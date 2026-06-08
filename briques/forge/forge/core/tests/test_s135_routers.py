"""S135 — montage natif des routes comms & intégrations.

Toutes protégées par ``Depends(get_current_user)`` → 401 sans token, ce qui prouve
le montage natif (Python) et non un relais vers le Bun (qui répondrait autrement,
voire 502 sans amont). Vérifié aux deux préfixes /api et /v1/api.
"""

import pytest
from httpx import ASGITransport, AsyncClient

GET_ROUTES = [
    "/api/keybindings",
    "/api/saved-filters",
    "/api/imap/configs",
    "/api/imap/emails",
    "/api/calendar/events",
    "/api/social/platforms",
    "/api/mcp/servers",
    "/api/documents",
    "/api/analytics",
    "/api/sentinel-rgpd/checklist",
    "/api/poles/00000000-0000-0000-0000-000000000000/incidents",
    "/api/poles/00000000-0000-0000-0000-000000000000/social",
]

POST_ROUTES = [
    "/api/saved-filters",
    "/api/imap/configs",
    "/api/calendar/events",
    "/api/mcp/servers",
    "/api/documents/upload",
    "/api/sentinel-rgpd/audit",
    "/api/poles/00000000-0000-0000-0000-000000000000/incidents",
    "/api/poles/00000000-0000-0000-0000-000000000000/social",
]

CANONICAL = [
    "/v1/api/keybindings",
    "/v1/api/analytics",
    "/v1/api/mcp/servers",
    "/v1/api/sentinel-rgpd/checklist",
]


@pytest.mark.asyncio
async def test_s135_routes_mounted_native_401():
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in GET_ROUTES:
            r = await c.get(path)
            assert r.status_code == 401, f"GET {path} → {r.status_code}"
        for path in POST_ROUTES:
            r = await c.post(path, json={})
            assert r.status_code == 401, f"POST {path} → {r.status_code}"
        for path in CANONICAL:
            r = await c.get(path)
            assert r.status_code == 401, f"GET {path} → {r.status_code}"


@pytest.mark.asyncio
async def test_s135_put_delete_keybinding_401():
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/api/keybindings", json={})
        assert r.status_code == 401
        r = await c.delete("/api/keybindings/x")
        assert r.status_code == 401
