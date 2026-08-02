from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_accueil_sert_le_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_css_servi():
    r = client.get("/style.css")
    assert r.status_code == 200


def test_front_contient_les_formulaires_auth():
    r = client.get("/")
    assert "formConnexion" in r.text
    assert "formInscription" in r.text


def test_front_ne_reference_pas_le_coeur():
    r = client.get("/")
    assert "tableau de bord du Cœur" not in r.text
    assert "localStorage" not in r.text
