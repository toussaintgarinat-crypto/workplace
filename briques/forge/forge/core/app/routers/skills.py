"""Router Skills. Portage de routes/skills.ts. Monté /api, protégé.

Re-porté en S137 : la route Bun avait été droppée au cutover S136 alors que le
frontend l'appelle toujours (SkillsView, VentureDetail, GovernancePanel). CRUD de
compétences (markdown) scopées user / venture / pôle, + skills globaux partagés.

Quirk Drizzle conservé (parité Bun) : la colonne `tags` stocke une string JSON
(`JSON.stringify(array)` au POST) et est renvoyée telle quelle en lecture.
"""

from __future__ import annotations

import json
import uuid as uuidlib

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Skills
from app.serde import skill

router = APIRouter()


def _uuid(v: str | None):
    if not v:
        return None
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _scope_filter(user_sub: str, pole_id: str | None, venture_id: str | None):
    """Réplique scopeFilter() du Bun (skills.ts).

    - poleId   → user + pole
    - ventureId→ user + venture + pole IS NULL
    - sinon    → (user OR global) + venture IS NULL + pole IS NULL
    """
    if pole_id:
        return and_(Skills.user_id == user_sub, Skills.pole_id == _uuid(pole_id))
    if venture_id:
        return and_(
            Skills.user_id == user_sub,
            Skills.venture_id == _uuid(venture_id),
            Skills.pole_id.is_(None),
        )
    return and_(
        or_(Skills.user_id == user_sub, Skills.is_global == True),  # noqa: E712
        Skills.venture_id.is_(None),
        Skills.pole_id.is_(None),
    )


@router.get("/skills", dependencies=[Depends(get_current_user)])
async def list_skills(request: Request, user: UserContext = Depends(get_current_user)):
    pole_id = request.query_params.get("poleId")
    venture_id = request.query_params.get("ventureId")
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Skills).where(_scope_filter(user.sub, pole_id, venture_id))
        )).scalars().all()
    return [skill(r) for r in rows]


@router.get("/skills/active", dependencies=[Depends(get_current_user)])
async def list_active_skills(request: Request, user: UserContext = Depends(get_current_user)):
    pole_id = request.query_params.get("poleId")
    venture_id = request.query_params.get("ventureId")
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Skills).where(and_(
                _scope_filter(user.sub, pole_id, venture_id),
                Skills.actif == True,  # noqa: E712
            ))
        )).scalars().all()
    return [skill(r) for r in rows]


class CreateSkill(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    skillMd: str = Field(min_length=1)
    actif: bool = True
    ventureId: str | None = None
    poleId: str | None = None


@router.post("/skills", dependencies=[Depends(get_current_user)])
async def create_skill(body: CreateSkill, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        row = Skills(
            user_id=user.sub,
            nom=body.nom,
            description=body.description,
            tags=json.dumps(body.tags),  # quirk Bun : JSON.stringify(array)
            skill_md=body.skillMd,
            actif=body.actif,
            venture_id=_uuid(body.ventureId),
            pole_id=_uuid(body.poleId),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return skill(row)


@router.patch("/skills/{sid}", dependencies=[Depends(get_current_user)])
async def update_skill(sid: str, body: dict = Body(default={}), user: UserContext = Depends(get_current_user)):
    u = _uuid(sid)
    colmap = {"nom": "nom", "description": "description", "actif": "actif", "skillMd": "skill_md"}
    cols = {colmap[k]: v for k, v in body.items() if k in colmap}
    async with SessionLocal() as s:
        if cols and u:
            await s.execute(
                update(Skills)
                .where(and_(Skills.id == u, Skills.user_id == user.sub))
                .values(updated_at=func.now(), **cols)
            )
            await s.commit()
        row = (await s.execute(
            select(Skills).where(and_(Skills.id == u, Skills.user_id == user.sub))
        )).scalar_one_or_none() if u else None
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return skill(row)


@router.delete("/skills/{sid}", dependencies=[Depends(get_current_user)])
async def delete_skill(sid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(sid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(Skills).where(and_(Skills.id == u, Skills.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
