"""Tests S132 — bouton [🛠️ Améliorer] + suggestions dev_*."""
import os
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

def test_bouton_ameliorer_present_dans_dashboard():
    html = client.get("/dashboard").text
    assert 'id="btn-ameliorer"' in html
    assert "🛠️" in html
    assert "Améliorer" in html

def test_bouton_ameliorer_injecte_le_bon_message():
    html = client.get("/dashboard").text
    assert "Je veux améliorer la solution." in html
    assert "taperAction" in html
