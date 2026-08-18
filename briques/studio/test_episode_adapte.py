"""Tests — route GET /series/{id}/episodes/{n}/adapte (lecture adaptée par profil, S231).

`_adapter_cible` est monkeypatché en spy : ses propres scénarios (succès/repli) sont déjà
couverts par `test_cible_lecture.py`, ici on vérifie le CÂBLAGE (résolution du profil,
isolation, 404) via la route FastAPI."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _serie_avec_episode_direct():
    """Injecte un épisode directement (contourne la co-création de bible, hors périmètre ici)."""
    import studio as S
    sid = client.post("/series", json={"titre": "Adaptable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Il était une fois un dragon.",
                          "script_brut": "Il était une fois un dragon."}]
    S._save(serie)
    return sid


def test_texte_adapte_appelle_adapter_cible_avec_la_cible_du_profil(monkeypatch):
    appels = []

    async def fake_adapter(texte, cible, langue="fr"):
        appels.append((texte, cible))
        return "Texte adapté.", True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)

    sid = _serie_avec_episode_direct()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body == {"texte": "Texte adapté.", "adapte": True, "cible": "7-9", "profil_id": pid}
    assert appels == [("Il était une fois un dragon.", "7-9")]


def test_episode_inexistant_404(monkeypatch):
    async def fake_adapter(texte, cible, langue="fr"):
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)
    sid = _serie_avec_episode_direct()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/episodes/99/adapte", params={"profil_id": pid})
    assert r.status_code == 404


def test_profil_inexistant_404():
    sid = _serie_avec_episode_direct()
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": "inconnu-xyz"})
    assert r.status_code == 404


def test_profil_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    pid = client.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                       headers=entetes_claire).json()["id"]
    sid = client.post("/series", json={"titre": "SérieMarina"},
                      headers=entetes_marina).json()["id"]
    import studio as S
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Texte.", "script_brut": "Texte."}]
    S._save(serie)
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid},
                   headers=entetes_marina)
    assert r.status_code == 404


def test_serie_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    sid = client.post("/series", json={"titre": "SérieClaire"},
                      headers=entetes_claire).json()["id"]
    pid = client.post("/profils", json={"nom": "DeMarina", "cible": "7-9"},
                       headers=entetes_marina).json()["id"]
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid},
                   headers=entetes_marina)
    assert r.status_code == 404
