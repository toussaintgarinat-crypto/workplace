"""Tests d'intégration de l'orchestrateur de tick (Sprint C) — DB réelle (même
motif que test_api.py), appels `personnages` mockés via respx quand une
naissance est tentée."""
import httpx
import pytest
import respx

import genome_moteur
import horloge_moteur
import stockage
import stockage_horloge
import stockage_spatial

PERSONNAGES_URL = "http://host.docker.internal:5900"


def _monde_avec_habitants(cle_api: str, n_cellules=2):
    cellules = [{"cellule_id": i, "x": float(i) * 100, "y": 500.0, "biome": "plaine",
                 "ressources": ["ble"], "voisins": [j for j in range(n_cellules) if j != i]}
                for i in range(n_cellules)]
    monde = stockage_spatial.creer_monde(cle_api, cellules, seed=42)
    stockage_horloge.initialiser_horloge(monde["id"])
    return monde


def _ajouter_habitant(cle_api: str, monde_id: str, cellule_id: int, sexe: str,
                       ne_au_tick: int = 0, theme: dict | None = None) -> str:
    """`theme` : dict au format portrait/theme_complet réel (voir PORTRAIT_FACTICE
    plus bas) SI cet habitant sera utilisé comme parent d'un croisement (via
    ReferenceParent) dans le test — sinon un dict vide suffit (jamais lu par la
    mécanique de tick elle-même, qui ne connaît qu'id/sexe/ne_au_tick, voir
    stockage_spatial.population_vivante_cellule)."""
    eid = stockage.creer(cle_api, "H", "X", None, None, theme or {}, "d", {}, False, sexe=sexe)
    stockage_spatial.placer(monde_id, eid, cellule_id, ne_au_tick=ne_au_tick)
    return eid


PORTRAIT_FACTICE = {
    "traditions": {"signe_solaire": {"nom": "Vierge"}},
    "portrait": {"archetype": "A", "forces": ["X", "Y"], "faiblesse": "Z"},
    "theme_complet": {
        "dominantes": {"planete": {"dominante": "Mercure"}, "signe": {"dominant": "Vierge"}},
        "dix_corps": {c: {"signe": "Vierge"} for c in
                      ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                       "Saturne", "Uranus", "Neptune", "Pluton"]},
    },
    "empreinte": [], "glossaire": [],
}


@pytest.mark.asyncio
async def test_tick_sans_habitants_avance_juste_le_compteur():
    monde = _monde_avec_habitants("cle-tk1")
    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk1")
    assert resultat["tick_actuel"] == 1
    assert resultat["naissances"] == 0
    assert resultat["morts"] == 0
    assert stockage_horloge.lire_horloge(monde["id"])["tick_actuel"] == 1


@pytest.mark.asyncio
async def test_tick_monde_introuvable_leve_404():
    with pytest.raises(genome_moteur.HTTPException) as exc:
        await horloge_moteur.executer_tick("id-inconnu", "cle-tk2")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_tick_regenere_ressources_et_progresse_technologie():
    monde = _monde_avec_habitants("cle-tk3")
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 10.0})
    _ajouter_habitant("cle-tk3", monde["id"], 0, "F", ne_au_tick=0)
    await horloge_moteur.executer_tick(monde["id"], "cle-tk3")
    stock_apres = stockage_spatial.lire_ressources_stock(monde["id"], 0)
    assert stock_apres["ble"] != 10.0  # a régénéré/consommé
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) >= 0.0


@pytest.mark.asyncio
async def test_tick_ne_tue_jamais_un_enfant_trop_jeune():
    monde = _monde_avec_habitants("cle-tk4")
    eid = _ajouter_habitant("cle-tk4", monde["id"], 0, "F", ne_au_tick=0)
    # 1 seul tick : âge = 1 << AGE_ADULTE_MIN, ne doit jamais mourir
    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk4")
    assert resultat["morts"] == 0
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0)[0]["id"] == eid


@respx.mock
@pytest.mark.asyncio
async def test_tick_naissance_couple_appelle_genome_moteur():
    monde = _monde_avec_habitants("cle-tk5")
    from horloge import PLAFOND_RESSOURCE
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": PLAFOND_RESSOURCE})
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    # ne_au_tick=-20 : simule un couple déjà adulte fécondable (âge > AGE_ADULTE_MIN=16)
    # dès le 1er tick, sans avoir à faire tourner des dizaines de ticks de vieillissement.
    # `theme=PORTRAIT_FACTICE` : ces 2 habitants seront réellement croisés via
    # ReferenceParent — leur `theme` stocké doit donc être portrait-shaped (lu par
    # genome_moteur._theme_parent puis fusion.fusionner_description).
    a = _ajouter_habitant("cle-tk5", monde["id"], 0, "F", ne_au_tick=-20, theme=PORTRAIT_FACTICE)
    b = _ajouter_habitant("cle-tk5", monde["id"], 0, "M", ne_au_tick=-20, theme=PORTRAIT_FACTICE)
    # Couple déjà actif AVANT ce tick (créé directement, pas via l'étape 5 du tick) :
    # un couple tout juste formé PAR le tick ne tente jamais une naissance ce même
    # tick (voir design/horloge_moteur.py) — il faut donc préexister à l'appel.
    stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    naissance_observee = False
    for _ in range(30):
        resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk5")
        if resultat["naissances"] > 0:
            naissance_observee = True
            break
    assert naissance_observee


@pytest.mark.asyncio
async def test_tick_couple_forme_ce_tick_ne_tente_pas_naissance_ce_meme_tick(monkeypatch):
    """Régression constraint 3 : un couple formé PENDANT ce tick (étape 5) ne doit
    jamais être éligible à une tentative de naissance CE MÊME tick (étape 6) —
    seuls les couples déjà actifs AVANT ce tick le sont. On force `former_couples`
    à former le couple à coup sûr et `tente_naissance_couple` à toujours réussir :
    si la naissance survient quand même, c'est que le tick a (à tort) inclus un
    couple fraîchement formé dans sa boucle de reproduction."""
    # n_cellules=1 : une seule cellule, donc le mock de `former_couples` (forcé à
    # toujours renvoyer ce couple) n'est invoqué qu'une fois par tick — avec
    # plusieurs cellules il serait appelé une fois par cellule et formerait le
    # même couple plusieurs fois, faussant l'assertion sur `couples_formes`.
    monde = _monde_avec_habitants("cle-tk6", n_cellules=1)
    # ne_au_tick=-20 : adultes fécondables dès ce tick, aucun couple préexistant.
    a = _ajouter_habitant("cle-tk6", monde["id"], 0, "F", ne_au_tick=-20)
    b = _ajouter_habitant("cle-tk6", monde["id"], 0, "M", ne_au_tick=-20)

    monkeypatch.setattr(horloge_moteur.horloge, "former_couples",
                         lambda *a_, **k: [(a, b)])
    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple",
                         lambda *a_, **k: True)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk6")

    assert resultat["couples_formes"] == 1
    assert resultat["naissances"] == 0


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("n_cellules", [1, 3])
async def test_scenario_plusieurs_ticks_population_evolue(n_cellules):
    """Bout-en-bout : peuple un monde de plusieurs adultes fécondables, avance
    suffisamment de ticks, vérifie qu'au moins une naissance OU une mort a eu lieu
    (les deux sont probabilistes — sur assez de ticks, au moins l'un des deux doit
    se produire, sinon la mécanique de tick ne fait rien d'observable).

    Paramétré sur `n_cellules` (correctif revue finale) : avec une SEULE cellule,
    « cellule voisine » et « cellule des parents » sont indistinguables, ce qui
    masquait structurellement toute la mécanique de placement/migration
    inter-cellules. La variante à 3 cellules exerce une vraie topologie."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    cle = f"cle-scenario-{n_cellules}"
    monde = _monde_avec_habitants(cle, n_cellules=n_cellules)
    for i in range(6):
        sexe = "F" if i % 2 == 0 else "M"
        # theme=PORTRAIT_FACTICE : certains de ces habitants seront réellement
        # croisés au fil des ticks (couples formés automatiquement par l'étape 5).
        _ajouter_habitant(cle, monde["id"], 0, sexe, ne_au_tick=-30, theme=PORTRAIT_FACTICE)
    for cid in range(n_cellules):
        stockage_spatial.ecrire_ressources_stock(monde["id"], cid, {"ble": 100.0})

    total_naissances = total_morts = 0
    for _ in range(50):
        resultat = await horloge_moteur.executer_tick(monde["id"], cle)
        total_naissances += resultat["naissances"]
        total_morts += resultat["morts"]

    assert total_naissances > 0 or total_morts > 0


# --- Correctifs revue finale Sprint C (bugs visibles seulement à la composition) ---

@respx.mock
@pytest.mark.asyncio
async def test_nouveau_ne_porte_le_tick_de_sa_naissance(monkeypatch):
    """Correctif revue finale (Important) : `genome_moteur.executer_croisement` relit
    l'horloge EN DIRECT pour fixer `ne_au_tick`. `marquer_execution` étant appelée en
    DERNIER, tout enfant né au tick N recevait `ne_au_tick = N-1` — le design §6
    exige `tick_actuel + 1`, c'est-à-dire le tick du résumé renvoyé."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    monde = _monde_avec_habitants("cle-tk-ne", n_cellules=2)
    a = _ajouter_habitant("cle-tk-ne", monde["id"], 0, "F", ne_au_tick=-20, theme=PORTRAIT_FACTICE)
    b = _ajouter_habitant("cle-tk-ne", monde["id"], 0, "M", ne_au_tick=-20, theme=PORTRAIT_FACTICE)
    stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)
    # Tirages neutralisés : le test porte sur `ne_au_tick`, pas sur les probabilités.
    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple", lambda *a_, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)

    # Un premier tick pour que le bug soit discriminant : au tick 2, un `ne_au_tick`
    # à 1 (valeur buggée) se distingue d'un `ne_au_tick` à 2 (valeur attendue).
    await horloge_moteur.executer_tick(monde["id"], "cle-tk-ne")
    avant = {h["id"] for hs in stockage_spatial.population_vivante_monde(monde["id"]).values()
             for h in hs}

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk-ne")
    assert resultat["tick_actuel"] == 2
    assert resultat["naissances"] >= 1, resultat["avertissements"]

    par_cellule = stockage_spatial.population_vivante_monde(monde["id"])
    nouveaux = [h for hs in par_cellule.values() for h in hs if h["id"] not in avant]
    assert nouveaux, "au moins un nouveau-né doit être placé"
    for nn in nouveaux:
        assert nn["ne_au_tick"] == resultat["tick_actuel"]


@pytest.mark.asyncio
async def test_tick_dissout_le_couple_d_un_habitant_qui_meurt(monkeypatch):
    """Correctif revue finale (Important) — design §3 : « tout couple actif
    impliquant cet habitant est dissous ». Sans ça le couple restait `actif=1` à
    jamais et le survivant restait exclu des célibataires de sa cellule."""
    monde = _monde_avec_habitants("cle-tk-mort", n_cellules=1)
    a = _ajouter_habitant("cle-tk-mort", monde["id"], 0, "F", ne_au_tick=-30)
    b = _ajouter_habitant("cle-tk-mort", monde["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    # Les 2 membres du couple meurent (âge 31 au tick 1) ; la dissolution aléatoire
    # (5 %/tick) est neutralisée pour que l'assertion ne porte QUE sur le décès.
    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda age, niveau, rng: age > 30)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk-mort")

    assert resultat["morts"] == 2
    assert resultat["couples_dissous"] == 1
    assert couple_id not in [c["id"] for c in
                              stockage_horloge.couples_actifs_cellule(monde["id"], 0)]
    assert stockage_horloge.couples_actifs_monde(monde["id"]) == {}


@pytest.mark.asyncio
async def test_tick_le_survivant_redevient_celibataire_le_tick_suivant(monkeypatch):
    """Corollaire du précédent : le membre SURVIVANT d'un couple dont l'autre meurt
    doit redevenir éligible aux célibataires de sa cellule dès ce tick."""
    monde = _monde_avec_habitants("cle-tk-veuf", n_cellules=1)
    morte = _ajouter_habitant("cle-tk-veuf", monde["id"], 0, "F", ne_au_tick=-30)
    veuf = _ajouter_habitant("cle-tk-veuf", monde["id"], 0, "M", ne_au_tick=-30)
    libre = _ajouter_habitant("cle-tk-veuf", monde["id"], 0, "F", ne_au_tick=-30)
    stockage_horloge.former_couple(monde["id"], 0, morte, veuf, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    # Seule `morte` meurt. `horloge.meurt` ne reçoit pas l'identité de l'habitant :
    # on s'appuie sur le fait qu'il est appelé une fois par habitant, dans l'ordre
    # de `population_vivante_monde` (même requête, même ordre que dans le tick).
    ordre = iter([h["id"] for h in stockage_spatial.population_vivante_monde(monde["id"])[0]])
    monkeypatch.setattr(horloge_moteur.horloge, "meurt",
                         lambda age, niveau, rng: next(ordre) == morte)
    # Le veuf doit pouvoir former un nouveau couple avec `libre` ce même tick.
    monkeypatch.setattr(horloge_moteur.horloge, "former_couples",
                         lambda f, m, rng: [(f[0], m[0])] if f and m else [])

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk-veuf")

    assert resultat["morts"] == 1
    assert resultat["couples_dissous"] == 1
    assert resultat["couples_formes"] == 1, (
        "le survivant doit redevenir célibataire dès la dissolution par décès")
    actifs = stockage_horloge.couples_actifs_cellule(monde["id"], 0)
    assert len(actifs) == 1
    assert {actifs[0]["habitant_a_id"], actifs[0]["habitant_b_id"]} == {veuf, libre}


@pytest.mark.asyncio
async def test_tick_le_couple_suit_l_habitant_qui_migre(monkeypatch):
    """Correctif revue finale (Important) : les couples étant indexés par cellule,
    un migrant dont le couple restait dans la cellule d'origine pouvait former un
    SECOND couple actif dans sa cellule d'arrivée (violation de l'invariant
    applicatif « un habitant n'a au plus qu'un couple actif à la fois »)."""
    monde = _monde_avec_habitants("cle-tk-mig", n_cellules=2)
    a = _ajouter_habitant("cle-tk-mig", monde["id"], 0, "F", ne_au_tick=-30)
    b = _ajouter_habitant("cle-tk-mig", monde["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a_, **k: True)
    # Seul `b` migre (vers la cellule 1, unique voisine).
    monkeypatch.setattr(horloge_moteur.horloge, "migre",
                         lambda rng: True)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk-mig")

    assert resultat["migrations"] == 2  # a et b migrent tous les deux vers la cellule 1
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []
    actifs_1 = stockage_horloge.couples_actifs_cellule(monde["id"], 1)
    assert [c["id"] for c in actifs_1] == [couple_id]


@pytest.mark.asyncio
async def test_deux_ticks_concurrents_sur_le_meme_monde_ne_s_entrelacent_pas(monkeypatch):
    """Correctif revue finale (Important) : `executer_tick` `await` (appel HTTP vers
    `personnages` lors d'une naissance), donc un tick manuel et le tick du scheduler
    sur le MÊME monde pouvaient partir du même `tick_actuel` et appliquer chacun un
    tick complet d'effets pour un seul tick d'avancement. Le verrou par monde les
    sérialise — le second appelant attend, il n'échoue pas.

    `executer_croisement` est remplacé par une coroutine qui `await` réellement :
    c'est LE point de suspension du tick, celui qui rend l'entrelacement possible.
    Sans lui, `asyncio.gather` exécuterait les deux ticks bout à bout (une coroutine
    sans suspension ne rend jamais la main) et le test ne prouverait rien.

    L'assertion ne peut pas se limiter à `tick_actuel == +2` : depuis que
    `marquer_execution` a été remontée AVANT les naissances (correctif `ne_au_tick`),
    la séquence lire→avancer l'horloge ne contient plus d'`await`, donc le compteur
    ne peut plus se perdre même sans verrou. Ce qui reste corruptible, c'est la phase
    de naissances : elle relit l'horloge EN DIRECT pour dater le nouveau-né. Sans
    verrou, un enfant du tick 1 se réveille après que le tick 2 a déjà avancé
    l'horloge et se retrouve daté du tick 2. On observe donc le tick vu AVANT et
    APRÈS la suspension de chaque naissance."""
    import asyncio

    monde = _monde_avec_habitants("cle-tk-lock", n_cellules=1)
    a = _ajouter_habitant("cle-tk-lock", monde["id"], 0, "F", ne_au_tick=-20)
    b = _ajouter_habitant("cle-tk-lock", monde["id"], 0, "M", ne_au_tick=-20)
    stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple", lambda *a_, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)

    observes: list[tuple[int, int]] = []

    async def _croisement_lent(corps, cle):
        avant = stockage_horloge.lire_horloge(monde["id"])["tick_actuel"]
        await asyncio.sleep(0.05)
        apres = stockage_horloge.lire_horloge(monde["id"])["tick_actuel"]
        observes.append((avant, apres))
        return {"enfant_id": None, "cellule_id": None, "avertissement": None}

    monkeypatch.setattr(horloge_moteur.genome_moteur, "executer_croisement", _croisement_lent)

    resultats = await asyncio.gather(
        horloge_moteur.executer_tick(monde["id"], "cle-tk-lock"),
        horloge_moteur.executer_tick(monde["id"], "cle-tk-lock"))

    assert sorted(r["tick_actuel"] for r in resultats) == [1, 2]
    assert stockage_horloge.lire_horloge(monde["id"])["tick_actuel"] == 2
    assert observes == [(1, 1), (2, 2)], (
        "l'horloge ne doit jamais bouger PENDANT la phase de naissances d'un tick "
        f"— entrelacement observé : {observes}")
