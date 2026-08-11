"""S227 fix (revue post-fusion whole-branch, Fix 1 — Critical/sécurité) :
`client_lecture` était vérifié par LISTE NOIRE (`role == "member"`) dans
organizations.py, écrite avant que S227 ajoute cette 4e valeur légale de rôle.
Une appartenance `client_lecture` n'était ni "member" ni "owner"/"admin" au sens
strict de la comparaison littérale, donc passait le garde-fou et pouvait
ajouter/promouvoir des membres (add_member) ou retirer n'importe quel autre
membre (remove_member). Corrigé en LISTE BLANCHE (`role not in (owner, admin)`).

Régression prouvée ici sur les deux routes concernées."""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio

from app.auth import UserContext, get_current_user
import app.routers.organizations as orgs_mod

ORG_ID = "33333333-3333-3333-3333-333333333333"


def _client_lecture_user():
    return UserContext(sub="client-1", nom="Client", avatar_emoji="🙂", org_id=None,
                       venture_scopes=frozenset())


@pytest_asyncio.fixture(autouse=True)
async def _auth(app):
    """`client` (fixture conftest.py) est un `httpx.AsyncClient` nu (ASGITransport) —
    pas d'attribut `.app`. Le dependency_overrides se pose sur la fixture `app`
    (l'objet FastAPI), pas sur `client`. Même convention que
    tests/test_client_lecture_s227.py, tests/test_dossier_s227.py."""
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


def _mk_membership(role="client_lecture"):
    return SimpleNamespace(org_id=ORG_ID, user_id="client-1", role=role)


async def test_client_lecture_403_sur_add_member(client, monkeypatch):
    """(a) POST /api/orgs/{org_id}/members — un membre client_lecture ne doit
    jamais pouvoir ajouter/promouvoir un membre (self-promotion à admin
    incluse)."""
    my = _mk_membership()
    monkeypatch.setattr(orgs_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[my]]))
    r = await client.post(f"/api/orgs/{ORG_ID}/members",
                          json={"email": "victime@example.com", "role": "admin"})
    assert r.status_code == 403


async def test_client_lecture_403_sur_remove_member(client, monkeypatch):
    """(b) DELETE /api/orgs/{org_id}/members/{other_user_id} — un membre
    client_lecture ne doit jamais pouvoir retirer un AUTRE membre (se retirer
    soi-même reste permis, cf. remove_member)."""
    my = _mk_membership()
    monkeypatch.setattr(orgs_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[my]]))
    r = await client.delete(f"/api/orgs/{ORG_ID}/members/some-other-user-id")
    assert r.status_code == 403
