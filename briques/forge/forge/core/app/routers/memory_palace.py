"""Router memory (entrées mémoire agents). Portage de routes/memory-palace.ts (S129).

Monté /api, protégé. Clé/valeur typée (context/fact/preference/history), scopée user
+ X-Org-ID optionnel + agentId optionnel.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import MemoryEntries
from app.serde import memory_entry

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/memory")
async def list_memory(
    request: Request,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    type_ = request.query_params.get("type")
    agent_id = request.query_params.get("agentId")
    # S18 (Chantier 1) : scope org obligatoire (org active validée), jamais le header cru.
    conds = [MemoryEntries.user_id == user.sub, MemoryEntries.org_id == _uuid(org_id)]
    if type_:
        conds.append(MemoryEntries.type == type_)
    if agent_id:
        conds.append(MemoryEntries.agent_id == _uuid(agent_id))
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(MemoryEntries).where(and_(*conds)).order_by(desc(MemoryEntries.updated_at))
        )).scalars().all()
    return [memory_entry(r) for r in rows]


class CreateMemory(BaseModel):
    cle: str = Field(min_length=1, max_length=200)
    valeur: str
    type: Literal["context", "fact", "preference", "history"] | None = None
    agentId: str | None = None
    ttl: str | None = None


@router.post("/memory")
async def create_memory(
    body: CreateMemory,
    response: Response,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    ttl = None
    if body.ttl:
        try:
            ttl = datetime.datetime.fromisoformat(body.ttl.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ttl = None
    async with SessionLocal() as s:
        entry = MemoryEntries(
            user_id=user.sub, org_id=_uuid(org_id),
            cle=body.cle, valeur=body.valeur, type=body.type or "context",
            agent_id=_uuid(body.agentId), ttl=ttl,
        )
        s.add(entry)
        await s.commit()
        await s.refresh(entry)
    response.status_code = 201
    return memory_entry(entry)


class UpdateMemory(BaseModel):
    valeur: str


@router.put("/memory/{mid}", dependencies=[Depends(get_current_user)])
async def update_memory(mid: str, body: UpdateMemory, user: UserContext = Depends(get_current_user)):
    from sqlalchemy import func
    u = _uuid(mid)
    async with SessionLocal() as s:
        if u:
            await s.execute(
                update(MemoryEntries)
                .where(and_(MemoryEntries.id == u, MemoryEntries.user_id == user.sub))
                .values(valeur=body.valeur, updated_at=func.now())
            )
            await s.commit()
        row = (await s.execute(
            select(MemoryEntries).where(and_(MemoryEntries.id == u, MemoryEntries.user_id == user.sub))
        )).scalar_one_or_none() if u else None
    return memory_entry(row) if row else None


@router.delete("/memory/{mid}", dependencies=[Depends(get_current_user)])
async def delete_memory(mid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(mid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(MemoryEntries).where(
                and_(MemoryEntries.id == u, MemoryEntries.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
