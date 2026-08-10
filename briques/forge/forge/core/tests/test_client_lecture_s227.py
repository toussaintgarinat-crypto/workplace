"""S227 : rôle client_lecture — accès en lecture seule scopé à SA venture."""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


def _client_lecture_user():
    return UserContext(sub="client-1", nom="Client", avatar_emoji="🙂", org_id=None,
                       venture_scopes=frozenset({"11111111-1111-1111-1111-111111111111"}))


@pytest_asyncio.fixture(autouse=True)
async def _auth(app):
    """Surcharge l'auth pour tous les tests client_lecture S227.

    NB : `client` (fixture conftest.py) est un `httpx.AsyncClient` nu (via
    `ASGITransport`) — il n'a pas d'attribut `.app`. Le `dependency_overrides`
    se pose sur la fixture `app` (l'objet FastAPI lui-même), pas sur `client`.
    Même convention que `tests/test_ventures_s227.py` et `tests/test_skills.py`.
    """
    app.dependency_overrides[get_current_user] = _client_lecture_user
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
    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)


def _mk_venture(vid, owner="someone-else"):
    return SimpleNamespace(id=vid, owner_id=owner, geo_object_id=None,
                           audit_id=None, profil_entreprise=None)


async def test_client_lecture_accede_a_sa_venture(client, monkeypatch):
    vid = "11111111-1111-1111-1111-111111111111"
    v = _mk_venture(vid)
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [], []]))
    r = await client.get(f"/api/ventures/{vid}/dossier")
    assert r.status_code == 200


async def test_client_lecture_403_sur_autre_venture(client, monkeypatch):
    autre_vid = "22222222-2222-2222-2222-222222222222"
    v = _mk_venture(autre_vid)
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [], []]))
    r = await client.get(f"/api/ventures/{autre_vid}/dossier")
    assert r.status_code == 403
