"""Tests API (TestClient) : endpoints connexion /push/appareils + /push/cle_publique (S178)."""
import os, importlib
from fastapi.testclient import TestClient


def _client(tmp_path):
    os.environ["CONNEXION_DIR"] = str(tmp_path)
    os.environ["API_KEYS"] = "secret"      # active l'enforcement de clé (cle_api lit API_KEYS)
    os.environ["VAPID_PUBLIC_KEY"] = "pub-abc"
    import stockage, appareils, correspondance, main
    for m in (stockage, appareils, correspondance, main):
        importlib.reload(m)
    return TestClient(main.app), correspondance


def test_cle_publique_est_publique(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/push/cle_publique")
    assert r.status_code == 200 and r.json()["cle"] == "pub-abc"


def test_enregistrer_appareil_cree_correspondance(tmp_path):
    c, corr = _client(tmp_path)
    body = {"utilisateur": "marina",
            "appareil": {"endpoint": "https://push/AAA", "keys": {"p256dh": "p", "auth": "a"}}}
    r = c.post("/push/appareils", json=body, headers={"X-API-Key": "secret"})
    assert r.status_code == 200
    assert ("webpush", "https://push/AAA") in corr.cibles_pour("marina")


def test_enregistrer_exige_cle(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/push/appareils", json={"utilisateur": "m", "appareil": {"endpoint": "x"}})
    assert r.status_code in (401, 403)


def test_retirer_appareil(tmp_path):
    c, corr = _client(tmp_path)
    body = {"utilisateur": "marina",
            "appareil": {"endpoint": "https://push/BBB", "keys": {"p256dh": "p", "auth": "a"}}}
    c.post("/push/appareils", json=body, headers={"X-API-Key": "secret"})
    r = c.request("DELETE", "/push/appareils", json={"endpoint": "https://push/BBB"},
                  headers={"X-API-Key": "secret"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert corr.cibles_pour("marina") == []
