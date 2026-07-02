"""Tests de gateway_admin — 100 % offline.

On utilise des clients httpx fictifs injectables (motif noeud.py / sonde_fn) pour
valider les trois scénarios : OK, erreur HTTP, LITELLM_URL absente.
Aucun appel réseau réel.
"""
import asyncio
import os

import httpx
import pytest

import gateway_admin


# ── Helpers : faux AsyncClient ────────────────────────────────────────────────

class FakeReponse:
    """Simule httpx.Response sans réseau."""

    def __init__(self, status_code: int, data=None, text: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("pas de JSON dans la fausse réponse")
        return self._data


class FakeClientHTTP:
    """Client httpx faux (POST uniquement) — retourne les réponses dans l'ordre."""

    def __init__(self, *reponses):
        self._iter = iter(reponses)

    async def post(self, url, **kwargs):
        return next(self._iter)

    async def aclose(self):
        pass


class FakeClientReseau:
    """Simule une panne réseau (ConnectError)."""

    async def post(self, url, **kwargs):
        raise httpx.ConnectError("connexion refusée (simulé)")

    async def aclose(self):
        pass


def _lancer(coro):
    return asyncio.run(coro)


# ── Tests enregistrer_modele ──────────────────────────────────────────────────

def test_enregistrer_ok(monkeypatch):
    """Gateway répond 200 avec model_id → ok True, model_id renseigné."""
    monkeypatch.setenv("LITELLM_URL", "http://fake-gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-master-key")
    fake = FakeClientHTTP(FakeReponse(200, {"model_id": "abc-123"}))
    res = _lancer(gateway_admin.enregistrer_modele("ollama/llama3.3", "http://muscle:11434", client=fake))
    assert res["ok"] is True
    assert res["erreur"] is None
    assert res["model_id"] == "abc-123"
    assert res["model_name"] == "ollama/llama3.3"


def test_enregistrer_ok_sans_model_id(monkeypatch):
    """Gateway répond 200 sans model_id dans le corps → ok True, model_id None."""
    monkeypatch.setenv("LITELLM_URL", "http://fake-gw:4000")
    fake = FakeClientHTTP(FakeReponse(200, {"status": "success"}))
    res = _lancer(gateway_admin.enregistrer_modele("ollama/llama3.3", "http://muscle:11434", client=fake))
    assert res["ok"] is True
    assert res["model_id"] is None


def test_enregistrer_erreur_http(monkeypatch):
    """Gateway répond 500 → ok False, erreur contient le code HTTP."""
    monkeypatch.setenv("LITELLM_URL", "http://fake-gw:4000")
    fake = FakeClientHTTP(FakeReponse(500, text="Internal Server Error"))
    res = _lancer(gateway_admin.enregistrer_modele("ollama/llama3.3", "http://muscle:11434", client=fake))
    assert res["ok"] is False
    assert res["erreur"] is not None
    assert "500" in res["erreur"]
    assert res["model_id"] is None


def test_enregistrer_sans_litellm_url(monkeypatch):
    """LITELLM_URL absent → verdict honnête immédiat, sans appel réseau."""
    monkeypatch.delenv("LITELLM_URL", raising=False)
    # Pas de client injecté → ne doit PAS faire de vrai appel réseau
    res = _lancer(gateway_admin.enregistrer_modele("ollama/llama3.3", "http://muscle:11434"))
    assert res["ok"] is False
    assert "LITELLM_URL" in res["erreur"]
    assert res["model_id"] is None


def test_enregistrer_erreur_reseau(monkeypatch):
    """Panne réseau (ConnectError) → ok False, erreur renseignée, pas de levée."""
    monkeypatch.setenv("LITELLM_URL", "http://fake-gw:4000")
    fake = FakeClientReseau()
    res = _lancer(gateway_admin.enregistrer_modele("ollama/llama3.3", "http://muscle:11434", client=fake))
    assert res["ok"] is False
    assert res["erreur"] is not None


# ── Tests retirer_modele ──────────────────────────────────────────────────────

def test_retirer_ok(monkeypatch):
    """Gateway répond 200 → ok True."""
    monkeypatch.setenv("LITELLM_URL", "http://fake-gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-master-key")
    fake = FakeClientHTTP(FakeReponse(200, {}))
    res = _lancer(gateway_admin.retirer_modele("abc-123", client=fake))
    assert res["ok"] is True
    assert res["erreur"] is None


def test_retirer_erreur_http(monkeypatch):
    """Gateway répond 404 → ok False."""
    monkeypatch.setenv("LITELLM_URL", "http://fake-gw:4000")
    fake = FakeClientHTTP(FakeReponse(404, text="Not Found"))
    res = _lancer(gateway_admin.retirer_modele("inexistant", client=fake))
    assert res["ok"] is False
    assert "404" in res["erreur"]


def test_retirer_sans_litellm_url(monkeypatch):
    """LITELLM_URL absent → verdict honnête, sans appel réseau."""
    monkeypatch.delenv("LITELLM_URL", raising=False)
    res = _lancer(gateway_admin.retirer_modele("abc-123"))
    assert res["ok"] is False
    assert "LITELLM_URL" in res["erreur"]
