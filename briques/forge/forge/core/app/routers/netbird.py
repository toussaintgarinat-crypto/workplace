"""Router netbird. Portage de routes/netbird.ts (S132). Monté /api/netbird, protégé.

Proxy générique vers l'API NetBird (VPN mesh) avec le PAT serveur. Le token
Keycloak de l'utilisateur a déjà été validé (Depends get_current_user). 503 si
NETBIRD_TOKEN absent.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.config import settings

router = APIRouter(dependencies=[Depends(get_current_user)])


async def _proxy(path: str, method: str, body: dict | None = None) -> JSONResponse:
    if not settings.NETBIRD_TOKEN:
        return JSONResponse(
            status_code=503,
            content={"error": "NetBird not configured: NETBIRD_TOKEN is missing"},
        )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Token {settings.NETBIRD_TOKEN}",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.request(
                method, f"{settings.NETBIRD_API_URL}{path}", headers=headers, json=body
            )
        try:
            data = res.json()
        except ValueError:
            data = {}
        return JSONResponse(status_code=res.status_code, content=data)
    except httpx.HTTPError as err:
        return JSONResponse(status_code=503, content={"error": f"NetBird unreachable: {err}"})


async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except (ValueError, TypeError):
        return {}


# ── Peers ────────────────────────────────────────────────────
@router.get("/peers")
async def peers():
    return await _proxy("/api/peers", "GET")


# ── Groups ───────────────────────────────────────────────────
@router.get("/groups")
async def list_groups():
    return await _proxy("/api/groups", "GET")


@router.post("/groups")
async def create_group(request: Request):
    return await _proxy("/api/groups", "POST", await _json_body(request))


@router.put("/groups/{gid}")
async def update_group(gid: str, request: Request):
    return await _proxy(f"/api/groups/{gid}", "PUT", await _json_body(request))


@router.delete("/groups/{gid}")
async def delete_group(gid: str):
    return await _proxy(f"/api/groups/{gid}", "DELETE")


# ── Policies ─────────────────────────────────────────────────
@router.get("/policies")
async def list_policies():
    return await _proxy("/api/policies", "GET")


@router.post("/policies")
async def create_policy(request: Request):
    return await _proxy("/api/policies", "POST", await _json_body(request))


@router.put("/policies/{pid}")
async def update_policy(pid: str, request: Request):
    return await _proxy(f"/api/policies/{pid}", "PUT", await _json_body(request))


@router.delete("/policies/{pid}")
async def delete_policy(pid: str):
    return await _proxy(f"/api/policies/{pid}", "DELETE")


# ── Routes ───────────────────────────────────────────────────
@router.get("/routes")
async def routes():
    return await _proxy("/api/routes", "GET")


# ── DNS ──────────────────────────────────────────────────────
@router.get("/dns")
async def dns():
    return await _proxy("/api/dns/nameservers", "GET")


# ── Setup Keys (enrollment) ──────────────────────────────────
@router.post("/setup-keys")
async def create_setup_key(request: Request):
    body = await _json_body(request)
    return await _proxy("/api/setup-keys", "POST", {
        "name": f"forge-{int(time.time() * 1000)}",
        "type": "one-off",
        "expires_in": 86400,
        "usage_limit": 1,
        "auto_groups": body.get("groups", []),
        "ephemeral": False,
    })


@router.get("/setup-keys")
async def list_setup_keys():
    return await _proxy("/api/setup-keys", "GET")
