"""S227 (revue post-fusion whole-branch, wave 2, Fix A) : la même classe de bug
que wave 1 (une requête `OrganizationMembers` qui teste "a une ligne pour cet
org" sans jamais regarder `role`, laissant un membership `client_lecture` agir
comme un membre actif) a été retrouvée à deux sites supplémentaires —
`ventures._resolve_org_id` et `organizations.get_org`/`list_orgs` — puis
corrigée par un helper partagé, `_membre_actif` (auth.py), aussi rebranché sur
`_resolve_org` (déjà fixé en wave 1) pour DRY.

Ce fichier prouve :
(1) le helper compile bien un SQL qui exclut `role = 'client_lecture'` — c'est
    la garantie de fond derrière les tests de comportement ci-dessous, qui eux
    simulent seulement le résultat côté fake session (sans vraie DB) ;
(2) chaque site nouvellement corrigé discrimine correctement : bloque un
    membership client_lecture-only, laisse passer member/admin/owner (pas de
    régression sur les rôles légitimes).
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.auth import UserContext, _membre_actif, get_current_user
from app.models import OrganizationMembers
import app.routers.organizations as orgs_mod
import app.routers.ventures as ventures_mod

ORG_ID = "44444444-4444-4444-4444-444444444444"


def _user(sub):
    def _f():
        return UserContext(sub=sub, nom="Bob", avatar_emoji="🦊", org_id=None)
    return _f


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
    """Même convention que test_dossier_integration_s227.py::_FakeSession : une
    file `rows_by_call` consommée un execute() à la fois. `add`/`flush`/
    `commit`/`refresh` sont des no-ops (create_venture s'en sert pour les pôles
    par défaut, sans passer par execute())."""

    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)

    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = "55555555-5555-5555-5555-555555555555"
        obj.created_at = obj.updated_at = None


def test_membre_actif_exclut_client_lecture_dans_le_sql():
    """Unit test direct sur le helper : la clause WHERE compilée exclut bien
    `role != 'client_lecture'`. Si ce test casse, aucun des sites ci-dessous
    n'est plus protégé — c'est la garantie de fond.

    NB : pas de `literal_binds` ici — la colonne `org_id` est un UUID stocké en
    CHAR(32), et son literal-processor ne sait pas rendre une str brute passée
    au filtre du test (non pertinent pour ce qu'on vérifie : la présence de la
    clause `role != :role_N` et la valeur bindée `client_lecture`)."""
    q = _membre_actif(select(OrganizationMembers).where(OrganizationMembers.user_id == "u"))
    compiled = q.compile()
    assert "role !=" in str(compiled)
    assert "client_lecture" in compiled.params.values()


# ── ventures._resolve_org_id (via POST /api/ventures) ──────────────────────

async def test_resolve_org_id_bloque_client_lecture_via_x_org_id(client, app, monkeypatch):
    """create_venture : un client_lecture qui présente `X-Org-ID: <org du
    consultant>` ne doit PAS voir sa venture stampée avec cet org_id — ce
    serait une écriture dans le scope d'un autre tenant, interdite pour ce
    rôle. Le fake simule ce qu'une vraie DB renverrait après le fix : la query
    filtrée par `_membre_actif` ne trouve aucune ligne pour un membership
    client_lecture-only → repli sur org_id=None (comme un X-Org-ID périmé)."""
    app.dependency_overrides[get_current_user] = _user("client-1")
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.post("/api/ventures", json={"nom": "Client Acme"},
                          headers={"X-Org-ID": ORG_ID})
    app.dependency_overrides.clear()
    assert r.status_code == 201
    assert r.json()["orgId"] is None


async def test_resolve_org_id_honore_membre_actif_via_x_org_id(client, app, monkeypatch):
    """Non-régression : un membership légitime (member/admin/owner) doit
    toujours pouvoir stamper la venture créée avec l'org demandée via
    X-Org-ID."""
    app.dependency_overrides[get_current_user] = _user("user-1")
    membership = SimpleNamespace(org_id=ORG_ID, user_id="user-1", role="member")
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[membership]]))
    r = await client.post("/api/ventures", json={"nom": "Ma Venture"},
                          headers={"X-Org-ID": ORG_ID})
    app.dependency_overrides.clear()
    assert r.status_code == 201
    assert r.json()["orgId"] == ORG_ID


# ── organizations.get_org ───────────────────────────────────────────────────

async def test_get_org_bloque_client_lecture(client, app, monkeypatch):
    """GET /api/orgs/{org_id} : un client_lecture-only ne doit jamais recevoir
    l'org ni le roster de ses membres (fuite email/nom/role — cf. revue). Le
    fake simule le résultat filtré : la query membership ne trouve rien."""
    app.dependency_overrides[get_current_user] = _user("client-1")
    monkeypatch.setattr(orgs_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.get(f"/api/orgs/{ORG_ID}")
    app.dependency_overrides.clear()
    assert r.status_code == 404


async def test_get_org_honore_membre_actif(client, app, monkeypatch):
    """Non-régression : un membership légitime voit toujours son org + roster."""
    app.dependency_overrides[get_current_user] = _user("user-1")
    membership = SimpleNamespace(org_id=ORG_ID, user_id="user-1", role="admin")
    org = SimpleNamespace(id=ORG_ID, nom="Cabinet Conseil", emoji="🏢", slug="cabinet",
                          owner_id="someone-else", plan="team", created_at=None)
    monkeypatch.setattr(orgs_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[membership], [org], []]))
    r = await client.get(f"/api/orgs/{ORG_ID}")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["myRole"] == "admin"
    assert body["nom"] == "Cabinet Conseil"


# ── organizations.list_orgs ─────────────────────────────────────────────────

async def test_list_orgs_exclut_client_lecture(client, app, monkeypatch):
    """GET /api/orgs : un client_lecture-only ne doit voir aucune org listée
    (nom/emoji/slug du cabinet de conseil) — ce rôle reste scopé à une seule
    venture, jamais à la visibilité d'org. Le fake simule la query filtrée
    (aucune ligne)."""
    app.dependency_overrides[get_current_user] = _user("client-1")
    monkeypatch.setattr(orgs_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.get("/api/orgs")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


async def test_list_orgs_inclut_membre_actif(client, app, monkeypatch):
    """Non-régression : un membership légitime (ici owner) apparaît toujours
    dans la liste des orgs de l'appelant."""
    app.dependency_overrides[get_current_user] = _user("user-1")
    org = SimpleNamespace(id=ORG_ID, nom="Ma Boite", emoji="🏢", slug="ma-boite",
                          owner_id="user-1", plan="team", created_at=None)
    monkeypatch.setattr(orgs_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[(org, "owner")]]))
    r = await client.get("/api/orgs")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["role"] == "owner"
    assert body[0]["nom"] == "Ma Boite"
