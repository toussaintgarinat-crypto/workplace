"""Dépendance auth — 401 sans token / token invalide (sans accès réseau ni DB)."""

import pytest


async def test_protected_route_without_token_401(client):
    # /api/slo est protégé → 401 avant tout accès DB
    r = await client.get("/api/slo")
    assert r.status_code == 401


async def test_invalid_token_401(client, monkeypatch):
    async def _raise(*a, **k):
        raise Exception("bad token")

    monkeypatch.setattr("app.auth.verify_token", _raise)
    r = await client.get("/api/slo", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["error"] == "Invalid token"


async def test_auth_router_also_protected(client):
    r = await client.patch("/api/auth/me", json={"nom": "x"})
    assert r.status_code == 401
