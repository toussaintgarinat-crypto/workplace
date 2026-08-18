"""Tests — route PATCH /series/{id}/episodes/{n}/valeur (le parent retient/change la
valeur d'un chapitre)."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_episode():
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_brut": "Texte.", "valeur_suggeree": "courage",
                          "valeur": "courage"}]
    S._save(serie)
    return sid


def test_parent_change_la_valeur():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/1/valeur", json={"valeur": "empathie"})
    assert r.status_code == 200
    assert r.json() == {"valeur": "empathie", "valeur_suggeree": "courage"}
    assert S._load(sid)["episodes"][0]["valeur"] == "empathie"


def test_parent_retire_la_valeur():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/1/valeur", json={"valeur": None})
    assert r.status_code == 200
    assert r.json()["valeur"] is None


def test_valeur_inconnue_400():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/1/valeur", json={"valeur": "pas-une-valeur"})
    assert r.status_code == 400


def test_chapitre_inexistant_404():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/99/valeur", json={"valeur": "courage"})
    assert r.status_code == 404
