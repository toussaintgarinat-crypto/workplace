"""S181 — endpoint /admin/inviter-proche : appelle NetBird (mocké) et renvoie un QR SVG."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import main  # noqa: E402
import netbird  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_inviter_proche_renvoie_qr(monkeypatch):
    async def faux(nom, **kw):
        return {"key": "KKKK-LLLL", "expires": "2026-07-19T00:00:00Z", "name": nom}
    monkeypatch.setattr(netbird, "creer_setup_key", faux)

    r = client.post("/admin/inviter-proche", json={"nom": "marina"})
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == "KKKK-LLLL"
    assert "<svg" in data["qr_svg"]


def test_inviter_proche_erreur_netbird(monkeypatch):
    async def faux(nom, **kw):
        raise netbird.NetbirdError("token invalid")
    monkeypatch.setattr(netbird, "creer_setup_key", faux)

    r = client.post("/admin/inviter-proche", json={"nom": "x"})
    assert r.status_code == 502
    assert "erreur" in r.json()
