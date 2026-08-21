"""Validation du streaming token-par-token (S60) — `llm_pipeline.completer_flux`.

Autonome : aucune vraie Gateway. On simule le flux SSE OpenAI via httpx.MockTransport.
    $ cd core && python3 test_streaming.py
"""
import asyncio
import json
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["USAGE_LLM_PATH"] = os.path.join(_tmp, "usage.jsonl")
os.environ["LLM_CACHE_PATH"] = os.path.join(_tmp, "cache.jsonl")
os.environ["SHADOW_RUNS_PATH"] = os.path.join(_tmp, "shadow.jsonl")
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(_tmp, "modele.jsonl")
os.environ.setdefault("LLM_BUDGET_MOIS_USD", "0")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import journal_usage  # noqa: E402
import llm_pipeline  # noqa: E402
import journal_modele  # noqa: E402


def _sse(*chunks) -> bytes:
    """Construit un corps SSE façon OpenAI : une ligne `data:` par chunk + [DONE]."""
    corps = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    return corps.encode()


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _collecter(gen):
    return [evt async for evt in gen]


# ── Texte streamé ─────────────────────────────────────────────────────────────
def test_flux_texte():
    def h(req):
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "Bon"}}]},
            {"choices": [{"delta": {"content": "jour"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"usage": {"prompt_tokens": 5, "completion_tokens": 2}, "choices": []},
        ))

    async def go():
        async with _client(h) as c:
            return await _collecter(llm_pipeline.completer_flux(
                [{"role": "user", "content": "salut"}], modeles=["free/x"], client=c))
    evts = asyncio.run(go())
    deltas = [e["contenu"] for e in evts if e["type"] == "delta"]
    assert deltas == ["Bon", "jour"], deltas
    fin = [e for e in evts if e["type"] == "fin"][0]
    assert fin["message"]["content"] == "Bonjour"
    assert fin["resultat"].modele_utilise == "free/x"
    assert fin["resultat"].tokens_out == 2


def test_flux_journalise_dans_journal_modele():
    def h(req):
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "Bon"}}]},
            {"choices": [{"delta": {"content": "jour"}}]},
        ))

    async def go():
        async with _client(h) as c:
            return await _collecter(llm_pipeline.completer_flux(
                [{"role": "system", "content": "sys"}, {"role": "user", "content": "salut"}],
                modeles=["free/x"], etiquette="chat", fil="fil-test-streaming", client=c))
    asyncio.run(go())
    appels = journal_modele.appels("fil-test-streaming")
    assert len(appels) == 1
    assert appels[0]["modele"] == "free/x"
    assert appels[0]["message_recu"]["content"] == "Bonjour"


def test_flux_erreur_journalisee_dans_journal_modele():
    ancien = journal_usage.peut_appeler_payant
    journal_usage.peut_appeler_payant = lambda: False
    try:
        def h(req):
            raise AssertionError("aucun appel réseau ne doit partir si le budget bloque")

        async def go():
            async with _client(h) as c:
                return await _collecter(llm_pipeline.completer_flux(
                    [{"role": "user", "content": "x"}], modeles=["openai/gpt-4o"],
                    etiquette="chat", fil="fil-erreur-streaming", client=c))
        asyncio.run(go())
    finally:
        journal_usage.peut_appeler_payant = ancien
    appels = journal_modele.appels("fil-erreur-streaming")
    assert len(appels) == 1
    assert appels[0]["modele"] is None
    assert "Budget" in appels[0]["erreur"]


# ── tool_calls réassemblés depuis les fragments ───────────────────────────────
def test_flux_tool_call():
    def h(req):
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {"name": "liste_entreprises", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "{\"statut\""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": ":\"livre\"}"}}]}}]},
        ))

    async def go():
        async with _client(h) as c:
            return await _collecter(llm_pipeline.completer_flux(
                [{"role": "user", "content": "où en sont les entreprises ?"}],
                modeles=["free/x"], tools=[{"type": "function", "function": {"name": "liste_entreprises"}}],
                client=c))
    evts = asyncio.run(go())
    assert not [e for e in evts if e["type"] == "delta"]        # aucun texte, que des outils
    msg = [e for e in evts if e["type"] == "fin"][0]["message"]
    tc = msg["tool_calls"][0]
    assert tc["function"]["name"] == "liste_entreprises"
    assert tc["function"]["arguments"] == '{"statut":"livre"}'
    assert tc["id"] == "call_1"


# ── Bascule de modèle AVANT le 1er token (honnête) ────────────────────────────
def test_flux_fallback_avant_token():
    def h(req):
        modele = json.loads(req.content)["model"]
        if modele == "openai/ko":
            return httpx.Response(503, content=b"indispo")
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "ok"}}]}))

    async def go():
        async with _client(h) as c:
            return await _collecter(llm_pipeline.completer_flux(
                [{"role": "user", "content": "x"}], modeles=["openai/ko", "free/ok"], client=c))
    evts = asyncio.run(go())
    assert [e["contenu"] for e in evts if e["type"] == "delta"] == ["ok"]
    fin = [e for e in evts if e["type"] == "fin"][0]
    assert fin["resultat"].modele_utilise == "free/ok"
    assert fin["resultat"].modeles_essayes == ["openai/ko", "free/ok"]


# ── Garde-fou budget : payant bloqué, aucun gratuit → erreur honnête ──────────
def test_flux_budget_bloque():
    ancien = journal_usage.peut_appeler_payant
    journal_usage.peut_appeler_payant = lambda: False          # plafond atteint
    try:
        def h(req):
            raise AssertionError("aucun appel réseau ne doit partir si le budget bloque")

        async def go():
            async with _client(h) as c:
                return await _collecter(llm_pipeline.completer_flux(
                    [{"role": "user", "content": "x"}], modeles=["openai/gpt-4o"], client=c))
        evts = asyncio.run(go())
        assert len(evts) == 1 and evts[0]["type"] == "erreur"
        assert "Budget" in evts[0]["erreur"]
    finally:
        journal_usage.peut_appeler_payant = ancien


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
