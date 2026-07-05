"""Tests du cache sémantique des réponses LLM (S138, chantier 2).

    $ cd core && python3 -m pytest test_cache_semantique.py -v
"""
import asyncio
import os
import sys
import time
from pathlib import Path
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import httpx
import cache_semantique as cs


# ── Helpers ──────────────────────────────────────────────────────────────────

MSG_SIMPLE = [{"role": "user", "content": "Bonjour le monde"}]
MSG_AUTRE  = [{"role": "user", "content": "Salut tout le monde"}]
MSG_DIFF   = [{"role": "user", "content": "Parle-moi des volcans d'Islande"}]

MSG_RESP   = {"role": "assistant", "content": "Bonjour !"}

VEC_A = [1.0, 0.0, 0.0]
VEC_B = [1.0, 0.0, 0.0]
VEC_C = [0.0, 1.0, 0.0]

_CLIENT_FACTICE = None  # jamais appelé dans les tests synchrones


@pytest.fixture(autouse=True)
def cache_tmp(tmp_path, monkeypatch):
    """Redirige le cache vers un fichier temporaire pour chaque test."""
    p = tmp_path / "llm_cache.jsonl"
    monkeypatch.setattr(cs, "CACHE_PATH", p)
    monkeypatch.setattr(cs, "ACTIF", True)
    monkeypatch.setattr(cs, "TTL_S", 3600)
    monkeypatch.setattr(cs, "MAX_ENTREES", 100)
    monkeypatch.setattr(cs, "SEUIL", 0.97)
    yield p


# ── Tests synchrones ─────────────────────────────────────────────────────────

def test_1_cosine_vecteurs_identiques():
    """Cosinus de deux vecteurs identiques = 1.0."""
    assert abs(cs._cosine(VEC_A, VEC_B) - 1.0) < 1e-6


def test_2_cosine_vecteurs_orthogonaux():
    """Cosinus de deux vecteurs orthogonaux = 0.0."""
    assert abs(cs._cosine(VEC_A, VEC_C)) < 1e-6


def test_3_cosine_longueurs_differentes():
    """Cosinus renvoie -1.0 si les vecteurs ont des longueurs différentes."""
    assert cs._cosine([1.0], [1.0, 0.0]) == -1.0


def test_4_texte_prompt_concat():
    """_texte_prompt concatène role: content pour chaque message texte."""
    msgs = [
        {"role": "system", "content": "Tu es un assistant."},
        {"role": "user", "content": "Bonjour"},
    ]
    result = cs._texte_prompt(msgs)
    assert "system: Tu es un assistant." in result
    assert "user: Bonjour" in result


def test_5_texte_prompt_ignore_contenu_non_str():
    """_texte_prompt ignore les messages sans contenu string."""
    msgs = [{"role": "user", "content": None}, {"role": "user", "content": "ok"}]
    result = cs._texte_prompt(msgs)
    assert "ok" in result
    assert "None" not in result


def test_6_scope_hash_deterministe():
    """scope_hash est déterministe pour le même triplet."""
    h1 = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    h2 = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    assert h1 == h2


def test_7_scope_hash_modele_different():
    """scope_hash change si le modèle change."""
    h1 = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    h2 = cs.scope_hash(MSG_SIMPLE, "claude-3", [])
    assert h1 != h2


def test_8_scope_hash_systeme_different():
    """scope_hash change si le prompt système change."""
    msgs_sys_a = [{"role": "system", "content": "Tu es A."}, {"role": "user", "content": "ok"}]
    msgs_sys_b = [{"role": "system", "content": "Tu es B."}, {"role": "user", "content": "ok"}]
    assert cs.scope_hash(msgs_sys_a, "m", []) != cs.scope_hash(msgs_sys_b, "m", [])


# ── Tests asynchrones (mock embedding) ───────────────────────────────────────

class _FakeClient:
    """Client httpx factice : renvoie un embedding fixe ou simule une erreur."""

    def __init__(self, vec=None, status=200):
        self._vec = vec
        self._status = status

    async def post(self, url, **kwargs):
        if self._status >= 400:
            return _FakeResponse(self._status, {})
        data = [{"embedding": self._vec or VEC_A, "index": 0}]
        return _FakeResponse(200, {"data": data})


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    @property
    def headers(self):
        return {}


def run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_9_chercher_miss_fichier_vide(cache_tmp, monkeypatch):
    """chercher retourne None si le cache est vide."""
    client = _FakeClient(VEC_A)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    result = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert result is None


def test_10_stocker_puis_chercher_hit(cache_tmp, monkeypatch):
    """stocker puis chercher avec le même vecteur → hit (sim=1.0 ≥ seuil 0.97)."""
    client = _FakeClient(VEC_A)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    run(cs.stocker(client, MSG_SIMPLE, scope, MSG_RESP, "m"))
    hit = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert hit is not None
    assert hit["message"] == MSG_RESP


def test_11_scope_mismatch_miss(cache_tmp, monkeypatch):
    """chercher retourne None si le scope est différent."""
    client = _FakeClient(VEC_A)
    scope_a = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    scope_b = cs.scope_hash(MSG_SIMPLE, "claude-3", [])
    run(cs.stocker(client, MSG_SIMPLE, scope_a, MSG_RESP, "gpt-4o"))
    hit = run(cs.chercher(client, MSG_SIMPLE, scope_b))
    assert hit is None


def test_12_ttl_expire_miss(cache_tmp, monkeypatch):
    """Une entrée expirée (ts très ancien) n'est pas renvoyée."""
    import json
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    entree = {
        "ts": time.time() - 99999,  # très ancien
        "scope": scope,
        "modele": "m",
        "prompt_norm": "user: Bonjour le monde",
        "message": MSG_RESP,
        "embedding": VEC_A,
    }
    cache_tmp.write_text(json.dumps(entree) + "\n", encoding="utf-8")
    client = _FakeClient(VEC_A)
    hit = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert hit is None


def test_13_gateway_ko_chercher_retourne_none(cache_tmp, monkeypatch):
    """Si la Gateway renvoie 500, chercher retourne None sans lever."""
    client = _FakeClient(status=500)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    result = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert result is None


def test_14_actif_false_chercher_retourne_none(cache_tmp, monkeypatch):
    """Si ACTIF est False, chercher retourne None immédiatement."""
    monkeypatch.setattr(cs, "ACTIF", False)
    client = _FakeClient(VEC_A)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    result = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert result is None
