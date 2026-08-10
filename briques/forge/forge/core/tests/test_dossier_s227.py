"""S227 : GET /ventures/{id}/dossier — agrégateur avec repli honnête par section."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

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
    def __init__(self, rows_by_call):
        # rows_by_call : liste de listes, une par appel .execute() consécutif
        # (venture, poles, audit_missions dans cet ordre côté handler).
        self._rows_by_call = list(rows_by_call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)


def _mk_venture(**kw):
    base = dict(
        id="11111111-1111-1111-1111-111111111111", owner_id="user-1",
        geo_object_id="geo-1", audit_id="audit-1", profil_entreprise={"organisation": "SARL"},
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("scenario", ["nominal", "geo_en_panne", "audit_en_panne", "deux_en_panne"])
async def test_dossier_agrege(client, app, monkeypatch, scenario):
    # NB : cette brique expose `client` (httpx.AsyncClient nu, sans .app — cf.
    # conftest.py) et `app` comme deux fixtures distinctes ; le fixture `app`
    # porte les dependency_overrides (même convention que test_ventures_s227.py).
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [], []]))
    monkeypatch.setattr(ventures_mod.settings, "GEO_URL", "http://geo.test")
    monkeypatch.setattr(ventures_mod.settings, "AUDIT_URL", "http://audit.test")
    monkeypatch.setattr(ventures_mod.settings, "INGESTION_URL", "http://ingestion.test")

    # `httpx.AsyncClient.get` est patché au niveau CLASSE : ça intercepte aussi
    # bien les appels sortants du routeur (geo/audit/ingestion, un nouveau
    # AsyncClient à chaque appel) QUE le `client` de test lui-même (qui est
    # aussi un AsyncClient, câblé sur l'ASGITransport de l'app). Pour toute URL
    # qui ne correspond à aucune brique externe simulée (i.e. l'appel du test
    # vers /api/ventures/...), on relaie vers l'implémentation d'origine —
    # sinon le test intercepterait sa propre requête vers l'app et ne
    # l'exécuterait jamais.
    _orig_get = httpx.AsyncClient.get

    async def _fake_get(self, url, **kw):
        url = str(url)
        if scenario in ("geo_en_panne", "deux_en_panne") and "geo.test" in url:
            raise httpx.ConnectError("geo down")
        if scenario in ("audit_en_panne", "deux_en_panne") and "audit.test" in url:
            raise httpx.ConnectError("audit down")
        if "geo.test" in url:
            return httpx.Response(200, json={"id": "geo-1", "metadata": {"nom": "Acme"}})
        if "audit.test" in url:
            return httpx.Response(200, json={"id": "audit-1", "statut": "termine"})
        if "ingestion.test" in url:
            return httpx.Response(200, json={"total": 0, "offset": 0, "documents": []})
        return await _orig_get(self, url, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    r = await client.get(f"/api/ventures/{v.id}/dossier")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["profilEntreprise"] == {"organisation": "SARL"}
    if scenario == "geo_en_panne":
        assert body["identite"]["statut"] == "indisponible"
        assert body["identite"]["geoObjectId"] == "geo-1"
        assert body["audit"]["id"] == "audit-1"
    elif scenario == "audit_en_panne":
        assert body["audit"]["statut"] == "indisponible"
        assert body["audit"]["auditId"] == "audit-1"
        assert body["identite"]["id"] == "geo-1"
    elif scenario == "deux_en_panne":
        assert body["identite"]["statut"] == "indisponible"
        assert body["audit"]["statut"] == "indisponible"
    else:
        assert body["identite"]["id"] == "geo-1"
        assert body["audit"]["id"] == "audit-1"
