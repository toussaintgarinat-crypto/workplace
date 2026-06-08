"""Router injection-guard. Portage de routes/injection-guard.ts (S127).

Monté sur /api (routes /injection-guard/check, /injection-guard/logs). Protégé.
"""

from __future__ import annotations

import re
import uuid as uuidlib

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, desc, select

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import InjectionLogs
from app.serde import injection_log

router = APIRouter()

# Ordre PRÉSERVÉ (le Bun renvoie le premier match) — patterns regex insensibles à la casse.
PATTERNS = [
    (re.compile(r"ignore previous instructions", re.I), "Ignore instructions pattern"),
    (re.compile(r"you are now", re.I), "Role override attempt"),
    (re.compile(r"jailbreak", re.I), "Jailbreak keyword"),
    (re.compile(r"system prompt", re.I), "System prompt exfiltration"),
    (re.compile(r"disregard|forget all", re.I), "Context erasure attempt"),
    (re.compile(r"\bDAN\b", re.I), "DAN prompt"),
]


class CheckInput(BaseModel):
    input: str


def detect(text: str) -> str:
    """Renvoie la raison du PREMIER pattern qui matche, sinon "" (logique pure)."""
    for pattern, label in PATTERNS:
        if pattern.search(text):
            return label
    return ""


@router.post("/injection-guard/check")
async def check(
    body: CheckInput,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    raison = detect(body.input)
    flagged = bool(raison)
    async with SessionLocal() as session:
        log = InjectionLogs(
            user_id=user.sub,
            org_id=uuidlib.UUID(org_id),
            input=body.input[:1000],
            flagged=flagged,
            raison=raison,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        log_id = str(log.id)
    return {"flagged": flagged, "raison": raison, "id": log_id}


@router.get("/injection-guard/logs")
async def logs(
    flagged: str | None = None,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    only_flagged = flagged == "true"
    async with SessionLocal() as session:
        stmt = select(InjectionLogs).where(and_(
            InjectionLogs.user_id == user.sub,
            InjectionLogs.org_id == uuidlib.UUID(org_id),
        ))
        if only_flagged:
            stmt = stmt.where(InjectionLogs.flagged == True)  # noqa: E712
        rows = (await session.execute(stmt.order_by(desc(InjectionLogs.created_at)).limit(200))).scalars().all()
    return [injection_log(r) for r in rows]
