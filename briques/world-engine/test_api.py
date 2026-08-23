"""Tests API de world-engine."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_auth_rejette_cle_absente_quand_api_keys_configuree(monkeypatch):
    """Teste directement cle_api() pour vérifier le rejet d'une clé manquante/invalide."""
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    # Clé absente → rejet
    with pytest.raises(main.HTTPException) as exc:
        main.cle_api(x_api_key=None, authorization=None)
    assert exc.value.status_code == 401
    # Clé invalide → rejet
    with pytest.raises(main.HTTPException) as exc:
        main.cle_api(x_api_key="mauvaise-cle", authorization=None)
    assert exc.value.status_code == 401
    # Clé valide → acceptée
    result = main.cle_api(x_api_key="vraie-cle", authorization=None)
    assert result == "vraie-cle"
    # Bearer token valide → acceptée
    result = main.cle_api(x_api_key=None, authorization="Bearer vraie-cle")
    assert result == "vraie-cle"
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)


def test_sante_jamais_protegee_meme_avec_api_keys(monkeypatch):
    """/sante reste accessible sans clé, même si API_KEYS est configurée."""
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    c = TestClient(main.app)
    assert c.get("/sante").status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
