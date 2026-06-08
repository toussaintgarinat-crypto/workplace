"""Tests du router Skills (re-porté S137) — CRUD + scope + quirk tags string JSON."""

from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio

import app.routers.skills as skills_mod
from app.auth import UserContext, get_current_user


def _fake_user():
    return UserContext(sub="test-user-123", nom="Bob", avatar_emoji="🦊", org_id=None)


@pytest_asyncio.fixture(autouse=True)
async def _auth(app):
    """Surcharge l'auth pour tous les tests skills."""
    app.dependency_overrides[get_current_user] = _fake_user
    yield
    app.dependency_overrides.clear()


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.added = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _FakeResult(self._rows)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = "generated-id"


def _mk_skill(**kw):
    base = dict(
        id="skill-1", user_id="test-user-123", org_id=None, venture_id=None,
        pole_id=None, nom="N", description="D", tags='["a","b"]', skill_md="# md",
        actif=True, is_global=False, created_at=None, updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_list_skills_tags_raw(client, monkeypatch):
    sk = _mk_skill()
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession(rows=[sk]))
    r = await client.get("/api/skills")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["tags"] == '["a","b"]'  # string brute (quirk Drizzle)
    assert body[0]["global"] is False
    assert body[0]["skillMd"] == "# md"


async def test_list_active(client, monkeypatch):
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession(rows=[_mk_skill(actif=True)]))
    r = await client.get("/api/skills/active?poleId=11111111-1111-1111-1111-111111111111")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_create_skill(client, monkeypatch):
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession())
    r = await client.post("/api/skills", json={"nom": "Compétence", "skillMd": "# md", "tags": ["x"]})
    assert r.status_code == 201
    body = r.json()
    # parité Bun : tags stocké en string JSON, renvoyé tel quel
    assert body["tags"] == '["x"]'
    assert body["nom"] == "Compétence"


async def test_create_skill_validation(client, monkeypatch):
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession())
    # skillMd manquant → 422
    r = await client.post("/api/skills", json={"nom": "X"})
    assert r.status_code == 422


async def test_patch_skill(client, monkeypatch):
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession(rows=[_mk_skill(actif=False)]))
    r = await client.patch("/api/skills/11111111-1111-1111-1111-111111111111", json={"actif": False})
    assert r.status_code == 200
    assert r.json()["actif"] is False


async def test_patch_skill_404(client, monkeypatch):
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession(rows=[]))
    r = await client.patch("/api/skills/11111111-1111-1111-1111-111111111111", json={"nom": "Z"})
    assert r.status_code == 404


async def test_delete_skill(client, monkeypatch):
    monkeypatch.setattr(skills_mod, "SessionLocal", lambda: _FakeSession())
    r = await client.delete("/api/skills/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
