"""S133 — montage natif des routes automation & pipelines (401 sans auth, pas un proxy Bun)."""

import pytest
from httpx import ASGITransport, AsyncClient

GET_ROUTES = [
    "/api/sessions",
    "/api/sessions/s1/messages",
    "/api/command-bridge/overview",
    "/api/command-bridge/decisions",
    "/api/command-bridge/blackboard",
    "/api/pipeline-templates",
    "/api/automation",
    "/api/templates",
    "/api/poles/p1/repetition-config",
    "/api/repetition/pending/p1",
    "/api/hitl/pending",
    "/api/hitl/history",
    "/api/governor/config",
    "/api/governor/usage",
    "/api/risk-engine/logs",
    "/api/degradation",
    "/api/degradation/m1/episodes",
]

POST_ROUTES = [
    "/api/sessions",
    "/api/command-bridge/decisions",
    "/api/command-bridge/poles/p1/toggle-pause",
    "/api/pipeline-templates",
    "/api/poles/p1/dag/import",
    "/api/pipeline-assistant/chat",
    "/api/automation",
    "/api/templates",
    "/api/repetition/event",
    "/api/hitl/requests",
    "/api/governor/usage",
    "/api/risk-engine/score",
    "/api/degradation",
]


@pytest.mark.asyncio
async def test_s133_routes_are_mounted_native_not_proxied():
    """Sans token, les routes S133 répondent 401 (montées nativement), pas un proxy."""
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
async def test_s133_canonical_v1_alias_mounted():
    """L'alias canonique /v1/api/* est monté pour les routes S133 (natif, pas 404/proxy)."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in ("/v1/api/sessions", "/v1/api/command-bridge/overview",
                     "/v1/api/pipeline-templates", "/v1/api/automation",
                     "/v1/api/governor/config", "/v1/api/degradation"):
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"
