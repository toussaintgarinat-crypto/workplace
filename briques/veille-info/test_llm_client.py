"""Tests du client LLM Gateway-aware (copie adaptée de briques/synopsis/lib/llm_client.py —
même motif, brique indépendante). Aucun réseau réel."""
import os

import pytest

from lib import llm_client


def test_leve_si_aucun_fournisseur_configure(monkeypatch):
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Aucun fournisseur"):
        llm_client.llm_complete("bonjour")


def test_appel_gateway_ok(monkeypatch):
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.local:4001")
    monkeypatch.setenv("GATEWAY_KEY", "test-key")

    captured = {}

    class _Rep:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "Résumé généré."}}]}

    def _post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Rep()

    monkeypatch.setattr(llm_client.httpx, "post", _post)
    resultat = llm_client.llm_complete("Résume ceci.", system="Tu es concis.")
    assert resultat == "Résumé généré."
    assert captured["url"] == "http://gateway.local:4001/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "Tu es concis."}
    assert captured["json"]["messages"][1] == {"role": "user", "content": "Résume ceci."}


def test_appel_gateway_erreur_http_leve_apres_retries(monkeypatch):
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.local:4001")
    monkeypatch.setenv("GATEWAY_KEY", "test-key")

    class _Rep:
        status_code = 500
        text = "erreur serveur"

    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _Rep())
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)
    with pytest.raises(RuntimeError, match="LLM call failed"):
        llm_client.llm_complete("bonjour")
