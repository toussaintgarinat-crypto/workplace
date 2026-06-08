"""Router MCP (serveurs Model Context Protocol). Portage de routes/mcp.ts (S135).

Monté /api, protégé. CRUD de serveurs MCP scopés (perso / venture / pôle) +
introspection (``/tools``) et invocation (``/call``) via le client MCP.

``authToken`` est masqué en lecture (GET → ``***``, POST → ``''``). ⚠️ Quirk Bun
préservé : le PATCH renvoie la ligne brute de ``.returning()`` → ``authToken`` y
apparaît en clair (comportement identique au Bun, non corrigé pour parité).
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.mcp_client import call_mcp_tool, list_mcp_tools
from app.models import McpServers
from app.serde import mcp_server

router = APIRouter()

_AUTH_TYPES = {"none", "bearer", "basic"}


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _scope_filter(user: UserContext, pole_id: str | None, venture_id: str | None):
    base = McpServers.user_id == user.sub
    if pole_id:
        return and_(base, McpServers.pole_id == _uuid(pole_id))
    if venture_id:
        return and_(base, McpServers.venture_id == _uuid(venture_id), McpServers.pole_id.is_(None))
    return and_(base, McpServers.venture_id.is_(None), McpServers.pole_id.is_(None))


@router.get("/mcp/servers", dependencies=[Depends(get_current_user)])
async def list_servers(request: Request, user: UserContext = Depends(get_current_user)):
    pole_id = request.query_params.get("poleId")
    venture_id = request.query_params.get("ventureId")
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(McpServers).where(_scope_filter(user, pole_id, venture_id))
        )).scalars().all()
    out = []
    for r in rows:
        d = mcp_server(r)
        d["authToken"] = "***" if r.auth_token else ""
        out.append(d)
    return out


class CreateServer(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1)
    authType: str = "none"
    authToken: str = ""
    ventureId: str | None = None
    poleId: str | None = None


@router.post("/mcp/servers", dependencies=[Depends(get_current_user)])
async def create_server(body: CreateServer, response: Response,
                        user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        row = McpServers(
            user_id=user.sub, nom=body.nom, url=body.url,
            auth_type=body.authType if body.authType in _AUTH_TYPES else "none",
            auth_token=body.authToken,
            venture_id=_uuid(body.ventureId),
            pole_id=_uuid(body.poleId),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    d = mcp_server(row)
    d["authToken"] = ""
    response.status_code = 201
    return d


@router.patch("/mcp/servers/{mid}", dependencies=[Depends(get_current_user)])
async def update_server(mid: str, body: dict, user: UserContext = Depends(get_current_user)):
    u = _uuid(mid)
    colmap = {"nom": "nom", "url": "url", "actif": "actif",
              "authType": "auth_type", "authToken": "auth_token"}
    updates = {colmap[k]: v for k, v in body.items() if k in colmap}
    async with SessionLocal() as s:
        if u and updates:
            await s.execute(
                update(McpServers).where(and_(
                    McpServers.id == u, McpServers.user_id == user.sub,
                )).values(**updates)
            )
            await s.commit()
        row = (await s.execute(
            select(McpServers).where(and_(
                McpServers.id == u, McpServers.user_id == user.sub,
            ))
        )).scalar_one_or_none() if u else None
    # Quirk Bun : ligne brute renvoyée (authToken en clair).
    return mcp_server(row) if row else None


@router.delete("/mcp/servers/{mid}", dependencies=[Depends(get_current_user)])
async def delete_server(mid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(mid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(McpServers).where(and_(
                McpServers.id == u, McpServers.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}


async def _load_server(mid: str, user: UserContext):
    u = _uuid(mid)
    async with SessionLocal() as s:
        row = (await s.execute(
            select(McpServers).where(and_(
                McpServers.id == u, McpServers.user_id == user.sub,
            ))
        )).scalar_one_or_none() if u else None
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.get("/mcp/servers/{mid}/tools", dependencies=[Depends(get_current_user)])
async def server_tools(mid: str, user: UserContext = Depends(get_current_user)):
    server = await _load_server(mid, user)
    return await list_mcp_tools(server)


class CallTool(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


@router.post("/mcp/servers/{mid}/call", dependencies=[Depends(get_current_user)])
async def server_call(mid: str, body: CallTool, user: UserContext = Depends(get_current_user)):
    server = await _load_server(mid, user)
    return {"result": await call_mcp_tool(server, body.tool, body.args)}
