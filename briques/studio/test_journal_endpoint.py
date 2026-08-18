"""Tests — route GET /profils/{id}/journal (lecture du journal d'un profil)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_journal_vide_par_defaut():
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/profils/{pid}/journal")
    assert r.status_code == 200
    assert r.json() == {"evenements": []}


def test_profil_inexistant_404():
    r = client.get("/profils/inconnu-xyz/journal")
    assert r.status_code == 404


def test_profil_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    pid = client.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                       headers=entetes_claire).json()["id"]
    r = client.get(f"/profils/{pid}/journal", headers=entetes_marina)
    assert r.status_code == 404
