"""Router hitl. Portage de routes/hitl.ts (S133). Monté /api, protégé.

Human-In-The-Loop : demandes d'arbitrage (niveaux 1..6) en attente / historique,
création, et décision (approved/rejected). Colonne payload = TEXT JSON.

NB parité : le Bun incrémente des compteurs ``metrics.hitl_*`` (in-memory, exposés
par /metrics — hors périmètre S133). Ce sont des effets de bord sans impact sur la
réponse HTTP ; non portés ici (le domaine metrics sera traité à son sprint).
"""

from __future__ import annotations

import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import HitlRequests
from app.serde import hitl_request

router = APIRouter()

HITL_LEVELS = {1: "Information", 2: "Confirmation", 3: "Approbation", 4: "Validation", 5: "Autorisation", 6: "Critique"}


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/hitl/pending", dependencies=[Depends(get_current_user)])
async def pending(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(HitlRequests)
            .where(and_(HitlRequests.user_id == user.sub, HitlRequests.statut == "pending"))
            .order_by(desc(HitlRequests.created_at))
        )).scalars().all()
    return [hitl_request(x) for x in rows]


@router.get("/hitl/history", dependencies=[Depends(get_current_user)])
async def history(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(HitlRequests).where(HitlRequests.user_id == user.sub)
            .order_by(desc(HitlRequests.created_at)).limit(50)
        )).scalars().all()
    return [hitl_request(x) for x in rows]


class CreateHitl(BaseModel):
    sessionId: str | None = None
    niveau: int = Field(default=1, ge=1, le=6)
    action: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


@router.post("/hitl/requests", dependencies=[Depends(get_current_user)])
async def create_request(body: CreateHitl, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        req = HitlRequests(
            user_id=user.sub, session_id=_uuid(body.sessionId),
            niveau=body.niveau, action=body.action,
            payload=json.dumps(body.payload), statut="pending",
        )
        s.add(req)
        await s.commit()
        await s.refresh(req)
    return JSONResponse(status_code=201, content=hitl_request(req))


class DecideHitl(BaseModel):
    decision: str  # 'approved' | 'rejected'


@router.post("/hitl/requests/{rid}/decide", dependencies=[Depends(get_current_user)])
async def decide_request(rid: str, body: DecideHitl, user: UserContext = Depends(get_current_user)):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid decision")
    ruid = _uuid(rid)
    async with SessionLocal() as s:
        req = None
        if ruid:
            await s.execute(
                update(HitlRequests)
                .where(and_(HitlRequests.id == ruid, HitlRequests.user_id == user.sub))
                .values(statut=body.decision, decide_par=user.sub, decide_at=datetime.datetime.utcnow())
            )
            await s.commit()
            req = (await s.execute(
                select(HitlRequests).where(and_(HitlRequests.id == ruid, HitlRequests.user_id == user.sub))
            )).scalar_one_or_none()
        if req is None:
            raise HTTPException(status_code=404, detail="Not found")
    return hitl_request(req)
