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
