"""Router agent-autonomy (rules/feedback/runs/scores). Portage de agent-autonomy.ts (S128).

Monté sur /api. Protégé.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import AgentAutonomyRules, AgentFeedback, AgentRuns, AgentScores
from app.serde import agent_feedback as ser_feedback
from app.serde import agent_run as ser_run
from app.serde import agent_score as ser_score
from app.serde import autonomy_rule as ser_rule

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except ValueError:
        return None


# ── Autonomy rules ──────────────────────────────────────────────────
@router.get("/agents/{agent_id}/autonomy")
async def get_autonomy(agent_id: str, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        rule = (await s.execute(
            select(AgentAutonomyRules).where(AgentAutonomyRules.agent_id == au).limit(1)
        )).scalar_one_or_none() if au else None
    return ser_rule(rule) if rule else {"niveau": "N1", "horaires": "{}", "overrideOk": False}


class PutAutonomy(BaseModel):
    niveau: str  # N0|N1|N2|N3
    horaires: str | None = None
    overrideOk: bool | None = None


@router.put("/agents/{agent_id}/autonomy")
async def put_autonomy(agent_id: str, body: PutAutonomy, response: Response, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(AgentAutonomyRules).where(AgentAutonomyRules.agent_id == au).limit(1)
        )).scalar_one_or_none() if au else None
        if existing:
            cols = {"niveau": body.niveau}
            if body.horaires is not None:
                cols["horaires"] = body.horaires
            if body.overrideOk is not None:
                cols["override_ok"] = body.overrideOk
            await s.execute(update(AgentAutonomyRules).where(AgentAutonomyRules.id == existing.id).values(updated_at=func.now(), **cols))
            await s.commit()
            row = (await s.execute(select(AgentAutonomyRules).where(AgentAutonomyRules.id == existing.id))).scalar_one()
            return ser_rule(row)
        row = AgentAutonomyRules(
            agent_id=au, user_id=user.sub, niveau=body.niveau,
            horaires=body.horaires if body.horaires is not None else "{}",
            override_ok=body.overrideOk if body.overrideOk is not None else False,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        response.status_code = 201
        return ser_rule(row)


# ── Feedback ────────────────────────────────────────────────────────
@router.get("/agents/{agent_id}/feedback")
async def get_feedback(agent_id: str, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AgentFeedback).where(AgentFeedback.agent_id == au).order_by(desc(AgentFeedback.created_at))
        )).scalars().all() if au else []
    avg = sum((r.rating if r.rating is not None else 3) for r in rows) / len(rows) if rows else 0
    return {"rows": [ser_feedback(r) for r in rows], "avg": avg}


class PostFeedback(BaseModel):
    rating: int = Field(ge=1, le=5)
    commentaire: str | None = None


@router.post("/agents/{agent_id}/feedback")
async def post_feedback(agent_id: str, body: PostFeedback, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        fb = AgentFeedback(agent_id=_uuid(agent_id), user_id=user.sub, rating=body.rating, commentaire=body.commentaire or "")
        s.add(fb)
        await s.commit()
        await s.refresh(fb)
        response.status_code = 201
        return ser_feedback(fb)


# ── Runs ────────────────────────────────────────────────────────────
@router.get("/agents/{agent_id}/runs")
async def get_runs(agent_id: str, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AgentRuns).where(AgentRuns.agent_id == au).order_by(desc(AgentRuns.created_at)).limit(100)
        )).scalars().all() if au else []
    return [ser_run(r) for r in rows]


class PostRun(BaseModel):
    input: str
    poleId: str | None = None


@router.post("/agents/{agent_id}/runs")
async def post_run(agent_id: str, body: PostRun, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        run = AgentRuns(agent_id=_uuid(agent_id), user_id=user.sub, pole_id=_uuid(body.poleId), input=body.input, statut="running")
        s.add(run)
        await s.commit()
        await s.refresh(run)
        response.status_code = 201
        return ser_run(run)


class PatchRun(BaseModel):
    statut: str | None = None
    output: str | None = None
    tokensIn: int | None = None
    tokensOut: int | None = None
    dureeMs: int | None = None


@router.patch("/agent-runs/{run_id}")
async def patch_run(run_id: str, body: PatchRun, user: UserContext = Depends(get_current_user)):
    ru = _uuid(run_id)
    field_map = {"statut": "statut", "output": "output", "tokensIn": "tokens_in", "tokensOut": "tokens_out", "dureeMs": "duree_ms"}
    cols = {field_map[k]: v for k, v in body.model_dump(exclude_unset=True).items()}
    if body.statut and body.statut != "running":
        cols["completed_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    async with SessionLocal() as s:
        if cols:
            await s.execute(update(AgentRuns).where(and_(AgentRuns.id == ru, AgentRuns.user_id == user.sub)).values(**cols))
            await s.commit()
        row = (await s.execute(select(AgentRuns).where(AgentRuns.id == ru))).scalar_one_or_none()
    return ser_run(row) if row else None


# ── Scores ──────────────────────────────────────────────────────────
@router.get("/agents/{agent_id}/score")
async def get_score(agent_id: str, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        score = (await s.execute(
            select(AgentScores).where(AgentScores.agent_id == au).limit(1)
        )).scalar_one_or_none() if au else None
    return ser_score(score) if score else {"confianceScore": 0, "riskLevel": "faible", "retroFeedback": ""}


class PutScore(BaseModel):
    confianceScore: float | None = None
    riskLevel: str | None = None
    retroFeedback: str | None = None


@router.put("/agents/{agent_id}/score")
async def put_score(agent_id: str, body: PutScore, response: Response, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    field_map = {"confianceScore": "confiance_score", "riskLevel": "risk_level", "retroFeedback": "retro_feedback"}
    cols = {field_map[k]: v for k, v in body.model_dump(exclude_unset=True).items()}
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(AgentScores).where(AgentScores.agent_id == au).limit(1)
        )).scalar_one_or_none() if au else None
        if existing:
            await s.execute(update(AgentScores).where(AgentScores.id == existing.id).values(updated_at=func.now(), **cols))
            await s.commit()
            row = (await s.execute(select(AgentScores).where(AgentScores.id == existing.id))).scalar_one()
            return ser_score(row)
        row = AgentScores(agent_id=au, **cols)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        response.status_code = 201
        return ser_score(row)
