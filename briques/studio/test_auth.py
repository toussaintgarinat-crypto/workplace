"""Auth de la brique Studio : le verrou `cle_api` (X-API-Key).

`cle_api` lit le global `API_KEYS` À L'APPEL → on peut activer l'auth par monkeypatch
sans réimporter le module. Vérifie : mode ouvert (défaut) = accès libre ; auth active =
401 sans clé, 200 avec la bonne clé. `STUDIO_KEY` a son propre dialecte par personne
(S187, cf. test_dialecte_studio_key_*), distinct du dialecte BYO ci-dessous.
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


def test_dialecte_studio_key_utilise_x_user_id(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    r = client.post("/series", json={"titre": "Test"},
                    headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json()["cree_par"] == "claire"


def test_dialecte_studio_key_replie_sur_perso_sans_x_user_id(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    r = client.post("/series", json={"titre": "Test"}, headers={"X-API-Key": "cle-coeur"})
    assert r.status_code == 200
    assert r.json()["cree_par"] == "perso"


def test_dialecte_byo_inchange_avec_studio_key_configuree(monkeypatch):
    # Une clé BYO (API_KEYS, PAS STUDIO_KEY) garde le motif historique : identité = la clé.
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    monkeypatch.setattr(M, "API_KEYS", {"cle-coeur", "clef-client-byo"})
    r = client.post("/series", json={"titre": "Test"},
                    headers={"X-API-Key": "clef-client-byo", "X-User-Id": "claire"})
    assert r.status_code == 200
    # X-User-Id est IGNORÉ pour une clé BYO — ce n'est pas le Cœur qui appelle.
    assert r.json()["cree_par"] == "clef-client-byo"
