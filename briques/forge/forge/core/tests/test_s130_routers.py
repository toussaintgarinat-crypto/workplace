"""S130 — montage natif des routes ventures/audit/etc. (401 sans auth, pas un proxy Bun)."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_s130_routes_are_mounted_native_not_proxied():
    """Sans token, les routes S130 répondent 401 (montées nativement), pas un proxy."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        get_paths = [
            "/api/ventures",
            "/api/poles",
            "/api/dev/requests",
            "/api/rapports",
            "/api/brief/config",
            "/api/briefs",
            "/api/veille/sources",
            "/api/veille/articles",
        ]
        for path in get_paths:
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"
        # POST protégés aussi
        for path in ("/api/ventures", "/api/rapports/generate", "/api/brief/generate"):
            r = await c.post(path, json={})
            assert r.status_code == 401, f"POST {path} → {r.status_code}"


@pytest.mark.asyncio
async def test_s130_canonical_v1_alias_mounted():
    """L'alias canonique /v1/api/* est monté pour les routes S130."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/api/ventures")
        assert r.status_code == 401  # natif (pas 404/proxy)
