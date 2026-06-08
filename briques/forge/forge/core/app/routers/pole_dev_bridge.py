"""Router pole-dev-bridge. Portage de routes/pole-dev-bridge.ts (S130). Monté /api, protégé.

Un pôle soumet une demande d'automatisation au « Pôle Dev » → analyse LLM → déploiement
en règle d'automation. LLM via la gateway (`generate_text`).
"""

from __future__ import annotations

import json
import uuid as uuidlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.llm import generate_text
from app.models import AutomationRules, PoleDevRequests
from app.serde import pole_dev_request

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


class CreateRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sourcePoleName: str
    sourcePoleEmoji: str | None = None
    frequency: str = "manual"  # daily|weekly|on_event|manual
    priority: str = "medium"  # low|medium|high|critical


@router.post("/poles/{pole_id}/dev-requests", dependencies=[Depends(get_current_user)])
async def submit_request(pole_id: str, body: CreateRequest, response: Response,
                         user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        req = PoleDevRequests(
            source_pole_id=_uuid(pole_id), source_pole_name=body.sourcePoleName,
            source_pole_emoji=body.sourcePoleEmoji or "📌", title=body.title,
            description=body.description, frequency=body.frequency, priority=body.priority,
            user_id=user.sub, status="pending",
        )
        s.add(req)
        await s.commit()
        await s.refresh(req)
    response.status_code = 201
    return pole_dev_request(req)


@router.get("/dev/requests", dependencies=[Depends(get_current_user)])
async def list_requests(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(PoleDevRequests).order_by(desc(PoleDevRequests.created_at))
        )).scalars().all()
    return [pole_dev_request(r) for r in rows]


@router.get("/poles/{pole_id}/dev-requests", dependencies=[Depends(get_current_user)])
async def list_pole_requests(pole_id: str, user: UserContext = Depends(get_current_user)):
    pu = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(PoleDevRequests).where(PoleDevRequests.source_pole_id == pu)
            .order_by(desc(PoleDevRequests.created_at))
        )).scalars().all() if pu else []
    return [pole_dev_request(r) for r in rows]


@router.post("/dev/requests/{rid}/analyze", dependencies=[Depends(get_current_user)])
async def analyze_request(rid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(rid)
    async with SessionLocal() as s:
        req = (await s.execute(
            select(PoleDevRequests).where(PoleDevRequests.id == u)
        )).scalar_one_or_none() if u else None
        if req is None:
            raise HTTPException(status_code=404, detail="Not found")
        await s.execute(update(PoleDevRequests).where(PoleDevRequests.id == u)
                        .values(status="analyzing", updated_at=datetime.utcnow()))
        await s.commit()

        prompt = f"""Tu es un architecte logiciel senior dans une entreprise utilisant des agents IA.
Un pôle "{req.source_pole_name}" a soumis cette demande d'automatisation :

Titre : {req.title}
Description : {req.description}
Fréquence : {req.frequency}
Priorité : {req.priority}

Analyse cette demande et réponds en JSON avec ce format exact :
{{
  "feasibility": "high|medium|low",
  "effort": "small|medium|large",
  "type": "automation|integration|ai_agent|scheduled_job|webhook",
  "analysis": "Analyse en 2-3 phrases : ce qui est répétitif, pourquoi c'est automatisable, risques.",
  "proposedSolution": "Solution technique concrète en 3-4 étapes numérotées.",
  "automationTrigger": "Description du déclencheur (ex: chaque lundi 8h, à chaque nouveau CRM contact...)",
  "estimatedTimeSaved": "Estimation du temps économisé par semaine (ex: 2h/semaine)"
}}"""
        text = await generate_text(prompt=prompt)
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = {"analysis": text, "proposedSolution": ""}

        await s.execute(update(PoleDevRequests).where(PoleDevRequests.id == u).values(
            status="analyzed",
            analysis=parsed.get("analysis") or text,
            proposed_solution=parsed.get("proposedSolution") or "",
            updated_at=datetime.utcnow(),
        ))
        await s.commit()
        updated = (await s.execute(
            select(PoleDevRequests).where(PoleDevRequests.id == u)
        )).scalar_one_or_none()
    return {**pole_dev_request(updated), "parsed": parsed}


class DeployRequest(BaseModel):
    trigger: str
    action: str
    conditions: str | None = None


@router.post("/dev/requests/{rid}/deploy", dependencies=[Depends(get_current_user)])
async def deploy_request(rid: str, body: DeployRequest, user: UserContext = Depends(get_current_user)):
    u = _uuid(rid)
    async with SessionLocal() as s:
        req = (await s.execute(
            select(PoleDevRequests).where(PoleDevRequests.id == u)
        )).scalar_one_or_none() if u else None
        if req is None:
            raise HTTPException(status_code=404, detail="Not found")
        rule = AutomationRules(
            user_id=user.sub, nom=req.title, trigger=body.trigger,
            actions=json.dumps([{"type": "custom", "value": body.action}]),
            conditions=body.conditions or "{}", actif=True,
        )
        s.add(rule)
        await s.flush()
        await s.execute(update(PoleDevRequests).where(PoleDevRequests.id == u).values(
            status="deployed", automation_rule_id=rule.id, updated_at=datetime.utcnow()))
        await s.commit()
        await s.refresh(rule)  # peuple created_at/updated_at (server_default)
        updated = (await s.execute(
            select(PoleDevRequests).where(PoleDevRequests.id == u)
        )).scalar_one_or_none()
        from app.serde import _sid, iso
        rule_json = {
            "id": _sid(rule.id), "userId": rule.user_id, "orgId": _sid(rule.org_id),
            "nom": rule.nom, "description": rule.description, "trigger": rule.trigger,
            "actions": rule.actions, "conditions": rule.conditions, "actif": rule.actif,
            "executions": rule.executions, "createdAt": iso(rule.created_at),
            "updatedAt": iso(rule.updated_at),
        }
    return {"request": pole_dev_request(updated), "rule": rule_json}


class PatchRequest(BaseModel):
    status: str | None = None
    rejectionReason: str | None = None
    analysis: str | None = None
    proposedSolution: str | None = None


@router.patch("/dev/requests/{rid}", dependencies=[Depends(get_current_user)])
async def patch_request(rid: str, body: PatchRequest, user: UserContext = Depends(get_current_user)):
    u = _uuid(rid)
    raw = body.model_dump(exclude_unset=True)
    colmap = {"status": "status", "rejectionReason": "rejection_reason",
              "analysis": "analysis", "proposedSolution": "proposed_solution"}
    cols = {colmap[k]: v for k, v in raw.items() if k in colmap}
    async with SessionLocal() as s:
        if u:
            await s.execute(update(PoleDevRequests).where(PoleDevRequests.id == u)
                            .values(updated_at=datetime.utcnow(), **cols))
            await s.commit()
        updated = (await s.execute(
            select(PoleDevRequests).where(PoleDevRequests.id == u)
        )).scalar_one_or_none() if u else None
    return pole_dev_request(updated) if updated else None
