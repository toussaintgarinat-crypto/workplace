"""Router personnalités Forge. Portage de routes/personalities.ts (S128).

Monté sur /api. Protégé. Personnalités GLOBALES (pas de scope user).
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import asc, delete as sa_delete, desc, select, update

from app.auth import get_current_user
from app.db import SessionLocal
from app.models import AgentDefinitions, ForgePersonalities
from app.serde import personality

router = APIRouter()


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except ValueError:
        return None


@router.get("/personalities", dependencies=[Depends(get_current_user)])
async def list_personalities():
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(ForgePersonalities).order_by(
                asc(ForgePersonalities.position),
                desc(ForgePersonalities.is_builtin),
                asc(ForgePersonalities.label),
            )
        )).scalars().all()
    return [personality(r) for r in rows]


class Reorder(BaseModel):
    ids: list[str] = Field(min_length=1)


@router.patch("/personalities/reorder", dependencies=[Depends(get_current_user)])
async def reorder(body: Reorder):
    async with SessionLocal() as s:
        for idx, pid in enumerate(body.ids):
            u = _uuid(pid)
            if u:
                await s.execute(update(ForgePersonalities).where(ForgePersonalities.id == u).values(position=idx))
        await s.commit()
    return {"ok": True}


class CreatePersonality(BaseModel):
    label: str = Field(min_length=1)
    emoji: str | None = None
    description: str | None = None
    systemPrompt: str | None = None


@router.post("/personalities", dependencies=[Depends(get_current_user)])
async def create_personality(body: CreatePersonality, response: Response):
    async with SessionLocal() as s:
        p = ForgePersonalities(
            label=body.label,
            emoji=body.emoji or "🤖",
            description=body.description or "",
            system_prompt=body.systemPrompt or "",
            is_builtin=0,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        response.status_code = 201
        return personality(p)


class UpdatePersonality(BaseModel):
    label: str | None = Field(default=None, min_length=1)
    emoji: str | None = None
    description: str | None = None
    systemPrompt: str | None = None


@router.put("/personalities/{pid}", dependencies=[Depends(get_current_user)])
async def update_personality(pid: str, body: UpdatePersonality):
    u = _uuid(pid)
    if u is None:
        raise HTTPException(status_code=404, detail="Not found")
    fields = {"label": "label", "emoji": "emoji", "description": "description", "systemPrompt": "system_prompt"}
    cols = {fields[k]: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    async with SessionLocal() as s:
        if cols:
            await s.execute(update(ForgePersonalities).where(ForgePersonalities.id == u).values(**cols))
            await s.commit()
        row = (await s.execute(select(ForgePersonalities).where(ForgePersonalities.id == u))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return personality(row)


@router.delete("/personalities/{pid}", dependencies=[Depends(get_current_user)])
async def delete_personality(pid: str):
    u = _uuid(pid)
    if u is None:
        raise HTTPException(status_code=404, detail="Not found")
    async with SessionLocal() as s:
        row = (await s.execute(select(ForgePersonalities).where(ForgePersonalities.id == u))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        if row.is_builtin:
            raise HTTPException(status_code=400, detail="Cannot delete a builtin personality")
        await s.execute(update(AgentDefinitions).where(AgentDefinitions.personality_id == u).values(personality_id=None))
        await s.execute(sa_delete(ForgePersonalities).where(ForgePersonalities.id == u))
        await s.commit()
    return {"ok": True}
