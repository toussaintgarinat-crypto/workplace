"""Auth de la brique Studio : le verrou `cle_api` (X-API-Key).

`cle_api` lit le global `API_KEYS` À L'APPEL → on peut activer l'auth par monkeypatch
sans réimporter le module. Vérifie : mode ouvert (défaut) = accès libre ; auth active =
401 sans clé, 200 avec la bonne clé. (Le repli STUDIO_KEY→API_KEYS est prouvé en LIVE.)
"""

import main as M
from fastapi.testclient import TestClient

client = TestClient(M.app)


def test_mode_ouvert_accepte_sans_cle():
    # conftest pose API_KEYS="" → ensemble vide → mode ouvert.
    assert M.API_KEYS == set()
    r = client.get("/series")
    assert r.status_code == 200


def test_auth_active_refuse_sans_cle(monkeypatch):
    monkeypatch.setattr(M, "API_KEYS", {"clef-de-service"})
    r = client.get("/series")
    assert r.status_code == 401


def test_auth_active_accepte_avec_cle(monkeypatch):
    monkeypatch.setattr(M, "API_KEYS", {"clef-de-service"})
    r = client.get("/series", headers={"X-API-Key": "clef-de-service"})
    assert r.status_code == 200


def test_auth_active_refuse_mauvaise_cle(monkeypatch):
    monkeypatch.setattr(M, "API_KEYS", {"clef-de-service"})
    r = client.get("/series", headers={"X-API-Key": "pas-la-bonne"})
    assert r.status_code == 401
