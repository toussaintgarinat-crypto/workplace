"""Tests API de world-engine."""
import importlib

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import main
import stockage
import stockage_horloge
import stockage_spatial

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_auth_rejette_cle_absente_quand_api_keys_configuree(monkeypatch):
    """Teste directement cle_api() pour vérifier le rejet d'une clé manquante/invalide."""
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    # Clé absente → rejet
    with pytest.raises(main.HTTPException) as exc:
        main.cle_api(x_api_key=None, authorization=None)
    assert exc.value.status_code == 401
    # Clé invalide → rejet
    with pytest.raises(main.HTTPException) as exc:
        main.cle_api(x_api_key="mauvaise-cle", authorization=None)
    assert exc.value.status_code == 401
    # Clé valide → acceptée
    result = main.cle_api(x_api_key="vraie-cle", authorization=None)
    assert result == "vraie-cle"
    # Bearer token valide → acceptée
    result = main.cle_api(x_api_key=None, authorization="Bearer vraie-cle")
    assert result == "vraie-cle"
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # main.app est un NOUVEL objet après reload — resynchronise
                                    # le client de test, sinon les tests suivants tournent contre
                                    # les classes Pydantic (Croisement/ReferenceParent) FIGÉES
                                    # d'avant ce reload et l'isinstance() de _theme_parent échoue.


def test_sante_jamais_protegee_meme_avec_api_keys(monkeypatch):
    """/sante reste accessible sans clé, même si API_KEYS est configurée."""
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    c = TestClient(main.app)
    assert c.get("/sante").status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # même resynchronisation qu'au-dessus.


PERSONNAGES_URL = "http://host.docker.internal:5900"

_FICHE_A = {"prenoms": "Théo", "date_naissance": "1985-03-10", "heure_naissance": "08:00",
            "latitude": 48.85, "longitude": 2.35, "utc_offset": 1.0}
_FICHE_B = {"prenoms": "Léa", "date_naissance": "1988-07-22", "heure_naissance": "16:20",
            "latitude": 45.76, "longitude": 4.83, "utc_offset": 2.0}


def _portrait_factice(dominante_planete="Mercure", dominante_signe="Vierge",
                       signe_dix_corps="Vierge") -> dict:
    """`signe_dix_corps` est appliqué IDENTIQUEMENT aux 10 corps (fixture minimale) —
    fait varier ce paramètre entre 2 appels pour tester la comparaison d'hérédité."""
    return {
        "traditions": {"signe_solaire": {"nom": "Vierge"}},
        "portrait": {"archetype": "Le Gardien", "forces": ["Sagesse", "Stabilité", "Émotivité"],
                     "faiblesse": "Combativité"},
        "theme_complet": {
            "dominantes": {"planete": {"dominante": dominante_planete},
                            "signe": {"dominant": dominante_signe}},
            "dix_corps": {c: {"signe": signe_dix_corps} for c in
                          ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                           "Saturne", "Uranus", "Neptune", "Pluton"]},
        },
        "empreinte": [], "glossaire": [],
    }


@respx.mock
def test_genome_croiser_chemin_heureux():
    route_portrait = respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),   # parent A
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),        # parent B
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])    # enfant
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "prenoms_enfant": "Nova", "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    data = r.json()
    assert data["enfant"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"
    assert data["heredite"]["resume"] == {"A": 10, "B": 0, "commun": 0, "mutation": 0}
    assert data["mutation_survenue"] is False
    assert "description_genome" in data
    assert isinstance(data["enfant_id"], str) and data["enfant_id"]
    assert data["avertissement"] is None
    stocke = stockage.lire("public", data["enfant_id"])
    assert stocke["prenoms"] == "Nova"
    assert stocke["parent_a_id"] is None   # parent_a était une fiche brute, pas une référence
    assert stocke["parent_b_id"] is None

    # Correctif revue finale : verrouille le corps EXACT envoyé à personnages pour
    # l'enfant (date dérivée du signe avec marge anti-cuspide, heure/lieu/utc_offset
    # propagés tels quels — jamais None, jamais une valeur d'un parent copiée par erreur).
    import json as _json
    fiche_enfant_envoyee = _json.loads(route_portrait.calls[2].request.content)
    assert fiche_enfant_envoyee == {
        "prenoms": "Nova", "nom": "", "date_naissance": "2015-08-27",
        "heure_naissance": "10:00", "latitude": 43.6, "longitude": 1.44, "utc_offset": 1.0}


@respx.mock
def test_genome_croiser_sexe_absent_du_corps_envoye_a_personnages():
    """Correctif revue finale (Important) : `sexe` est un rôle DANS ce croisement
    (placement, Sprint B), jamais un trait de la fiche envoyée à `personnages` — ne
    doit jamais franchir la frontière de la brique, même si `personnages` l'ignore
    aujourd'hui par défaut Pydantic (extra="ignore")."""
    route_portrait = respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),   # parent A
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),        # parent B
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])    # enfant
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {**_FICHE_A, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200

    import json as _json
    corps_parent_a = _json.loads(route_portrait.calls[0].request.content)
    assert "sexe" not in corps_parent_a


@respx.mock
def test_genome_croiser_personnages_injoignable_502():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(side_effect=httpx.ConnectError("down"))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 502


@respx.mock
def test_genome_croiser_fiche_parent_invalide_propage_422():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(422, json={"detail": "Fiche insuffisante."}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"prenoms": "X"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_aucun_signe_reconnu_422():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice()))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": []}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_parent_a_422_prioritaire_meme_si_b_indisponible():
    """Correctif : A doit être entièrement résolu avant que B soit appelé. Si A est
    invalide (422) et que B serait injoignable, la réponse doit rester 422 (pas 502)."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(422, json={"detail": "Fiche A insuffisante."})])
    r = client.post("/genome/croiser", json={
        "parent_a": {"prenoms": "X"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_detail_replie_sur_texte_si_corps_non_dict():
    """Correctif : _detail() ne doit jamais lever, même si le corps d'erreur de
    personnages est un JSON valide mais pas un objet (ex: une liste)."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(422, json=["erreur inattendue"]))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_sans_heure_enfant_422():
    """heure_naissance_enfant est requis (Pydantic) : sans lui, 422 avant tout appel réseau.
    @respx.mock sans aucune route enregistrée : si la garde Pydantic régressait, le moindre
    appel HTTP réel serait intercepté et lèverait plutôt que de pendre sur host.docker.internal."""
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44, "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_parent_theme_degrade_422():
    """personnages peut répondre 200 avec un theme_complet DÉGRADÉ (sans heure de
    naissance côté parent) — pas une erreur de son côté, mais world-engine doit
    refuser honnêtement plutôt que de planter en KeyError sur dominantes/dix_corps
    absents (Critical de la revue finale)."""
    theme_degrade = _portrait_factice()
    del theme_degrade["theme_complet"]["dominantes"]
    del theme_degrade["theme_complet"]["dix_corps"]
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=theme_degrade))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_parent_a_theme_degrade_prioritaire_meme_si_b_indisponible():
    """Correctif revue finale (round 2) : le contrôle sémantique de A (thème dégradé)
    doit être résolu AVANT tout appel réseau pour B — même invariant que le correctif
    HTTP de statut (commit 1fc80ce), réintroduit un temps sur le contrôle sémantique
    par le correctif Critical précédent. Si A est dégradé et que B serait injoignable,
    la réponse doit rester 422 (pas 502)."""
    theme_degrade = _portrait_factice()
    del theme_degrade["theme_complet"]["dominantes"]
    del theme_degrade["theme_complet"]["dix_corps"]
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=theme_degrade)])
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_401_personnages_devient_502():
    """Un 401 de personnages (ex: WORLD_ENGINE_KEY mal configurée côté world-engine)
    ne doit JAMAIS être confondu avec un rejet DE L'APPELANT : mappé en 502, pas
    propagé tel quel (Important de la revue finale)."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(401, json={"detail": "Clé API manquante ou invalide."}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 502


@respx.mock
def test_genome_croiser_parent_a_par_id_reutilise_stockage():
    """parent_a peut être {"id": ...} référençant un enfant déjà stocké : son thème
    est relu depuis stockage.py, personnages n'est PAS rappelé pour ce parent."""
    theme_stocke = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          theme_stocke, "desc", {"resume": {}}, False)

    route_portrait = respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),   # parent B
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])  # enfant
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))

    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid}, "parent_b": _FICHE_B,
        "prenoms_enfant": "Nova2", "heure_naissance_enfant": "10:00",
        "latitude_enfant": 43.6, "longitude_enfant": 1.44, "utc_offset_enfant": 1.0,
        "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    assert route_portrait.call_count == 2  # parent B + enfant seulement — PAS parent A


@respx.mock
def test_genome_croiser_parent_id_introuvable_404():
    """@respx.mock sans aucune route enregistrée : si l'id-lookup régressait vers un
    appel réseau, ça lèverait plutôt que de pendre sur host.docker.internal."""
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": "id-inconnu"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 404


def _monde_factice(n=10):
    """Monde déterministe pour les tests de placement : chaque cellule i a pour
    SEULE voisine (i+1)%n — évite toute dépendance à la géométrie Voronoï réelle
    (déjà testée dans test_spatial.py/test_stockage_spatial.py)."""
    cellules = [{"cellule_id": i, "x": float(i), "y": float(i), "biome": "plaine",
                 "ressources": [], "voisins": [(i + 1) % n]} for i in range(n)]
    return stockage_spatial.creer_monde("public", cellules, seed=1)


@respx.mock
def test_genome_croiser_place_enfant_voisin_du_parent_si_place():
    monde = _monde_factice()
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid_mere, 0)  # seule voisine de 0 : cellule 1

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_mere, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 1


@respx.mock
def test_genome_croiser_sans_monde_id_pas_de_placement():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    assert r.json()["cellule_id"] is None


@respx.mock
def test_genome_croiser_parent_fiche_brute_placement_aleatoire_borne():
    monde = _monde_factice()
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {**_FICHE_A, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert 0 <= r.json()["cellule_id"] < 10


@respx.mock
def test_genome_croiser_parent_stocke_non_place_placement_aleatoire_borne():
    monde = _monde_factice()
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    # eid_mere n'a jamais été placé sur aucun monde

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_mere, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert 0 <= r.json()["cellule_id"] < 10


@respx.mock
def test_genome_croiser_parent_place_dans_un_autre_monde_placement_aleatoire_borne():
    monde_a = _monde_factice()
    monde_b = _monde_factice()
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde_a["id"], eid_mere, 0)  # placée dans monde_a...

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_mere, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde_b["id"]})  # ...mais le croisement cible monde_b
    assert r.status_code == 200
    assert 0 <= r.json()["cellule_id"] < 10


@respx.mock
def test_genome_croiser_monde_id_introuvable_404():
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "monde_id": "id-inconnu"})
    assert r.status_code == 404


@respx.mock
def test_genome_croiser_parent_b_marque_f_devient_reference():
    monde = _monde_factice()
    theme_pere = _portrait_factice("Mars", "Bélier", "Bélier")
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_pere = stockage.creer("public", "Pere", "", None, None, theme_pere, "d", {"resume": {}}, False)
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid_mere, 3)  # seule voisine de 3 : cellule 4

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_pere, "sexe": "M"}, "parent_b": {"id": eid_mere, "sexe": "F"},
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 4


@respx.mock
def test_genome_croiser_deux_parents_marques_f_parent_a_gagne():
    monde = _monde_factice()
    theme_a = _portrait_factice("Mercure", "Vierge", "Vierge")
    theme_b = _portrait_factice("Mars", "Bélier", "Bélier")
    eid_a = stockage.creer("public", "A", "", None, None, theme_a, "d", {"resume": {}}, False)
    eid_b = stockage.creer("public", "B", "", None, None, theme_b, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid_a, 0)   # seule voisine de 0 : cellule 1
    stockage_spatial.placer(monde["id"], eid_b, 5)   # seule voisine de 5 : cellule 6 (disjoint de 1)

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_a, "sexe": "F"}, "parent_b": {"id": eid_b, "sexe": "F"},
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 1  # parent_a (0→1), pas parent_b (5→6)


def test_genome_enfants_lister_et_lire():
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          _portrait_factice(), "desc", {"resume": {"A": 1}}, False)

    r = client.get("/genome/enfants")
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()]
    assert eid in ids
    assert "theme" not in r.json()[0]   # liste allégée

    r2 = client.get(f"/genome/enfants/{eid}")
    assert r2.status_code == 200
    assert r2.json()["prenoms"] == "Nova"
    assert r2.json()["theme"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"


def test_genome_enfant_lire_introuvable_404():
    r = client.get("/genome/enfants/id-inconnu")
    assert r.status_code == 404


def test_genome_enfants_cloisonnes_par_cle_api(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    eid = main.stockage.creer("cle-x", "Secret", "", None, None,
                               _portrait_factice(), "d", {"resume": {}}, False)
    r_x = c.get("/genome/enfants", headers={"X-API-Key": "cle-x"})
    r_y = c.get("/genome/enfants", headers={"X-API-Key": "cle-y"})
    assert any(e["id"] == eid for e in r_x.json())
    assert not any(e["id"] == eid for e in r_y.json())
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # même resynchronisation que les 2 tests d'auth
                                    # au-dessus — sinon les tests suivants qui
                                    # exercent {"id": ...} tournent contre les
                                    # classes Pydantic FIGÉES d'avant ce reload.


def test_genome_enfant_supprimer():
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          _portrait_factice(), "d", {"resume": {}}, False)
    r = client.delete(f"/genome/enfants/{eid}")
    assert r.status_code == 204
    assert client.get(f"/genome/enfants/{eid}").status_code == 404


def test_genome_enfant_supprimer_introuvable_404():
    r = client.delete("/genome/enfants/id-inconnu")
    assert r.status_code == 404


def test_genome_enfant_supprimer_purge_placement_spatial_orphelin():
    """Correctif revue finale (Minor) : supprimer un enfant placé sur un monde ne
    doit pas laisser de rangée `placements` morte dans stockage_spatial.py."""
    monde = _monde_factice()
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          _portrait_factice(), "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid, 0)
    assert stockage_spatial.placement_cellule(monde["id"], eid) == 0

    r = client.delete(f"/genome/enfants/{eid}")
    assert r.status_code == 204
    assert stockage_spatial.placement_cellule(monde["id"], eid) is None


@respx.mock
def test_genome_croiser_stockage_echoue_repond_quand_meme(monkeypatch):
    """Un échec d'écriture SQLite après un croisement réussi ne fait jamais échouer
    la requête : le calcul est bon, seule la persistance a un problème."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))

    def _echec(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(main.stockage, "creer", _echec)

    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    data = r.json()
    assert data["enfant_id"] is None
    assert data["avertissement"] is not None and "disque plein" in data["avertissement"]


@respx.mock
def test_genome_croiser_monde_supprime_pendant_croisement_avertissement_lisible(monkeypatch):
    """Correctif revue finale (Minor) : course rare (TOCTOU) — le monde est supprimé
    entre le monde_existe() en tête de route et le placement. Avant le correctif,
    rng.randrange(None) levait un TypeError opaque ; l'avertissement doit maintenant
    être un message lisible. Même motif que test_genome_croiser_stockage_echoue_repond_quand_meme."""
    monde = _monde_factice()
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))

    def _monde_supprime_entretemps(monde_id):
        return None
    monkeypatch.setattr(main.stockage_spatial, "nb_cellules_monde", _monde_supprime_entretemps)

    r = client.post("/genome/croiser", json={
        "parent_a": {**_FICHE_A, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    data = r.json()
    assert data["cellule_id"] is None
    assert data["avertissement"] is not None
    assert "supprimé" in data["avertissement"]
    assert "TypeError" not in data["avertissement"]


def test_genome_arbre_trois_generations():
    gp = stockage.creer("public", "GrandParent", "", None, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    p = stockage.creer("public", "Parent", "", gp, None,
                        _portrait_factice(), "d", {"resume": {}}, False)
    e = stockage.creer("public", "Enfant", "", p, None,
                        _portrait_factice(), "d", {"resume": {}}, False)

    r = client.get(f"/genome/arbre/{e}")
    assert r.status_code == 200
    arbre = r.json()
    assert arbre["id"] == e
    assert arbre["parent_a"]["id"] == p
    assert arbre["parent_a"]["parent_a"]["id"] == gp
    assert arbre["parent_a"]["parent_a"]["parent_a"] is None
    assert arbre["parent_b"] is None


def test_genome_arbre_branche_tronquee_apres_suppression():
    gp = stockage.creer("public", "GrandParent", "", None, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    e = stockage.creer("public", "Enfant", "", gp, None,
                        _portrait_factice(), "d", {"resume": {}}, False)
    stockage.supprimer("public", gp)

    r = client.get(f"/genome/arbre/{e}")
    assert r.status_code == 200
    assert r.json()["parent_a"] is None   # gp supprimé, branche tronquée, pas d'erreur


def test_genome_arbre_racine_introuvable_404():
    r = client.get("/genome/arbre/id-inconnu")
    assert r.status_code == 404


def test_genome_arbre_ancetre_partage_devient_stub_pas_reexpanse():
    """La lignée est un DAG, pas un arbre : gp est partagé par p1 et p2 (pedigree
    collapse). Correctif Critical revue finale : la 2e apparition de gp doit être
    un stub `deja_present` — pas un noeud entièrement redéveloppé (parent_a/parent_b),
    sans quoi la réexpansion explose exponentiellement avec la profondeur."""
    gp = stockage.creer("public", "GrandParent", "", None, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    p1 = stockage.creer("public", "Parent1", "", gp, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    p2 = stockage.creer("public", "Parent2", "", gp, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    e = stockage.creer("public", "Enfant", "", p1, p2,
                        _portrait_factice(), "d", {"resume": {}}, False)

    r = client.get(f"/genome/arbre/{e}")
    assert r.status_code == 200
    arbre = r.json()
    assert arbre["parent_a"]["id"] == p1
    assert arbre["parent_b"]["id"] == p2

    premier_gp = arbre["parent_a"]["parent_a"]
    second_gp = arbre["parent_b"]["parent_a"]
    assert premier_gp["id"] == gp
    assert second_gp["id"] == gp
    # Le 1er atteint (via p1) est pleinement développé...
    assert "parent_a" in premier_gp and "parent_b" in premier_gp
    assert premier_gp.get("deja_present") is not True
    # ...le 2e (via p2, même gp) est un stub : pas re-développé, marqué deja_present.
    assert second_gp.get("deja_present") is True
    assert "parent_a" not in second_gp and "parent_b" not in second_gp


@respx.mock
def test_genome_croiser_refuse_auto_croisement_422():
    """Croiser un enfant stocké avec lui-même (même id des deux côtés) est le cas
    le plus pathologique du problème d'ancêtre partagé — refusé avant tout appel
    réseau. @respx.mock sans route enregistrée : un appel HTTP réel lèverait."""
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          _portrait_factice(), "d", {"resume": {}}, False)
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid}, "parent_b": {"id": eid},
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 422
    assert "lui-même" in r.json()["detail"]


@respx.mock
def test_genome_croiser_sexe_enfant_persiste():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice()),
                     httpx.Response(200, json=_portrait_factice()),
                     httpx.Response(200, json=_portrait_factice())])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 48.0, "longitude_enfant": 2.0,
        "heure_naissance_enfant": "10:00", "utc_offset_enfant": 1.0,
        "sexe_enfant": "M"})
    assert r.status_code == 200
    eid = r.json()["enfant_id"]
    enfant = client.get(f"/genome/enfants/{eid}").json()
    assert enfant["sexe"] == "M"


def test_spatial_monde_creer_puis_lire():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 42})
    assert r.status_code == 200
    meta = r.json()
    assert meta["nb_cellules"] == 10
    assert meta["seed"] == 42

    r2 = client.get(f"/spatial/mondes/{meta['id']}")
    assert r2.status_code == 200
    monde = r2.json()
    assert len(monde["cellules"]) == 10


def test_spatial_monde_creer_sans_seed_genere_un_seed():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10})
    assert r.status_code == 200
    assert isinstance(r.json()["seed"], int)


def test_spatial_monde_creer_nb_cellules_hors_bornes_422():
    assert client.post("/spatial/mondes", json={"nb_cellules": 5}).status_code == 422
    assert client.post("/spatial/mondes", json={"nb_cellules": 3000}).status_code == 422


def test_spatial_mondes_lister():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1})
    mid = r.json()["id"]
    r2 = client.get("/spatial/mondes")
    assert any(m["id"] == mid for m in r2.json())
    assert "cellules" not in r2.json()[0]


def test_spatial_monde_lire_introuvable_404():
    assert client.get("/spatial/mondes/id-inconnu").status_code == 404


def test_spatial_cellule_lire():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    r = client.get(f"/spatial/mondes/{mid}/cellules/0")
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 0
    assert client.get(f"/spatial/mondes/{mid}/cellules/999").status_code == 404


def test_spatial_monde_forker():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    r = client.post(f"/spatial/mondes/{mid}/forker")
    assert r.status_code == 200
    fork = r.json()
    assert fork["forked_from_id"] == mid
    assert fork["id"] != mid
    assert client.get(f"/spatial/mondes/{fork['id']}").status_code == 200


def test_spatial_monde_forker_introuvable_404():
    assert client.post("/spatial/mondes/id-inconnu/forker").status_code == 404


def test_spatial_monde_supprimer():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    r = client.delete(f"/spatial/mondes/{mid}")
    assert r.status_code == 204
    assert client.get(f"/spatial/mondes/{mid}").status_code == 404


def test_spatial_monde_supprimer_introuvable_404():
    assert client.delete("/spatial/mondes/id-inconnu").status_code == 404


def test_spatial_mondes_cloisonnes_par_cle_api(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                  headers={"X-API-Key": "cle-x"}).json()["id"]
    r_x = c.get(f"/spatial/mondes/{mid}", headers={"X-API-Key": "cle-x"})
    r_y = c.get(f"/spatial/mondes/{mid}", headers={"X-API-Key": "cle-y"})
    assert r_x.status_code == 200
    assert r_y.status_code == 404
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # resynchronise après reload, même motif que les autres
                                    # tests d'auth de ce fichier.


def test_spatial_forker_cloisonne_par_cle_api(monkeypatch):
    """Correctif revue finale (Important) : gap de couverture cloisonnement — la
    seule opération /spatial/* qui crée une copie (fork) n'avait aucun test HTTP-level
    de cloisonnement. Même motif que test_spatial_mondes_cloisonnes_par_cle_api."""
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                  headers={"X-API-Key": "cle-x"}).json()["id"]
    r_y = c.post(f"/spatial/mondes/{mid}/forker", headers={"X-API-Key": "cle-y"})
    assert r_y.status_code == 404
    r_x = c.post(f"/spatial/mondes/{mid}/forker", headers={"X-API-Key": "cle-x"})
    assert r_x.status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # resynchronise après reload, même motif que les autres
                                    # tests d'auth de ce fichier.


def test_spatial_monde_creer_meme_seed_meme_maillage():
    """Bout-en-bout : même (nb_cellules, seed) ⇒ même maillage — les deux mondes créés
    séparément doivent avoir des cellules identiques (biome/ressources/voisins/x/y par
    cellule_id), seuls id/cree_le du monde lui-même diffèrent légitimement."""
    r1 = client.post("/spatial/mondes", json={"nb_cellules": 15, "seed": 777})
    r2 = client.post("/spatial/mondes", json={"nb_cellules": 15, "seed": 777})
    assert r1.status_code == 200 and r2.status_code == 200
    id1, id2 = r1.json()["id"], r2.json()["id"]
    assert id1 != id2

    monde1 = client.get(f"/spatial/mondes/{id1}").json()
    monde2 = client.get(f"/spatial/mondes/{id2}").json()

    def _sans_champs_identite(cellules):
        return [{k: v for k, v in cel.items() if k != "enfants"} for cel in cellules]

    assert _sans_champs_identite(monde1["cellules"]) == _sans_champs_identite(monde2["cellules"])


def stockage_spatial_test_cellules(n=2):
    return [{"cellule_id": i, "x": float(i) * 10, "y": float(i) * 5, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]


@respx.mock
def test_genome_croiser_place_enfant_avec_le_tick_courant_du_monde():
    """L'enfant hérite du tick_actuel de l'horloge du monde au moment du
    placement — pas toujours 0 — sinon son âge serait faux dès que le monde a
    déjà avancé (voir horloge.py/horloge_moteur.py, Sprint C)."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice()),
                     httpx.Response(200, json=_portrait_factice()),
                     httpx.Response(200, json=_portrait_factice())])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))
    monde = stockage_spatial.creer_monde("public", stockage_spatial_test_cellules(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.marquer_execution(monde["id"], 5)  # simule un monde déjà au tick 5
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 48.0, "longitude_enfant": 2.0,
        "heure_naissance_enfant": "10:00", "utc_offset_enfant": 1.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    eid = r.json()["enfant_id"]
    cellule_id = r.json()["cellule_id"]
    population = stockage_spatial.population_vivante_cellule(monde["id"], cellule_id)
    assert any(h["id"] == eid and h["ne_au_tick"] == 5 for h in population)


def test_horloge_monde_a_une_horloge_des_sa_creation():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10})
    mid = r.json()["id"]
    etat = client.get(f"/horloge/{mid}").json()
    assert etat == {"monde_id": mid, "tick_actuel": 0, "actif": False,
                     "intervalle_secondes": None, "derniere_execution": None}


def test_horloge_tick_manuel_avance_le_compteur():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    resultat = client.post(f"/horloge/{mid}/tick").json()
    assert resultat["tick_actuel"] == 1
    assert client.get(f"/horloge/{mid}").json()["tick_actuel"] == 1


def test_horloge_tick_monde_introuvable_404():
    r = client.post("/horloge/id-inconnu/tick")
    assert r.status_code == 404


def test_horloge_demarrer_puis_arreter():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    r = client.post(f"/horloge/{mid}/demarrer", json={"intervalle_secondes": 60})
    assert r.status_code == 200
    assert r.json()["actif"] is True
    r = client.post(f"/horloge/{mid}/arreter")
    assert r.json()["actif"] is False


def test_horloge_demarrer_intervalle_hors_bornes_422():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    r = client.post(f"/horloge/{mid}/demarrer", json={"intervalle_secondes": 1})
    assert r.status_code == 422


def test_horloge_fork_reprend_tick_mais_reste_inactif():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    client.post(f"/horloge/{mid}/tick")
    client.post(f"/horloge/{mid}/tick")
    fork_id = client.post(f"/spatial/mondes/{mid}/forker").json()["id"]
    etat_fork = client.get(f"/horloge/{fork_id}").json()
    assert etat_fork["tick_actuel"] == 2
    assert etat_fork["actif"] is False


def test_horloge_supprimer_monde_purge_horloge():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    client.delete(f"/spatial/mondes/{mid}")
    assert client.get(f"/horloge/{mid}").status_code == 404
