"""S132 — montage natif des routes devops/déploiement (401 sans auth, pas un proxy Bun)."""

import pytest
from httpx import ASGITransport, AsyncClient

GET_ROUTES = [
    "/api/servers",
    "/api/gitpack/jobs",
    "/api/gitpack/jobs/j1",
    "/api/staging",
    "/api/dev-team",
    "/api/audit/m1/deployments",
    "/api/audit/instances/i1/stream",
    "/api/poles/p1/sprints",
    "/api/poles/p1/tasks",
    "/api/poles/p1/dag",
    "/api/netbird/peers",
    "/api/netbird/groups",
]

POST_ROUTES = [
    "/api/servers",
    "/api/gitpack/analyze",
    "/api/staging",
    "/api/dev-team",
    "/api/audit/m1/deploy",
    "/api/poles/p1/sprints",
    "/api/poles/p1/tasks",
    "/api/poles/p1/dag",
    "/api/poles/p1/dag/run",
    "/api/netbird/setup-keys",
]


@pytest.mark.asyncio
async def test_s132_routes_are_mounted_native_not_proxied():
    """Sans token, les routes S132 répondent 401 (montées nativement), pas un proxy."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in GET_ROUTES:
            r = await c.get(path)
            assert r.status_code == 401, f"GET {path} → {r.status_code}"
        for path in POST_ROUTES:
            r = await c.post(path, json={})
            assert r.status_code == 401, f"POST {path} → {r.status_code}"


@pytest.mark.asyncio
async def test_s132_canonical_v1_alias_mounted():
    """L'alias canonique /v1/api/* est monté pour les routes S132 (natif, pas 404/proxy)."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in ("/v1/api/servers", "/v1/api/staging", "/v1/api/netbird/peers",
                     "/v1/api/poles/p1/dag"):
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"
