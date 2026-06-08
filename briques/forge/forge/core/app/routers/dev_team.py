"""Router dev-team. Portage de routes/dev-team.ts (S132). Monté /api, protégé.

Backlog de tâches de dev scopé par utilisateur (+ org via X-Org-ID, + filtre
?statut). Kanban DevTeam (cf. Sprint 50 frontend).
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import DevTasks
from app.serde import dev_task

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


@router.get("/dev-team")
async def list_dev_tasks(
    statut: str | None = None,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        cond = [DevTasks.user_id == user.sub, DevTasks.org_id == oid]
        if statut:
            cond.append(DevTasks.statut == statut)
        rows = (await s.execute(
            select(DevTasks).where(and_(*cond)).order_by(desc(DevTasks.created_at))
        )).scalars().all()
    return [dev_task(x) for x in rows]


class CreateDevTask(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    description: str | None = None
    type: str | None = None
    statut: str | None = None
    priorite: str | None = None
    poleId: str | None = None
    agentIA: str | None = None
    tempsEstime: int | None = None
    assigneA: str | None = None
    deadline: str | None = None


@router.post("/dev-team")
async def create_dev_task(
    body: CreateDevTask,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        t = DevTasks(
            user_id=user.sub, org_id=oid, pole_id=_uuid(body.poleId),
            titre=body.titre, description=body.description or "",
            type=body.type or "feature", statut=body.statut or "backlog",
            priorite=body.priorite or "normale",
            agent_ia=body.agentIA or "", temps_estime=body.tempsEstime or 0,
            assigne_a=body.assigneA or "", deadline=_parse_date(body.deadline),
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
    return JSONResponse(status_code=201, content=dev_task(t))


class UpdateDevTask(BaseModel):
    titre: str | None = None
    description: str | None = None
    type: str | None = None
    statut: str | None = None
    priorite: str | None = None
    agentIA: str | None = None
    analyseLLM: str | None = None
    assigneA: str | None = None


_PATCH_COLMAP = {
    "titre": "titre", "description": "description", "type": "type",
    "statut": "statut", "priorite": "priorite", "agentIA": "agent_ia",
    "analyseLLM": "analyse_llm", "assigneA": "assigne_a",
}


@router.patch("/dev-team/{tid}", dependencies=[Depends(get_current_user)])
async def update_dev_task(tid: str, body: UpdateDevTask, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    raw = body.model_dump(exclude_unset=True)
    cols = {_PATCH_COLMAP[k]: v for k, v in raw.items() if k in _PATCH_COLMAP}
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        t = None
        if tuid:
            await s.execute(
                update(DevTasks).where(and_(DevTasks.id == tuid, DevTasks.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            t = (await s.execute(
                select(DevTasks).where(and_(DevTasks.id == tuid, DevTasks.user_id == user.sub))
            )).scalar_one_or_none()
    return dev_task(t) if t is not None else None


@router.delete("/dev-team/{tid}", dependencies=[Depends(get_current_user)])
async def delete_dev_task(tid: str, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    async with SessionLocal() as s:
        if tuid:
            await s.execute(sa_delete(DevTasks).where(and_(DevTasks.id == tuid, DevTasks.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
