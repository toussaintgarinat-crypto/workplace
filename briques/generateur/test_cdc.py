"""Tests S229 : table cahiers_des_charges + endpoints cahier des charges."""
import os
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test-offline")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "test_generateur_cdc.db"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main as gen_main
    monkeypatch.setattr(gen_main, "DB_PATH", str(tmp_path / "apps.db"))
    with TestClient(gen_main.app) as c:
        yield c


def test_table_cahiers_des_charges_existe(client):
    import main as gen_main
    with gen_main._connexion() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cahiers_des_charges)").fetchall()}
    assert cols == {"id", "audit_id", "markdown", "pdf_chemin", "pptx_chemin", "statut", "created_at"}


def test_dernier_cdc_absent_retourne_none(client):
    import main as gen_main
    assert gen_main._dernier_cdc("audit-inexistant") is None
