"""Tests — route GET /series/{id}/arbre/{noeud_id}/lire (mode enfant, lecture seule).

`_adapter_cible` est monkeypatché en spy (motif `test_episode_adapte.py`)."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_arbre():
    sid = client.post("/series", json={"titre": "Aventure"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [
        {"n": 1, "script_brut": "Le début de l'aventure.", "audios": {}},
        {"n": 2, "script_brut": "Dans la grotte.", "audios": {}},
    ]
    serie["arbre"] = {
        "id": "n1", "niveau": 1, "synopsis": "Ouverture", "choix": ["Grotte", "Village"],
        "episode_n": 1, "script": "Le début de l'aventure.",
        "enfants": [
            {"choix": "Grotte", "noeud": {"id": "n2", "niveau": 2, "synopsis": "Grotte",
                                          "choix": [], "enfants": [], "episode_n": 2,
                                          "script": "Dans la grotte."}},
            {"choix": "Village", "noeud": {"id": "n3", "niveau": 2, "synopsis": "Village",
                                           "choix": [], "enfants": []}},  # pas encore écrit
        ],
    }
    S._save(serie)
    return sid


def _mock_adapter(monkeypatch):
    async def fake_adapter(texte, cible, langue="fr"):
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)


def test_lire_noeud_indique_quelles_branches_sont_ecrites(monkeypatch):
    appels = []

    async def fake_adapter(texte, cible, langue="fr"):
        appels.append((texte, cible))
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)

    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n1/lire", params={"profil_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["texte"] == "Le début de l'aventure."
    assert body["episode_n"] == 1
    choix = {c["texte"]: c["ecrit"] for c in body["choix"]}
    assert choix == {"Grotte": True, "Village": False}
    assert appels == [("Le début de l'aventure.", "7-9")]


def test_lire_noeud_non_ecrit_404(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n3/lire", params={"profil_id": pid})
    assert r.status_code == 404


def test_lire_noeud_inexistant_404(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n-fantome/lire", params={"profil_id": pid})
    assert r.status_code == 404


def test_serie_sans_arbre_404(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = client.post("/series", json={"titre": "Sans arbre"}).json()["id"]
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n1/lire", params={"profil_id": pid})
    assert r.status_code == 404
