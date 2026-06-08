"""Router sprints. Portage de routes/sprints.ts (S132). Monté /api, protégé.

Sprints + tâches scopés par pôle/utilisateur. Le PATCH ignore les champs falsy
(parité Bun : `if (body.nom)`), sauf `description`/`assigneA`/`sprintId` testés
explicitement contre undefined.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Sprints, Tasks
from app.serde import sprint as ser_sprint
from app.serde import task as ser_task

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _parse_date(v: str | None):
    if not v:
        return None
    try:
        return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


# ── Sprints ──────────────────────────────────────────────────

@router.get("/poles/{pole_id}/sprints", dependencies=[Depends(get_current_user)])
async def list_sprints(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Sprints).where(and_(Sprints.pole_id == puid, Sprints.user_id == user.sub))
            .order_by(desc(Sprints.created_at))
        )).scalars().all()
    return [ser_sprint(x) for x in rows]


class CreateSprint(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    objectif: str | None = None
    dateFin: str | None = None


@router.post("/poles/{pole_id}/sprints", dependencies=[Depends(get_current_user)])
async def create_sprint(pole_id: str, body: CreateSprint, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        sp = Sprints(
            pole_id=puid, user_id=user.sub, nom=body.nom,
            objectif=body.objectif or "", date_fin=_parse_date(body.dateFin),
        )
        s.add(sp)
        await s.commit()
        await s.refresh(sp)
    return JSONResponse(status_code=201, content=ser_sprint(sp))


class UpdateSprint(BaseModel):
    nom: str | None = None
    objectif: str | None = None
    statut: str | None = None
    dateFin: str | None = None


@router.patch("/sprints/{sid}", dependencies=[Depends(get_current_user)])
async def update_sprint(sid: str, body: UpdateSprint, user: UserContext = Depends(get_current_user)):
    suid = _uuid(sid)
    cols: dict = {}
    if body.nom:
        cols["nom"] = body.nom
    if body.objectif is not None:
        cols["objectif"] = body.objectif
    if body.statut:
        cols["statut"] = body.statut
    if body.dateFin:
        cols["date_fin"] = _parse_date(body.dateFin)
    async with SessionLocal() as s:
        sp = None
        if suid:
            if cols:
                await s.execute(
                    update(Sprints).where(and_(Sprints.id == suid, Sprints.user_id == user.sub)).values(**cols)
                )
                await s.commit()
            sp = (await s.execute(
                select(Sprints).where(and_(Sprints.id == suid, Sprints.user_id == user.sub))
            )).scalar_one_or_none()
        if sp is None:
            raise HTTPException(status_code=404, detail="Not found")
    return ser_sprint(sp)


@router.delete("/sprints/{sid}", dependencies=[Depends(get_current_user)])
async def delete_sprint(sid: str, user: UserContext = Depends(get_current_user)):
    suid = _uuid(sid)
    async with SessionLocal() as s:
        if suid:
            await s.execute(sa_delete(Sprints).where(and_(Sprints.id == suid, Sprints.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


# ── Tasks ────────────────────────────────────────────────────

@router.get("/poles/{pole_id}/tasks", dependencies=[Depends(get_current_user)])
async def list_tasks(pole_id: str, sprintId: str | None = None, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        cond = [Tasks.pole_id == puid, Tasks.user_id == user.sub]
        if sprintId:
            cond.append(Tasks.sprint_id == _uuid(sprintId))
        rows = (await s.execute(
            select(Tasks).where(and_(*cond)).order_by(desc(Tasks.created_at))
        )).scalars().all()
    return [ser_task(x) for x in rows]


class CreateTask(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    description: str | None = None
    sprintId: str | None = None
    priorite: str | None = None
    assigneA: str | None = None


@router.post("/poles/{pole_id}/tasks", dependencies=[Depends(get_current_user)])
async def create_task(pole_id: str, body: CreateTask, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        t = Tasks(
            pole_id=puid, user_id=user.sub, titre=body.titre,
            description=body.description or "", sprint_id=_uuid(body.sprintId),
            priorite=body.priorite or "normale", assigne_a=body.assigneA,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
    return JSONResponse(status_code=201, content=ser_task(t))


class UpdateTask(BaseModel):
    titre: str | None = None
    description: str | None = None
    statut: str | None = None
    priorite: str | None = None
    assigneA: str | None = None
    sprintId: str | None = None


@router.patch("/tasks/{tid}", dependencies=[Depends(get_current_user)])
async def update_task(tid: str, body: UpdateTask, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    raw = body.model_dump(exclude_unset=True)
    cols: dict = {"updated_at": datetime.datetime.utcnow()}
    if body.titre:
        cols["titre"] = body.titre
    if "description" in raw:
        cols["description"] = body.description
    if body.statut:
        cols["statut"] = body.statut
    if body.priorite:
        cols["priorite"] = body.priorite
    if "assigneA" in raw:
        cols["assigne_a"] = body.assigneA
    if "sprintId" in raw:
        cols["sprint_id"] = _uuid(body.sprintId)
    async with SessionLocal() as s:
        t = None
        if tuid:
            await s.execute(
                update(Tasks).where(and_(Tasks.id == tuid, Tasks.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            t = (await s.execute(
                select(Tasks).where(and_(Tasks.id == tuid, Tasks.user_id == user.sub))
            )).scalar_one_or_none()
        if t is None:
            raise HTTPException(status_code=404, detail="Not found")
    return ser_task(t)


@router.delete("/tasks/{tid}", dependencies=[Depends(get_current_user)])
async def delete_task(tid: str, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    async with SessionLocal() as s:
        if tuid:
            await s.execute(sa_delete(Tasks).where(and_(Tasks.id == tuid, Tasks.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
