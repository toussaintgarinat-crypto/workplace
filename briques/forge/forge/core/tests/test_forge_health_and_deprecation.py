"""/api/health natif (forme Bun) + headers Deprecation sur le legacy /api/*."""

import re


async def test_api_health_native_shape(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["module"] == "forge:core"
    assert re.match(r"\d{4}-\d{2}-\d{2}T.*Z$", body["timestamp"])


async def test_legacy_api_has_deprecation_headers(client):
    r = await client.get("/api/health")
    assert r.headers.get("deprecation") == "true"
    assert "Sunset" in r.headers or "sunset" in r.headers
    assert r.headers.get("link") == '</v1/api/health>; rel="successor-version"'


async def test_canonical_v1_has_no_deprecation(client):
    r = await client.get("/v1/api/health")
    assert r.status_code == 200
    assert r.json()["module"] == "forge:core"
    assert "deprecation" not in {k.lower() for k in r.headers}
