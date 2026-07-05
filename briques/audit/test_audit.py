import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main as audit_main
    monkeypatch.setattr(audit_main, "DB_PATH", str(tmp_path / "audits.db"))
    with TestClient(audit_main.app) as c:
        yield c


def test_sante(client):
    resp = client.get("/sante")
    assert resp.status_code == 200
    assert resp.json()["statut"] == "ok"


def test_lister_audits_vide(client):
    resp = client.get("/audits")
    assert resp.status_code == 200
    assert resp.json() == []


def test_lire_audit_inexistant_retourne_404(client):
    resp = client.get("/audits/audit-inexistant-xyz")
    assert resp.status_code == 404


def test_supprimer_audit_inexistant(client):
    resp = client.delete("/audits/audit-inexistant-xyz")
    assert resp.status_code == 204


def test_importer_et_lire_audit(client):
    resp = client.post("/audits/import", json={
        "nom_entreprise": "Test SA",
        "statut": "termine",
    })
    assert resp.status_code == 200
    audit_id = resp.json()["id"]

    resp2 = client.get(f"/audits/{audit_id}")
    assert resp2.status_code == 200
    assert resp2.json()["nom_entreprise"] == "Test SA"


def test_importer_et_supprimer_audit(client):
    resp = client.post("/audits/import", json={"nom_entreprise": "Suppr SA"})
    audit_id = resp.json()["id"]
    resp2 = client.delete(f"/audits/{audit_id}")
    assert resp2.status_code == 204


def test_auditer_corps_invalide_retourne_422(client):
    resp = client.post("/auditer", json={"mauvais_champ": "x"})
    assert resp.status_code == 422


def test_auditer_corps_vide_retourne_422(client):
    resp = client.post("/auditer", json={})
    assert resp.status_code == 422


def test_auditer_docs_valide_retourne_202(client, monkeypatch):
    import main as audit_main

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr(audit_main, "_lancer_audit", _noop)
    resp = client.post("/auditer", json={"doc_ids": ["doc-1", "doc-2"]})
    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert "statut" in data


def test_auditer_tout_sans_etl_retourne_502(client, monkeypatch):
    import main as audit_main

    async def _raise(*a, **kw):
        raise Exception("ETL inaccessible en test")

    monkeypatch.setattr(audit_main, "_recuperer_tous_ids", _raise)
    resp = client.post("/auditer/tout")
    assert resp.status_code == 502
