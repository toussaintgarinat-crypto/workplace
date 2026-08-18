"""Tests — route POST /series/{id}/arbre/{noeud_id}/choisir (l'enfant choisit une
branche). Refuse toujours une branche non écrite (404) — jamais de génération en direct."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_arbre():
    sid = client.post("/series", json={"titre": "Aventure"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [
        {"n": 1, "script_brut": "Le début.", "audios": {}},
        {"n": 2, "script_brut": "Dans la grotte.", "audios": {}},
    ]
    serie["arbre"] = {
        "id": "n1", "niveau": 1, "synopsis": "Ouverture", "choix": ["Grotte", "Village"],
        "episode_n": 1, "script": "Le début.",
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


def test_choisir_branche_ecrite_journalise_et_avance():
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir", json={"profil_id": pid, "choix": "Grotte"})
    assert r.status_code == 200
    assert r.json() == {"noeud_id": "n2"}
    evenements = S._load_journal(pid)
    assert len(evenements) == 1
    assert evenements[0]["type"] == "arbre_choix"
    assert evenements[0]["noeud_id"] == "n2"
    assert evenements[0]["choix"] == "Grotte"
    assert evenements[0]["episode_n"] == 2


def test_choisir_branche_non_ecrite_404_et_ne_journalise_rien():
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir", json={"profil_id": pid, "choix": "Village"})
    assert r.status_code == 404
    assert S._load_journal(pid) == []


def test_choix_inconnu_404():
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir",
                    json={"profil_id": pid, "choix": "N'existe pas"})
    assert r.status_code == 404


def test_profil_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_a = {"X-API-Key": "cle-coeur", "X-User-Id": "a-choisir"}
    entetes_b = {"X-API-Key": "cle-coeur", "X-User-Id": "b-choisir"}
    sid = client.post("/series", json={"titre": "T"}, headers=entetes_a).json()["id"]
    serie = S._load(sid)
    serie["arbre"] = {"id": "n1", "niveau": 1, "synopsis": "S", "choix": ["A"],
                      "script": "x", "enfants": [{"choix": "A",
                      "noeud": {"id": "n2", "niveau": 2, "synopsis": "S2", "choix": [],
                                "enfants": [], "script": "y"}}]}
    S._save(serie)
    pid = client.post("/profils", json={"nom": "DeB", "cible": "7-9"},
                      headers=entetes_b).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir", json={"profil_id": pid, "choix": "A"},
                    headers=entetes_a)
    assert r.status_code == 404
