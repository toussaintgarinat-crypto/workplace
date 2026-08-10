"""S227 : exposition geoObjectId/auditId/profilEntreprise sur le CRUD ventures."""
from __future__ import annotations

from types import SimpleNamespace

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


def _fake_user():
    return UserContext(sub="user-1", nom="Bob", avatar_emoji="🦊", org_id=None)


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _FakeResult(self._rows)

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _mk_venture(**kw):
    base = dict(
        id="11111111-1111-1111-1111-111111111111", owner_id="user-1", org_id=None,
        nom="Client X", description="", emoji="🚀", couleur="#6366f1", type="audit",
        statut="actif", created_at=None, updated_at=None,
        geo_object_id=None, audit_id=None, profil_entreprise=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_get_venture_expose_les_champs_s227(client, monkeypatch):
    client.app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(geo_object_id="geo-1", audit_id="audit-1",
                     profil_entreprise={"organisation": "SARL"})
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows=[v]))
    r = await client.get(f"/api/ventures/{v.id}")
    client.app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["geoObjectId"] == "geo-1"
    assert body["auditId"] == "audit-1"
    assert body["profilEntreprise"] == {"organisation": "SARL"}


async def test_patch_venture_accepte_les_champs_s227(client, monkeypatch):
    client.app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(geo_object_id="geo-9", audit_id="audit-9",
                     profil_entreprise={"activites": ["conseil"]})
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows=[v]))
    r = await client.patch(f"/api/ventures/{v.id}", json={
        "geoObjectId": "geo-9", "auditId": "audit-9",
        "profilEntreprise": {"activites": ["conseil"]},
    })
    client.app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["geoObjectId"] == "geo-9"
    assert body["profilEntreprise"] == {"activites": ["conseil"]}
