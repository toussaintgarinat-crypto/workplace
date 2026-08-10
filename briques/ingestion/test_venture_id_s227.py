"""S227 : colonne indexée venture_id sur documents (coexiste avec l'ancienne clé
JSON metadonnees.classement.entreprise_id — aucune migration destructive)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    from main import app
    with TestClient(app) as c:
        yield c


def test_documents_a_la_colonne_venture_id(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "colonnes.db")
    stockage.initialiser()
    with stockage._conn() as con:
        colonnes = {row["name"] for row in con.execute("PRAGMA table_info(documents)").fetchall()}
    assert "venture_id" in colonnes


def test_ingerer_avec_venture_id_puis_filtrer(client):
    resp = client.post(
        "/ingerer",
        files={"fichier": ("bonjour.txt", b"Bonjour monde !", "text/plain")},
        data={"venture_id": "venture-42"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    autre = client.post(
        "/ingerer",
        files={"fichier": ("autre.txt", b"Autre contenu.", "text/plain")},
    )
    assert autre.status_code == 200

    resp2 = client.get("/documents?venture_id=venture-42")
    assert resp2.status_code == 200
    docs = resp2.json()["documents"]
    assert [d["id"] for d in docs] == [doc_id]


def test_document_sans_venture_id_reste_lisible(client):
    resp = client.post(
        "/documents/import",
        json={"nom": "ancien.txt", "source": "test", "texte_extrait": "x"},
    )
    doc_id = resp.json()["id"]
    resp2 = client.get(f"/documents/{doc_id}")
    assert resp2.status_code == 200
    assert resp2.json()["nom"] == "ancien.txt"
