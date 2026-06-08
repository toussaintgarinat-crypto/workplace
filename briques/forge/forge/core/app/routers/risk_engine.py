"""Router risk-engine. Portage de routes/risk-engine.ts (S133). Monté /api, protégé.

Scoring de risque d'une action (heuristique mots-clés), journalisation, et
décision fast-path / review / block. ``score_action`` est PURE (testée), l'ordre
des branches est respecté à l'identique pour la parité (delete avant purge/drop).
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, desc, select, update

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import RiskLogs
from app.serde import risk_log

router = APIRouter()

FAST_PATH_WHITELIST = ["read", "list", "search", "get", "export_csv"]


def score_action(action: str) -> tuple[int, str]:
    """(score, niveau). Ordre des branches identique au Bun (parité)."""
    lower = action.lower()
    if any(k in lower for k in FAST_PATH_WHITELIST):
        return 5, "faible"
    if "delete" in lower or "supprimer" in lower:
        return 85, "eleve"
    if "deploy" in lower or "stripe" in lower or "email_send" in lower:
        return 70, "eleve"
    if "create" in lower or "update" in lower:
        return 35, "moyen"
    if "purge" in lower or "drop" in lower or "truncate" in lower:
        return 95, "critique"
    return 20, "faible"


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


class ScoreBody(BaseModel):
    action: str
    poleId: str | None = None
    contexte: str | None = None


@router.post("/risk-engine/score")
async def score(
    body: ScoreBody,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    sc, niveau = score_action(body.action)
    fast_path = sc <= 15
    async with SessionLocal() as s:
        log = RiskLogs(
            user_id=user.sub, org_id=oid, pole_id=_uuid(body.poleId),
            action=body.action, score=sc, niveau=niveau,
            fast_path=fast_path, approuve=fast_path, raison=body.contexte or "",
        )
        s.add(log)
        await s.commit()
        await s.refresh(log)
    out = risk_log(log)
    out["fastPath"] = fast_path
    out["recommande"] = "proceed" if fast_path else ("block" if sc >= 70 else "review")
    return out


@router.get("/risk-engine/logs")
async def list_logs(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    cond = [RiskLogs.user_id == user.sub, RiskLogs.org_id == oid]
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(RiskLogs).where(and_(*cond)).order_by(desc(RiskLogs.created_at)).limit(200)
        )).scalars().all()
    return [risk_log(x) for x in rows]


@router.patch("/risk-engine/logs/{lid}/approuve", dependencies=[Depends(get_current_user)])
async def approve_log(lid: str, user: UserContext = Depends(get_current_user)):
    luid = _uuid(lid)
    async with SessionLocal() as s:
        log = None
        if luid:
            await s.execute(
                update(RiskLogs).where(and_(RiskLogs.id == luid, RiskLogs.user_id == user.sub)).values(approuve=True)
            )
            await s.commit()
            log = (await s.execute(
                select(RiskLogs).where(and_(RiskLogs.id == luid, RiskLogs.user_id == user.sub))
            )).scalar_one_or_none()
    return risk_log(log) if log is not None else None
