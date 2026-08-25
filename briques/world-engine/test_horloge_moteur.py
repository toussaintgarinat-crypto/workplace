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


@pytest.mark.asyncio
async def test_le_partenaire_reste_sur_place_ne_forme_pas_un_second_couple(monkeypatch):
    """Correctif 2e revue finale (Important) : `deja_en_couple` était calculé sur les
    seuls couples indexés sur LA cellule traitée. Dès qu'un membre migre, le couple
    le suit (`deplacer_couples_habitants`) : le membre resté sur place ne voyait
    plus aucun couple dans sa propre cellule, retombait dans le vivier des
    célibataires et pouvait former un SECOND couple actif — les deux couples
    restaient alors `actif=1` en même temps pour le même habitant."""
    monde = _monde_avec_habitants("cle-tk-2couples", n_cellules=2)
    a = _ajouter_habitant("cle-tk-2couples", monde["id"], 0, "F", ne_au_tick=-30)
    b = _ajouter_habitant("cle-tk-2couples", monde["id"], 0, "M", ne_au_tick=-30)
    libre = _ajouter_habitant("cle-tk-2couples", monde["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    # Aucune naissance : le test porte sur les couples, pas sur la reproduction
    # (et `executer_croisement` appellerait `personnages` en HTTP réel).
    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "tenter_rencontres_occasionnelles",
                         lambda f, m, rng: [])

    # --- Tick 1 : SEUL `b` migre vers la cellule 1 ; son couple l'y suit. ---
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a_, **k: True)
    ordre = iter([h["id"] for h in stockage_spatial.population_vivante_monde(monde["id"])[0]])
    monkeypatch.setattr(horloge_moteur.horloge, "migre", lambda rng: next(ordre) == b)
    await horloge_moteur.executer_tick(monde["id"], "cle-tk-2couples")
    assert [c["id"] for c in stockage_horloge.couples_actifs_cellule(monde["id"], 1)] == [couple_id]
    assert stockage_spatial.population_vivante_cellule(monde["id"], 1)[0]["id"] == b

    # --- Tick 2 : `a` est seule dans la cellule 0 avec `libre`. Elle est TOUJOURS
    # en couple avec `b` (dans la cellule 1) : elle ne doit pas se réapparier. ---
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "former_couples",
                         lambda f, m, rng: [(f[0], m[0])] if f and m else [])

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk-2couples")

    assert resultat["couples_formes"] == 0, (
        "le membre resté sur place est encore en couple : aucun second couple ne "
        "doit se former")
    actifs = [c for cs in stockage_horloge.couples_actifs_monde(monde["id"]).values() for c in cs]
    assert [c["id"] for c in actifs] == [couple_id]
    assert actifs[0]["cellule_id"] == 1
    impliques = [c for c in actifs if a in (c["habitant_a_id"], c["habitant_b_id"])]
    assert len(impliques) == 1, "un habitant ne doit JAMAIS avoir 2 couples actifs à la fois"


@pytest.mark.asyncio
async def test_le_deces_dissout_le_couple_meme_parti_dans_une_autre_cellule(monkeypatch):
    """Correctif 2e revue finale (Important) : la dissolution par décès ne cherchait
    le couple du défunt que parmi les couples indexés sur SA cellule. Quand le
    partenaire avait migré avant (emportant la ligne du couple avec lui), le couple
    du défunt était invisible depuis sa propre cellule et survivait `actif=1` à
    jamais."""
    monde = _monde_avec_habitants("cle-tk-mort-loin", n_cellules=2)
    a = _ajouter_habitant("cle-tk-mort-loin", monde["id"], 0, "F", ne_au_tick=-30)
    b = _ajouter_habitant("cle-tk-mort-loin", monde["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "tenter_rencontres_occasionnelles",
                         lambda f, m, rng: [])

    # --- Tick 1 : SEUL `b` migre vers la cellule 1 ; le couple y est recalé. ---
    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a_, **k: True)
    ordre_mig = iter([h["id"] for h in stockage_spatial.population_vivante_monde(monde["id"])[0]])
    monkeypatch.setattr(horloge_moteur.horloge, "migre", lambda rng: next(ordre_mig) == b)
    await horloge_moteur.executer_tick(monde["id"], "cle-tk-mort-loin")
    assert [c["id"] for c in stockage_horloge.couples_actifs_cellule(monde["id"], 1)] == [couple_id]

    # --- Tick 2 : c'est `a` (restée cellule 0) qui meurt, alors que la ligne du
    # couple vit désormais cellule 1. Le couple doit quand même être dissous. ---
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a_, **k: False)
    # `horloge.meurt` ne reçoit pas l'identité de l'habitant : on s'appuie sur le
    # fait qu'il est appelé une fois par habitant, cellules dans l'ordre croissant
    # (même ordre que `population_vivante_monde`, voir le test du veuf).
    pop = stockage_spatial.population_vivante_monde(monde["id"])
    ordre_mort = iter([h["id"] for cid in sorted(pop) for h in pop[cid]])
    monkeypatch.setattr(horloge_moteur.horloge, "meurt",
                         lambda age, niveau, rng: next(ordre_mort) == a)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk-mort-loin")

    assert resultat["morts"] == 1
    assert resultat["couples_dissous"] == 1, (
        "le couple du défunt doit être trouvé et dissous même si sa ligne réside "
        "dans une autre cellule que la sienne")
    assert stockage_horloge.couples_actifs_monde(monde["id"]) == {}


# --- Sprint D : migration transfrontière ---

import stockage_federation


def _crf_pair(cle="cle-fed"):
    """2 pays d'1 cellule chacun, rattachés à une fédération et déclarés adjacents
    — topologie minimale pour exercer une émigration."""
    origine = _monde_avec_habitants(cle, n_cellules=1)
    destination = _monde_avec_habitants(cle, n_cellules=1)
    f = stockage_federation.creer_federation(cle, "F")
    stockage_federation.rattacher_pays(f["id"], origine["id"], cle, None)
    stockage_federation.rattacher_pays(f["id"], destination["id"], cle, None)
    stockage_federation.declarer_adjacence(f["id"], origine["id"], destination["id"])
    return origine, destination


def _crf_pair_multi_tenant(cle_origine: str, cle_destination: str, n_cellules=1):
    """Comme `_crf_pair`, mais les 2 pays appartiennent à des tenants DIFFÉRENTS —
    la configuration réellement fédérée (voir design : « une fédération peut
    mélanger des cle_api différentes ») que `_crf_pair` n'exerce jamais."""
    origine = _monde_avec_habitants(cle_origine, n_cellules=n_cellules)
    destination = _monde_avec_habitants(cle_destination, n_cellules=n_cellules)
    f = stockage_federation.creer_federation(cle_origine, "F")
    stockage_federation.rattacher_pays(f["id"], origine["id"], cle_origine, None)
    stockage_federation.rattacher_pays(f["id"], destination["id"], cle_destination, None)
    stockage_federation.declarer_adjacence(f["id"], origine["id"], destination["id"])
    return origine, destination


@respx.mock
@pytest.mark.asyncio
async def test_emigrant_vers_un_autre_tenant_reste_fecond_dans_son_nouveau_pays(monkeypatch):
    """Correctif revue finale (Important) : un habitant émigré vers un pays d'un
    AUTRE tenant ne pouvait plus jamais se reproduire. Le tick de destination
    appelle `genome_moteur.executer_croisement(..., cle_api_destination)`, qui
    résout les parents via `stockage.lire(cle_api, parent_id)` — cloisonné. La
    ligne `enfants` du migrant appartenant encore au tenant d'ORIGINE, la
    naissance échouait silencieusement (« enfant stocké introuvable » dans les
    `avertissements`), rendant le migrant stérile à vie chez lui.

    L'émigration transfère désormais la propriété de l'habitant au tenant du pays
    destination (`stockage.transferer_proprietaire`)."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    cle_o, cle_d = "cle-fed-tenant-o", "cle-fed-tenant-d"
    origine, destination = _crf_pair_multi_tenant(cle_o, cle_d)
    migrante = _ajouter_habitant(cle_o, origine["id"], 0, "F", ne_au_tick=-20,
                                  theme=PORTRAIT_FACTICE)
    local = _ajouter_habitant(cle_d, destination["id"], 0, "M", ne_au_tick=-20,
                               theme=PORTRAIT_FACTICE)

    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    resultat = await horloge_moteur.executer_tick(origine["id"], cle_o)
    assert resultat["migrations_transfrontieres"] == 1

    assert stockage.lire(cle_d, migrante) is not None, (
        "le migrant doit devenir un habitant du tenant du pays destination")
    assert stockage.lire(cle_o, migrante) is None, (
        "... et ne plus appartenir au tenant d'origine")

    # Il s'apparie sur place, puis son nouveau pays avance d'un tick : la naissance
    # doit ABOUTIR. Avant le correctif : 0 naissance + « introuvable » en avertissement.
    stockage_horloge.former_couple(destination["id"], 0, migrante, local, tick=0)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple", lambda *a_, **k: True)

    resultat_d = await horloge_moteur.executer_tick(destination["id"], cle_d)

    assert not any("introuvable" in a for a in resultat_d["avertissements"]), (
        resultat_d["avertissements"])
    assert resultat_d["naissances"] == 1, resultat_d["avertissements"]


@pytest.mark.asyncio
async def test_tick_emigre_habitant_cellule_saturee_pays_adjacent(monkeypatch):
    origine, destination = _crf_pair("cle-fed1")
    eid = _ajouter_habitant("cle-fed1", origine["id"], 0, "F", ne_au_tick=-20)

    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed1")

    assert resultat["migrations_transfrontieres"] == 1
    assert resultat["migrations"] == 0  # jamais les deux à la fois pour le même habitant
    assert stockage_spatial.population_vivante_cellule(origine["id"], 0) == []
    assert stockage_spatial.population_vivante_cellule(destination["id"], 0) == [
        {"id": eid, "sexe": "F", "ne_au_tick": stockage_spatial.population_vivante_cellule(
            destination["id"], 0)[0]["ne_au_tick"]}]


@pytest.mark.asyncio
async def test_emigration_preserve_lage_reel(monkeypatch):
    origine, destination = _crf_pair("cle-fed2")
    # habitant né au tick -20 : âgé de 21 au tick 1 (tick_suivant=1, age=1-(-20)=21)
    eid = _ajouter_habitant("cle-fed2", origine["id"], 0, "F", ne_au_tick=-20)
    # avance la destination de 10 ticks AVANT l'émigration, pour que ne_au_tick ne
    # puisse pas coïncider par hasard entre les 2 pays si le recalcul était omis
    for _ in range(10):
        await horloge_moteur.executer_tick(destination["id"], "cle-fed2")

    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)
    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed2")

    assert resultat["migrations_transfrontieres"] == 1
    arrive = stockage_spatial.population_vivante_cellule(destination["id"], 0)[0]
    assert arrive["id"] == eid
    # âge réel au départ = 1 - (-20) = 21 ; horloge destination était à 10, donc
    # ne_au_tick attendu = 10 - 21 = -11 (peut être négatif, comme n'importe quel
    # habitant "déjà adulte" injecté directement — voir _ajouter_habitant)
    assert arrive["ne_au_tick"] == -11


@pytest.mark.asyncio
async def test_emigration_dissout_le_couple_actif_avant_le_depart(monkeypatch):
    origine, destination = _crf_pair("cle-fed3")
    a = _ajouter_habitant("cle-fed3", origine["id"], 0, "F", ne_au_tick=-30)
    b = _ajouter_habitant("cle-fed3", origine["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(origine["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    # seul `a` émigre (ordre de population_vivante_monde : a avant b, voir tests Sprint C)
    ordre = iter([True, False])
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: next(ordre))

    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed3")

    assert resultat["migrations_transfrontieres"] == 1
    assert resultat["couples_dissous"] == 1
    assert stockage_horloge.couples_actifs_monde(origine["id"]) == {}


@pytest.mark.asyncio
async def test_ligne_origine_conservee_marquee_emigre_jamais_supprimee(monkeypatch):
    origine, destination = _crf_pair("cle-fed4")
    eid = _ajouter_habitant("cle-fed4", origine["id"], 0, "F", ne_au_tick=-20)

    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)
    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed4")

    with stockage_spatial._conn() as c:
        r = c.execute("SELECT * FROM placements WHERE monde_id=? AND enfant_id=?",
                       (origine["id"], eid)).fetchone()
    assert r is not None, "la ligne d'origine ne doit jamais être supprimée"
    assert r["vivant"] == 1
    assert r["mort_au_tick"] is None
    assert r["emigre"] == 1
    assert r["emigre_vers_monde_id"] == destination["id"]


@pytest.mark.asyncio
async def test_emigration_timeout_verrou_destination_echoue_proprement(monkeypatch):
    """Le pays destination a son verrou déjà tenu (simulé directement, sans passer
    par un vrai tick concurrent) : l'émigration doit échouer PROPREMENT (capturée
    dans avertissements), jamais planter le tick ni bloquer indéfiniment — voir
    design, correction sur le verrouillage inter-pays."""
    origine, destination = _crf_pair("cle-fed6")
    eid = _ajouter_habitant("cle-fed6", origine["id"], 0, "F", ne_au_tick=-30)
    conjoint = _ajouter_habitant("cle-fed6", origine["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(origine["id"], 0, eid, conjoint, tick=0)

    monkeypatch.setattr(horloge_moteur, "VERROU_DESTINATION_TIMEOUT_S", 0.05)
    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    # seul `eid` tente d'émigrer (ordre de population_vivante_monde : eid avant conjoint)
    ordre = iter([True, False])
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: next(ordre))

    verrou_destination = horloge_moteur._verrou_tick(destination["id"])
    await verrou_destination.acquire()
    try:
        resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed6")
    finally:
        verrou_destination.release()

    assert resultat["migrations_transfrontieres"] == 0
    assert any("verrou" in a.lower() for a in resultat["avertissements"])
    # l'habitant reste dans son pays d'origine, jamais marqué émigré
    assert stockage_spatial.population_vivante_cellule(origine["id"], 0)[0]["id"] == eid
    # ... et son couple SURVIT : une émigration avortée ne doit jamais détruire le
    # couple de quelqu'un qui n'est finalement pas parti (correctif revue Task 4).
    assert resultat["couples_dissous"] == 0
    actifs = stockage_horloge.couples_actifs_monde(origine["id"])
    assert [c["id"] for c in actifs.get(0, [])] == [couple_id]


@pytest.mark.asyncio
async def test_verrou_destination_libere_avant_la_boucle_de_naissances(monkeypatch):
    """Correctif revue finale (Important) : les écritures d'émigration venaient
    APRÈS la boucle de naissances, qui `await` un appel HTTP vers `personnages`
    (30 s de timeout PAR naissance). Les verrous de tick des pays DESTINATION
    restaient donc tenus pendant tout ce temps, bloquant derrière eux les ticks
    PROPRES d'un autre pays (défaut de débit, jamais de corruption).

    On observe l'état du verrou destination DEPUIS l'intérieur d'une naissance :
    il doit déjà être rendu."""
    import asyncio

    cle = "cle-fed-verrou-naissance"
    origine, destination = _crf_pair(cle)
    a = _ajouter_habitant(cle, origine["id"], 0, "F", ne_au_tick=-20)
    b = _ajouter_habitant(cle, origine["id"], 0, "M", ne_au_tick=-20)
    _ajouter_habitant(cle, origine["id"], 0, "F", ne_au_tick=-20)  # la partante
    stockage_horloge.former_couple(origine["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a_, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "tente_naissance_couple", lambda *a_, **k: True)
    # Seule la 3e habitante émigre (ordre de population_vivante_monde) : le couple
    # reste sur place pour que la naissance ait bien lieu ce tick.
    ordre = iter([False, False, True])
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: next(ordre))

    verrou_destination = horloge_moteur._verrou_tick(destination["id"])
    observes: list[bool] = []

    async def _croisement_lent(corps, cle_):
        observes.append(verrou_destination.locked())
        await asyncio.sleep(0)
        return {"enfant_id": None, "cellule_id": None, "avertissement": None}

    monkeypatch.setattr(horloge_moteur.genome_moteur, "executer_croisement", _croisement_lent)

    resultat = await horloge_moteur.executer_tick(origine["id"], cle)

    assert resultat["migrations_transfrontieres"] == 1
    assert observes, "prérequis du test : au moins une naissance doit être tentée"
    assert not any(observes), (
        "le verrou du pays destination ne doit plus être tenu pendant la boucle de "
        f"naissances — observé : {observes}")
    assert not verrou_destination.locked()


@pytest.mark.asyncio
async def test_auto_adjacence_ignoree_jamais_d_emigration_vers_soi_meme(monkeypatch):
    """Un pays déclaré adjacent à LUI-MÊME ne doit jamais être une destination de
    migration : sinon chaque émigrant viserait le pays dont le verrou de tick est
    déjà tenu par ce tick même (verrou non réentrant) et attendrait le timeout
    complet, un par un — N × VERROU_DESTINATION_TIMEOUT_S de blocage par tick
    (correctif revue Task 4). Le timeout est volontairement laissé à sa valeur
    NORMALE ici : si l'auto-adjacence n'était pas filtrée, le test durerait des
    dizaines de secondes au lieu de terminer instantanément."""
    monde = _monde_avec_habitants("cle-fed7", n_cellules=1)
    f = stockage_federation.creer_federation("cle-fed7", "F")
    stockage_federation.rattacher_pays(f["id"], monde["id"], "cle-fed7", None)
    stockage_federation.declarer_adjacence(f["id"], monde["id"], monde["id"])
    assert stockage_federation.pays_adjacents(monde["id"]) == [monde["id"]], (
        "prérequis du test : l'auto-adjacence est bien stockée en amont")

    ids = [_ajouter_habitant("cle-fed7", monde["id"], 0, "F", ne_au_tick=-20)
           for _ in range(4)]
    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-fed7")

    assert resultat["migrations_transfrontieres"] == 0
    assert not any("verrou" in a.lower() for a in resultat["avertissements"])
    # personne n'a été marqué émigré : tout le monde est encore là
    assert sorted(h["id"] for h in stockage_spatial.population_vivante_cellule(
        monde["id"], 0)) == sorted(ids)


@pytest.mark.asyncio
async def test_pas_de_pays_adjacent_jamais_d_emigration(monkeypatch):
    """Un pays hors fédération (ou sans adjacence déclarée) ne doit jamais tenter
    de migration transfrontière, même si le jet aurait toujours réussi."""
    monde = _monde_avec_habitants("cle-fed5", n_cellules=1)
    _ajouter_habitant("cle-fed5", monde["id"], 0, "F", ne_au_tick=-20)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-fed5")

    assert resultat["migrations_transfrontieres"] == 0


@pytest.mark.asyncio
async def test_determinisme_migration_transfrontiere_meme_seed(monkeypatch):
    """Même motif que le déterminisme Sprint C : même (seed, tick, cellule) ⇒
    mêmes décisions de migration transfrontière sur 2 exécutions isolées (2
    fédérations parallèles indépendantes avec le même seed d'origine)."""
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    resultats = []
    for suffixe in ("x", "y"):
        cle = f"cle-fed-det-{suffixe}"
        cellules = [{"cellule_id": 0, "x": 0.0, "y": 0.0, "biome": "plaine",
                     "ressources": ["ble"], "voisins": []}]
        origine = stockage_spatial.creer_monde(cle, cellules, seed=999)
        stockage_horloge.initialiser_horloge(origine["id"])
        destination = stockage_spatial.creer_monde(cle, cellules, seed=1)
        stockage_horloge.initialiser_horloge(destination["id"])
        f = stockage_federation.creer_federation(cle, "F")
        stockage_federation.rattacher_pays(f["id"], origine["id"], cle, None)
        stockage_federation.rattacher_pays(f["id"], destination["id"], cle, None)
        stockage_federation.declarer_adjacence(f["id"], origine["id"], destination["id"])
        for i in range(10):
            _ajouter_habitant(cle, origine["id"], 0, "F" if i % 2 == 0 else "M", ne_au_tick=-20)

        resultat = await horloge_moteur.executer_tick(origine["id"], cle)
        resultats.append(resultat["migrations_transfrontieres"])

    assert resultats[0] == resultats[1]


@respx.mock
@pytest.mark.asyncio
async def test_bout_en_bout_migration_transfrontiere_reelle_sur_plusieurs_ticks():
    """Scénario bout-en-bout exigé par le design (section « Tests prévus ») et
    absent jusqu'ici : deux pays rattachés à une fédération, adjacence déclarée,
    plusieurs ticks avancés sur CHACUN indépendamment, au moins une migration
    transfrontière observée.

    Contrairement à tous les autres tests Sprint D de ce fichier, ni
    `cellule_saturee` ni `migre_frontiere` ne sont monkeypatchés : c'est la VRAIE
    chaîne probabiliste (`PROBABILITE_MIGRATION_FRONTIERE = 0.05`, saturation
    calculée sur les ressources réelles) qui est exercée. Test volontairement
    probabiliste et un peu lent, même classe que
    `test_scenario_plusieurs_ticks_population_evolue`.

    Les 2 pays appartiennent à des tenants DIFFÉRENTS : le transfert de propriété
    des émigrants (`stockage.transferer_proprietaire`) est donc lui aussi exercé
    de bout en bout, sans mock.

    Calibrage de la saturation, sans truquer la mécanique : une cellule est saturée
    quand `population > stock total`. Le stock est semé à 1.0 (au lieu du
    demi-plafond 50.0) pour saturer dès le 1er tick plutôt qu'au bout d'une
    dizaine, et 10 habitants par cellule consomment plus que la régénération
    (`(100 − q) × 0.10 < 10` dès `q > 0`) : la cellule reste donc drainée, donc
    saturée, tout le long. 20 habitants × 0.05 × 30 ticks ⇒ probabilité de
    n'observer AUCUN passage de frontière de l'ordre de 1e-13."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    cle_o, cle_d = "cle-e2e-origine", "cle-e2e-destination"
    origine, destination = _crf_pair_multi_tenant(cle_o, cle_d, n_cellules=2)
    for cid in range(2):
        for i in range(10):
            _ajouter_habitant(cle_o, origine["id"], cid, "F" if i % 2 == 0 else "M",
                               ne_au_tick=-20, theme=PORTRAIT_FACTICE)
        stockage_spatial.ecrire_ressources_stock(origine["id"], cid, {"ble": 1.0})
        stockage_spatial.ecrire_ressources_stock(destination["id"], cid, {"ble": 1.0})

    total_transfrontieres = 0
    for _ in range(30):
        # Chaque pays avance INDÉPENDAMMENT (aucune synchronisation de tick entre
        # pays d'une fédération — voir design).
        total_transfrontieres += (
            await horloge_moteur.executer_tick(origine["id"], cle_o))["migrations_transfrontieres"]
        total_transfrontieres += (
            await horloge_moteur.executer_tick(destination["id"], cle_d))["migrations_transfrontieres"]

    assert total_transfrontieres > 0, (
        "aucune migration transfrontière observée sur 30 ticks × 2 pays adjacents "
        "peuplés et saturés — la chaîne probabiliste réelle ne se déclenche jamais")

    # Le pays destination est réellement peuplé, et TOUS ses habitants vivants
    # appartiennent bien à SON tenant (immigrants transférés compris) : sans le
    # transfert de propriété, un immigrant resterait illisible pour `cle_d` et
    # stérile chez lui.
    arrivants = [h for hs in stockage_spatial.population_vivante_monde(destination["id"]).values()
                 for h in hs]
    assert arrivants, "le pays destination doit avoir reçu au moins un habitant"
    illisibles = [h["id"] for h in arrivants if stockage.lire(cle_d, h["id"]) is None]
    assert illisibles == [], (
        f"habitants du pays destination inaccessibles à son propre tenant : {illisibles}")
