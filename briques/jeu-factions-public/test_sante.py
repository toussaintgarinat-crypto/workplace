from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}


def test_docs_api_desactivees_pour_un_service_public():
    """Fix S220 revue finale : service public, pas de docs auto-générées exposées."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
