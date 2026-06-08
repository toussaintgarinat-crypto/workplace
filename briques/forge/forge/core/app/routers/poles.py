"""Router poles. Portage de routes/poles.ts (S130). Monté /api/poles, protégé.

CRUD pôles + enrichissement `llmConfig` (preset scope='pole'). ventureId
obligatoire à la création.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import LlmPresets, PoleMembers, Poles
from app.serde import llm_preset, pole, pole_member

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("", dependencies=[Depends(get_current_user)])
async def list_poles(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        if user.org_id:
            where = Poles.org_id == _uuid(user.org_id)
        else:
            where = Poles.owner_id == user.sub
        rows = (await s.execute(select(Poles).where(where))).scalars().all()
        if not rows:
            return []
        ids = [str(p.id) for p in rows]
        configs = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == "pole", LlmPresets.scope_id.in_(ids)))
        )).scalars().all()
    cfg_map = {c.scope_id: c for c in configs}
    return [{**pole(p), "llmConfig": (llm_preset(cfg_map[str(p.id)]) if str(p.id) in cfg_map else None)}
            for p in rows]


@router.get("/{pid}", dependencies=[Depends(get_current_user)])
async def get_pole(pid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(pid)
    async with SessionLocal() as s:
        if user.org_id:
            cond = or_(Poles.org_id == _uuid(user.org_id), Poles.owner_id == user.sub)
        else:
            cond = Poles.owner_id == user.sub
        p = (await s.execute(
            select(Poles).where(and_(Poles.id == u, cond))
        )).scalar_one_or_none() if u else None
        if p is None:
            raise HTTPException(status_code=404, detail="Not found")
        config = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == "pole", LlmPresets.scope_id == pid))
        )).scalar_one_or_none()
        members = (await s.execute(select(PoleMembers).where(PoleMembers.pole_id == u))).scalars().all()
    return {**pole(p), "llmConfig": (llm_preset(config) if config else None),
            "members": [pole_member(m) for m in members]}


class CreatePole(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    description: str = ""
    emoji: str = "🌍"
    couleur: str = "#6366f1"
    type: str = "custom"
    ventureId: str = Field(min_length=1)


@router.post("", dependencies=[Depends(get_current_user)])
async def create_pole(body: CreatePole, response: Response, user: UserContext = Depends(get_current_user)):
    if _uuid(body.ventureId) is None:
        raise HTTPException(status_code=400, detail="ventureId est obligatoire")
    async with SessionLocal() as s:
        p = Poles(nom=body.nom, description=body.description, emoji=body.emoji, couleur=body.couleur,
                  type=body.type, venture_id=body.ventureId, owner_id=user.sub,
                  org_id=_uuid(user.org_id) if user.org_id else None)
        s.add(p)
        await s.flush()
        s.add(PoleMembers(pole_id=p.id, user_id=user.sub, nom=user.nom,
                          avatar_emoji=user.avatar_emoji, role="owner"))
        s.add(LlmPresets(scope_type="pole", scope_id=str(p.id),
                         venture_id=_uuid(body.ventureId), updated_by=user.sub))
        await s.commit()
        await s.refresh(p)
    response.status_code = 201
    return pole(p)


class UpdatePole(BaseModel):
    nom: str | None = None
    description: str | None = None
    emoji: str | None = None
    couleur: str | None = None
    type: str | None = None
    ventureId: str | None = None


@router.patch("/{pid}", dependencies=[Depends(get_current_user)])
async def update_pole(pid: str, body: UpdatePole, user: UserContext = Depends(get_current_user)):
    u = _uuid(pid)
    raw = body.model_dump(exclude_unset=True)
    colmap = {"nom": "nom", "description": "description", "emoji": "emoji",
              "couleur": "couleur", "type": "type", "ventureId": "venture_id"}
    cols = {colmap[k]: v for k, v in raw.items() if k in colmap}
    async with SessionLocal() as s:
        p = None
        if u and cols:
            await s.execute(
                update(Poles).where(and_(Poles.id == u, Poles.owner_id == user.sub)).values(**cols)
            )
            await s.commit()
        if u:
            p = (await s.execute(
                select(Poles).where(and_(Poles.id == u, Poles.owner_id == user.sub))
            )).scalar_one_or_none()
        if p is None:
            raise HTTPException(status_code=404, detail="Not found")
    return pole(p)


@router.delete("/{pid}", dependencies=[Depends(get_current_user)])
async def delete_pole(pid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(pid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(Poles).where(and_(Poles.id == u, Poles.owner_id == user.sub)))
            await s.commit()
    return {"deleted": True}
