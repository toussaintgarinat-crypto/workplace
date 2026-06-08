"""S129 — module mémoire/RAG : sérialiseurs, chunking, résolution provider, MemPalace."""

import datetime
import types

import pytest

from app import memory
from app.serde import kb_article, memory_entry


# ── Sérialiseurs (parité Drizzle/Bun) ──────────────────────────────────
def test_kb_article_keys_and_tags_string():
    r = types.SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", user_id="u1", org_id=None,
        titre="Doc", contenu="hello", tags='["a","b"]', is_pinned=True, is_public=False,
        created_at=datetime.datetime(2026, 1, 1), updated_at=datetime.datetime(2026, 1, 2),
    )
    out = kb_article(r)
    assert set(out) == {"id", "userId", "orgId", "titre", "contenu", "tags",
                        "isPinned", "isPublic", "createdAt", "updatedAt"}
    assert out["tags"] == '["a","b"]'  # STRING brute, pas parsée
    assert out["isPinned"] is True and out["orgId"] is None


def test_memory_entry_keys():
    r = types.SimpleNamespace(
        id="x", user_id="u", org_id=None, agent_id=None, cle="k", valeur="v",
        type="context", ttl=None, created_at=None, updated_at=None)
    out = memory_entry(r)
    assert set(out) == {"id", "userId", "orgId", "agentId", "cle", "valeur",
                        "type", "ttl", "createdAt", "updatedAt"}
    assert out["type"] == "context" and out["ttl"] is None


# ── Chunking (parité ingestor.ts) ──────────────────────────────────────
def test_chunk_text_overlap_and_filter():
    assert memory.chunk_text("court") == []  # < 20 chars → filtré
    text = "x" * 1200
    chunks = memory.chunk_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= memory.CHUNK_SIZE for c in chunks)
    # overlap : pas (519 + 1) > total ; pas exactement, mais avance de 448 par chunk
    assert chunks[0][-memory.CHUNK_OVERLAP:] == chunks[1][:memory.CHUNK_OVERLAP]


# ── Résolution provider (parité embedder.ts) ───────────────────────────
def test_resolve_provider_falls_back_local(monkeypatch):
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.setattr(f"app.config.settings.{k}", "")
    assert memory.available_providers() == ["local"]
    assert memory.resolve_provider("openai") == "local"  # préféré indispo → local


def test_resolve_provider_prefers_available(monkeypatch):
    monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr("app.config.settings.GEMINI_API_KEY", "")
    monkeypatch.setattr("app.config.settings.MISTRAL_API_KEY", "")
    assert set(memory.available_providers()) == {"local", "openai"}
    assert memory.resolve_provider("openai") == "openai"
    assert memory.resolve_provider(None) == "openai"  # priorité openai > local


def test_collections_dims():
    assert memory.COLLECTIONS["local"]["size"] == 384
    assert memory.COLLECTIONS["openai"]["size"] == 1536
    assert memory.COLLECTIONS["gemini"]["size"] == 768
    assert memory.COLLECTIONS["mistral"]["size"] == 1024


# ── Client brique Mémoire Workplace (contrat /rappeler) ─────────────────
def test_mem_format_context_empty():
    assert memory.mem_format_context([]) == ""


def test_mem_format_context_truncates_and_labels():
    hits = [{"titre": "Note", "extrait": "z" * 600, "type": "ressource"}]
    out = memory.mem_format_context(hits)
    assert "## Mémoires Workplace" in out
    assert "[Note · ressource]" in out
    assert "…" in out  # tronqué à 450


@pytest.mark.asyncio
async def test_mem_prefetch_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "")
    assert await memory.mem_prefetch("hello") == []


@pytest.mark.asyncio
async def test_get_context_degrades_to_empty(monkeypatch):
    # Qdrant injoignable + Mémoire off → "" sans lever
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "")
    monkeypatch.setattr("app.config.settings.QDRANT_URL", "http://127.0.0.1:1")  # port mort
    out = await memory.get_context("question", "sess-1")
    assert out == ""
