"""Tests — route POST /series/{id}/episodes/{n}/marquer-lu (journal, chapitre écouté).

Vérifie aussi que la prévisualisation parent existante (GET .../adapte) ne journalise
JAMAIS — c'est le défaut de conception corrigé pendant l'auto-revue de la spec (2.2)."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_episode():
    sid = client.post("/series", json={"titre": "Adaptable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_brut": "Il était une fois un dragon."}]
    S._save(serie)
    return sid


def test_marquer_lu_journalise_un_evenement():
    sid = _serie_avec_episode()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/episodes/1/marquer-lu", json={"profil_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "chapitre_lu"
    assert body["serie_id"] == sid
    assert body["episode_n"] == 1
    assert S._load_journal(pid) == [body]


def test_episode_inexistant_404():
    sid = _serie_avec_episode()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/episodes/99/marquer-lu", json={"profil_id": pid})
    assert r.status_code == 404


def test_profil_inexistant_404():
    sid = _serie_avec_episode()
    r = client.post(f"/series/{sid}/episodes/1/marquer-lu", json={"profil_id": "inconnu-xyz"})
    assert r.status_code == 404


def test_preview_get_adapte_ne_journalise_rien(monkeypatch):
    async def fake_adapter(texte, cible, langue="fr"):
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)
    sid = _serie_avec_episode()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid})
    assert S._load_journal(pid) == []
