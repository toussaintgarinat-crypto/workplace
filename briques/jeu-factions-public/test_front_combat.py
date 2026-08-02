from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_front_combat_sert_le_html():
    r = client.get("/front_combat.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "phaser" in r.text.lower()


def test_front_combat_ne_contient_plus_de_cle_api():
    r = client.get("/front_combat.html")
    assert "localStorage" not in r.text
    assert "api_key=" not in r.text
