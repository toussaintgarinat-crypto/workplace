from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_front_combat_sert_le_html():
    r = client.get("/front_combat.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "phaser" in r.text.lower()
