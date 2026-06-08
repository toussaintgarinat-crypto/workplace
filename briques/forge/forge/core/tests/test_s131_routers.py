"""S131 — montage natif des routes business/finance (401 sans auth, pas un proxy Bun)."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_s131_routes_are_mounted_native_not_proxied():
    """Sans token, les routes S131 répondent 401 (montées nativement), pas un proxy."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        get_paths = [
            "/api/orgs",
            "/api/team",
            "/api/facturation",
            "/api/stripe/plans",
            "/api/stripe/payments",
            "/api/poles/p1/crm",
            "/api/poles/p1/contrats",
            "/api/poles/p1/budget",
            "/api/poles/p1/forecast",
            "/api/poles/p1/okrs",
        ]
        for path in get_paths:
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"
        for path in ("/api/orgs", "/api/facturation", "/api/prospection/analyze",
                     "/api/stripe/checkout", "/api/team"):
            r = await c.post(path, json={})
            assert r.status_code == 401, f"POST {path} → {r.status_code}"


@pytest.mark.asyncio
async def test_s131_canonical_v1_alias_mounted():
    """L'alias canonique /v1/api/* est monté pour les routes S131."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in ("/v1/api/orgs", "/v1/api/facturation", "/v1/api/stripe/plans"):
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"  # natif (pas 404/proxy)
