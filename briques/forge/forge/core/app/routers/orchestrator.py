"""Router orchestrator sessions. Portage de orchestrator.ts (S128). Monté /api, protégé."""

from __future__ import annotations

import json
import uuid as uuidlib

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete as sa_delete, desc, func, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import OrchestratorSessions
from app.serde import orchestrator_session as ser

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except ValueError:
        return None


@router.get("/orchestrator/sessions")
async def list_sessions(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(OrchestratorSessions).where(OrchestratorSessions.user_id == user.sub).order_by(desc(OrchestratorSessions.created_at))
        )).scalars().all()
    return [ser(r) for r in rows]


class CreateSession(BaseModel):
    titre: str = Field(min_length=1)
    poleId: str | None = None
    agents: list[str] | None = None


@router.post("/orchestrator/sessions")
async def create_session(body: CreateSession, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        row = OrchestratorSessions(
            user_id=user.sub, pole_id=_uuid(body.poleId), titre=body.titre,
            agents=json.dumps(body.agents or []), statut="actif",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        response.status_code = 201
        return ser(row)


class PatchSession(BaseModel):
    statut: str | None = None
    output: str | None = None
    agents: list[str] | None = None


@router.patch("/orchestrator/sessions/{sid}")
async def patch_session(sid: str, body: PatchSession, user: UserContext = Depends(get_current_user)):
    su = _uuid(sid)
    cols: dict = {}
    if body.statut is not None:
        cols["statut"] = body.statut
    if body.output is not None:
        cols["output"] = body.output
    if body.agents is not None:
        cols["agents"] = json.dumps(body.agents)
    async with SessionLocal() as s:
        await s.execute(
            update(OrchestratorSessions)
            .where(and_(OrchestratorSessions.id == su, OrchestratorSessions.user_id == user.sub))
            .values(updated_at=func.now(), **cols)
        )
        await s.commit()
        row = (await s.execute(select(OrchestratorSessions).where(OrchestratorSessions.id == su))).scalar_one_or_none()
    return ser(row) if row else None


@router.delete("/orchestrator/sessions/{sid}")
async def delete_session(sid: str, user: UserContext = Depends(get_current_user)):
    su = _uuid(sid)
    async with SessionLocal() as s:
        await s.execute(sa_delete(OrchestratorSessions).where(and_(OrchestratorSessions.id == su, OrchestratorSessions.user_id == user.sub)))
        await s.commit()
    return {"ok": True}
