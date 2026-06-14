"""S129 — module mémoire/RAG : sérialiseurs, chunking, résolution provider, MemPalace.

MemPalace = désormais un proxy vers la brique Mémoire Workplace (port 5600). La
table clé/valeur ``memory_entries`` et son sérialiseur ``memory_entry`` ont été
retirés ; le router ``memory_palace`` est réécrit en proxy par-org → cf. les tests
``test_mp_*`` en fin de fichier (espace forge-org-<id>, mapping wing→type)."""

import datetime
import types

import httpx
import pytest

from app import memory
from app.routers import memory_palace as mp
from app.serde import kb_article


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


# ── MemPalace = proxy vers la brique Mémoire (port 5600) ────────────────
def test_mp_espace_par_org():
    # Isolation S18 : un espace mémoire dédié par org ; repli solution sinon.
    assert mp._espace("org-42") == "forge-org-org-42"
    assert mp._espace(None) in ("Workplace", "")  # MEMOIRE_ESPACE par défaut vide → "Workplace"


@pytest.mark.asyncio
async def test_mp_brique_503_si_non_configuree(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "")
    with pytest.raises(HTTPException) as e:
        await mp._brique("GET", "/taxonomy")
    assert e.value.status_code == 503


@pytest.mark.asyncio
async def test_mp_taxonomy_reshape(monkeypatch):
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "http://memoire:5600")

    async def fake(method, path, **kw):
        assert method == "GET" and path == "/taxonomy"
        assert kw["params"]["espace"] == "forge-org-o1"
        return {"total": 5, "par_type": {"input": 3, "projet": 2}, "par_stage": {}}

    monkeypatch.setattr(mp, "_brique", fake)
    out = await mp.taxonomy(user=types.SimpleNamespace(sub="u1"), org_id="o1")
    assert out == {"total": 5, "wings": {"input": 3, "projet": 2}}


@pytest.mark.asyncio
async def test_mp_create_mappe_wing_vers_type(monkeypatch):
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "http://memoire:5600")
    capté = {}

    async def fake(method, path, **kw):
        capté["method"], capté["path"], capté["json"] = method, path, kw.get("json")
        return {"retenu": True, "id": "n1"}

    monkeypatch.setattr(mp, "_brique", fake)
    body = mp.NouveauSouvenir(contenu="idée", wing="projet", room="r1")
    out = await mp.create_memory(body=body, user=types.SimpleNamespace(sub="u1"), org_id="o1")
    assert out["retenu"] is True
    assert capté["method"] == "POST" and capté["path"] == "/retenir"
    j = capté["json"]
    assert j["type"] == "projet" and j["wing"] == "projet" and j["room"] == "r1"
    assert j["metadata"]["user_id"] == "u1"
    assert j["espace"] == "forge-org-o1"


@pytest.mark.asyncio
async def test_mp_create_wing_invalide_retombe_input(monkeypatch):
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "http://memoire:5600")
    capté = {}

    async def fake(method, path, **kw):
        capté["json"] = kw.get("json")
        return {"retenu": True}

    monkeypatch.setattr(mp, "_brique", fake)
    body = mp.NouveauSouvenir(contenu="x", wing="n_importe_quoi")
    await mp.create_memory(body=body, user=types.SimpleNamespace(sub="u1"), org_id="o1")
    assert capté["json"]["type"] == "input"


@pytest.mark.asyncio
async def test_mp_search_emballe_results(monkeypatch):
    monkeypatch.setattr("app.config.settings.MEMOIRE_URL", "http://memoire:5600")

    async def fake(method, path, **kw):
        assert path == "/rappeler" and kw["params"]["q"] == "voix"
        return {"souvenirs": [{"id": "a", "titre": "Aria", "score": 0.9}]}

    monkeypatch.setattr(mp, "_brique", fake)
    out = await mp.search_memory(q="voix", user=types.SimpleNamespace(sub="u1"), org_id="o1")
    assert out == {"results": [{"id": "a", "titre": "Aria", "score": 0.9}]}
