"""Tests API de world-engine."""
import importlib

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import main
import stockage

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
