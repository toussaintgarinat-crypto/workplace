"""Router automation. Portage de routes/automation.ts (S133). Monté /api, protégé.

Règles d'automatisation (trigger + conditions + actions), scopées par
``user.sub`` et organisation optionnelle (header X-Org-ID ; absent => parité du
``sql 1=1`` côté Bun). Colonnes conditions/actions = TEXT JSON.
"""

from __future__ import annotations

import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import AutomationRules
from app.serde import automation_rule

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/automation")
async def list_automation(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    cond = [AutomationRules.user_id == user.sub, AutomationRules.org_id == oid]
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AutomationRules).where(and_(*cond)).order_by(desc(AutomationRules.created_at))
        )).scalars().all()
    return [automation_rule(x) for x in rows]


class CreateAutomation(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str | None = None
    trigger: str = Field(min_length=1)
    conditions: dict | None = None
    actions: list | None = None
    actif: bool | None = None


@router.post("/automation")
async def create_automation(
    body: CreateAutomation,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        rule = AutomationRules(
            user_id=user.sub, org_id=oid,
            nom=body.nom, description=body.description or "",
            trigger=body.trigger,
            conditions=json.dumps(body.conditions or {}),
            actions=json.dumps(body.actions or []),
            actif=body.actif if body.actif is not None else True,
        )
        s.add(rule)
        await s.commit()
        await s.refresh(rule)
    return JSONResponse(status_code=201, content=automation_rule(rule))


class PatchAutomation(BaseModel):
    nom: str | None = None
    trigger: str | None = None
    conditions: dict | None = None
    actions: list | None = None
    actif: bool | None = None


@router.patch("/automation/{aid}", dependencies=[Depends(get_current_user)])
async def patch_automation(
    aid: str, body: PatchAutomation, user: UserContext = Depends(get_current_user),
):
    auid = _uuid(aid)
    raw = body.model_dump(exclude_unset=True)
    cols: dict = {}
    if "nom" in raw:
        cols["nom"] = raw["nom"]
    if "trigger" in raw:
        cols["trigger"] = raw["trigger"]
    if "actif" in raw:
        cols["actif"] = raw["actif"]
    if body.conditions is not None:
        cols["conditions"] = json.dumps(body.conditions)
    if body.actions is not None:
        cols["actions"] = json.dumps(body.actions)
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        rule = None
        if auid:
            await s.execute(
                update(AutomationRules)
                .where(and_(AutomationRules.id == auid, AutomationRules.user_id == user.sub))
                .values(**cols)
            )
            await s.commit()
            rule = (await s.execute(
                select(AutomationRules).where(and_(AutomationRules.id == auid, AutomationRules.user_id == user.sub))
            )).scalar_one_or_none()
    return automation_rule(rule) if rule is not None else None


@router.delete("/automation/{aid}", dependencies=[Depends(get_current_user)])
async def delete_automation(aid: str, user: UserContext = Depends(get_current_user)):
    auid = _uuid(aid)
    async with SessionLocal() as s:
        if auid:
            await s.execute(
                sa_delete(AutomationRules).where(and_(AutomationRules.id == auid, AutomationRules.user_id == user.sub))
            )
            await s.commit()
    return {"ok": True}
