"""S227 : bout-en-bout (mock réseau) — création venture, liaison geo/audit,
document ingéré, lecture du dossier agrégé. Motif : test réel, réseau mocké,
jamais simulé silencieusement (cf. audit/test_audit.py, forge/test_crm_import_lot.py)."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest_asyncio

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


def _fake_user():
    return UserContext(sub="user-1", nom="Bob", avatar_emoji="🦊", org_id=None)


@pytest_asyncio.fixture(autouse=True)
async def _auth(app):
    """`client` (fixture conftest.py) est un `httpx.AsyncClient` nu (ASGITransport) —
    pas d'attribut `.app`. Le dependency_overrides se pose sur la fixture `app`
    (l'objet FastAPI), pas sur `client`. Même convention que
    tests/test_skills.py, tests/test_ventures_s227.py, tests/test_dossier_s227.py,
    tests/test_client_lecture_s227.py."""
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
    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = "11111111-1111-1111-1111-111111111111"
        obj.created_at = obj.updated_at = None


class _FakeSessionPatch:
    """Session pour PATCH venture : DEUX execute() consécutifs (update puis select) —
    `update_venture` (app/routers/ventures.py) exécute d'abord l'UPDATE (résultat
    jeté), puis un SELECT dont le résultat devient le corps de la réponse. Une
    file `rows_by_call` à pop() inconditionnel se ferait consommer par l'UPDATE
    et laisserait le SELECT vide → réponse `None`, un faux vert qui n'aurait
    jamais prouvé la liaison geo/audit. Même pattern que
    `tests/test_ventures_s227.py::_FakeSessionPatch`."""

    def __init__(self, rows=None):
        self._rows = rows or []
        self._execute_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        # 1er execute (UPDATE) : résultat ignoré côté handler → vide.
        # 2e execute (SELECT) : renvoie la venture, devient venture(v) dans la réponse.
        result_rows = [] if self._execute_count == 0 else self._rows
        self._execute_count += 1
        return _FakeResult(result_rows)

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


async def test_venture_creee_puis_dossier_agrege_bout_en_bout(client, monkeypatch):
    monkeypatch.setattr(ventures_mod.settings, "GEO_URL", "http://geo.test")
    monkeypatch.setattr(ventures_mod.settings, "AUDIT_URL", "http://audit.test")
    monkeypatch.setattr(ventures_mod.settings, "INGESTION_URL", "http://ingestion.test")

    # 1. Création de la venture (type='audit').
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[]))
    creation = await client.post("/api/ventures", json={"nom": "Client Acme", "type": "audit"})
    assert creation.status_code == 201
    vid = creation.json()["id"]

    # 2. Liaison geo_object_id + audit_id (PATCH).
    v = SimpleNamespace(
        id=vid, owner_id="user-1", org_id=None, nom="Client Acme", description="",
        emoji="🚀", couleur="#6366f1", type="audit", statut="actif",
        created_at=None, updated_at=None,
        geo_object_id=None, audit_id=None, profil_entreprise=None,
    )
    # `v` porte déjà geo-1/audit-1 : elle représente la ligne APRÈS l'UPDATE — le
    # SELECT du 2e execute() la relit telle quelle, comme le ferait Postgres.
    v.geo_object_id, v.audit_id = "geo-1", "audit-1"
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSessionPatch(rows=[v]))
    liaison = await client.patch(f"/api/ventures/{vid}", json={"geoObjectId": "geo-1", "auditId": "audit-1"})
    assert liaison.status_code == 200
    liaison_body = liaison.json()
    assert liaison_body["geoObjectId"] == "geo-1"
    assert liaison_body["auditId"] == "audit-1"

    # 3. Document ingéré avec venture_id (simulé côté ingestion via le mock réseau
    #    du dossier — l'upload réel est couvert par Task 3 côté ingestion).

    # 4. Lecture du dossier agrégé : identite (geo) + audit (business) + documents.
    #
    # `httpx.AsyncClient.get` est patché au niveau CLASSE : ça intercepte aussi
    # bien les appels sortants du routeur (geo/audit/ingestion, un nouveau
    # AsyncClient à chaque appel) QUE le `client` de test lui-même (qui est
    # aussi un AsyncClient, câblé sur l'ASGITransport de l'app — cf.
    # conftest.py). Pour toute URL qui ne correspond à aucune brique externe
    # simulée (i.e. l'appel du test vers /api/ventures/.../dossier), on relaie
    # vers l'implémentation d'origine — sinon le test intercepterait sa propre
    # requête vers l'app et ne l'exécuterait jamais (même piège déjà rencontré
    # et documenté dans tests/test_dossier_s227.py).
    _orig_get = httpx.AsyncClient.get

    async def _fake_get(self, url, **kw):
        url = str(url)
        if "geo.test" in url:
            return httpx.Response(200, json={"id": "geo-1", "metadata": {"nom": "Acme"}})
        if "audit.test" in url:
            return httpx.Response(200, json={"id": "audit-1", "statut": "termine"})
        if "ingestion.test" in url:
            return httpx.Response(200, json={"total": 1, "offset": 0,
                                             "documents": [{"id": "doc-1", "nom": "contrat.pdf"}]})
        return await _orig_get(self, url, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[v], [], []]))
    dossier = await client.get(f"/api/ventures/{vid}/dossier")

    assert dossier.status_code == 200
    body = dossier.json()
    assert body["identite"]["id"] == "geo-1"
    assert body["audit"]["id"] == "audit-1"
    # Fix 3 (revue post-fusion) : "documents" est une enveloppe {statut, documents}.
    assert body["documents"] == {"statut": "ok",
                                 "documents": [{"id": "doc-1", "nom": "contrat.pdf"}]}
