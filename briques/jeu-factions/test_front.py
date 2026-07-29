from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_accueil_sert_le_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
