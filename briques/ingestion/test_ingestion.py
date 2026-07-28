import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    from main import app
    with TestClient(app) as c:
        yield c


def test_sante(client):
    resp = client.get("/sante")
    assert resp.status_code == 200
    data = resp.json()
    assert data["statut"] == "ok"
    assert "documents_ingeres" in data


def test_lister_documents_vide(client):
    resp = client.get("/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert data["total"] == 0


def test_lister_dossiers(client):
    resp = client.get("/dossiers")
    assert resp.status_code == 200
    data = resp.json()
    assert "projets" in data
    assert "categories" in data


def test_lire_document_inexistant_retourne_404(client):
    resp = client.get("/documents/doc-inexistant-xyz")
    assert resp.status_code == 404


def test_supprimer_document_inexistant_retourne_404(client):
    resp = client.delete("/documents/doc-inexistant-xyz")
    assert resp.status_code == 404


def test_importer_et_lire_document(client):
    resp = client.post("/documents/import", json={
        "nom": "test.txt",
        "source": "test",
        "texte_extrait": "Contenu de test.",
    })
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    resp2 = client.get(f"/documents/{doc_id}")
    assert resp2.status_code == 200
    assert resp2.json()["nom"] == "test.txt"


def test_importer_et_supprimer_document(client):
    resp = client.post("/documents/import", json={"nom": "suppr.txt"})
    doc_id = resp.json()["id"]
    resp2 = client.delete(f"/documents/{doc_id}")
    assert resp2.status_code == 200


def test_classer_document_inexistant_retourne_404(client):
    resp = client.patch(
        "/documents/inconnu-xyz/classement",
        json={"categorie": "test"},
    )
    assert resp.status_code == 404


def test_ingerer_fichier_vide_retourne_400(client):
    resp = client.post(
        "/ingerer",
        files={"fichier": ("vide.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400


def test_ingerer_fichier_texte(client):
    resp = client.post(
        "/ingerer",
        files={"fichier": ("bonjour.txt", b"Bonjour monde !", "text/plain")},
    )
    assert resp.status_code != 500
    if resp.status_code == 200:
        assert "id" in resp.json()


def test_ingerer_url_invalide_retourne_422(client):
    resp = client.post("/ingerer/url", json={"url": "pas-une-url"})
    assert resp.status_code == 422
