"""Router governor. Portage de routes/governor.ts (S133). Monté /api, protégé.

Gouvernance des coûts LLM : config budgets (upsert par user) + journal d'usage
(tokens/coût) avec agrégats. Cf. cost tracking S110 (cf. memory governor wiring).
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, desc, select, update

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import GovernorConfigs, GovernorUsage
from app.serde import governor_config, governor_usage

router = APIRouter()

_DEFAULT_CONFIG = {
    "budgetJournalier": 100000,
    "budgetMensuel": 2000000,
    "alerteSeuil": 80,
    "blocageSeuil": 95,
    "actif": True,
}


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/governor/config")
async def get_config(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    cond = [GovernorConfigs.user_id == user.sub, GovernorConfigs.org_id == oid]
    async with SessionLocal() as s:
        cfg = (await s.execute(
            select(GovernorConfigs).where(and_(*cond)).limit(1)
        )).scalar_one_or_none()
    return governor_config(cfg) if cfg is not None else dict(_DEFAULT_CONFIG)


class PutConfig(BaseModel):
    budgetJournalier: int | None = None
    budgetMensuel: int | None = None
    alerteSeuil: int | None = None
    blocageSeuil: int | None = None
    actif: bool | None = None


_CFG_COLMAP = {
    "budgetJournalier": "budget_journalier",
    "budgetMensuel": "budget_mensuel",
    "alerteSeuil": "alerte_seuil",
    "blocageSeuil": "blocage_seuil",
    "actif": "actif",
}


@router.put("/governor/config")
async def put_config(
    body: PutConfig,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    raw = body.model_dump(exclude_unset=True)
    cols = {_CFG_COLMAP[k]: v for k, v in raw.items() if k in _CFG_COLMAP}
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(GovernorConfigs).where(and_(
                GovernorConfigs.user_id == user.sub, GovernorConfigs.org_id == oid,
            )).limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            cols["updated_at"] = datetime.datetime.utcnow()
            await s.execute(update(GovernorConfigs).where(GovernorConfigs.id == existing.id).values(**cols))
            await s.commit()
            updated = (await s.execute(
                select(GovernorConfigs).where(GovernorConfigs.id == existing.id)
            )).scalar_one()
            return governor_config(updated)
        created = GovernorConfigs(user_id=user.sub, org_id=oid, **cols)
        s.add(created)
        await s.commit()
        await s.refresh(created)
    return JSONResponse(status_code=201, content=governor_config(created))


@router.get("/governor/usage", dependencies=[Depends(get_current_user)])
async def get_usage(
    depuis: str | None = None,
    user: UserContext = Depends(get_current_user),
):
    cond = [GovernorUsage.user_id == user.sub]
    if depuis:
        try:
            cond.append(GovernorUsage.created_at >= datetime.datetime.fromisoformat(depuis.replace("Z", "+00:00")))
        except ValueError:
            pass
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(GovernorUsage).where(and_(*cond)).order_by(desc(GovernorUsage.created_at)).limit(500)
        )).scalars().all()
    total_tokens = sum((r.tokens_in or 0) + (r.tokens_out or 0) for r in rows)
    total_cout = sum((r.cout_usd or 0) for r in rows)
    return {
        "rows": [governor_usage(r) for r in rows],
        "totalTokens": total_tokens,
        "totalCout": total_cout,
    }


class CreateUsage(BaseModel):
    provider: str
    model: str
    tokensIn: int | None = None
    tokensOut: int | None = None
    coutUsd: float | None = None
    poleId: str | None = None


@router.post("/governor/usage")
async def create_usage(
    body: CreateUsage,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        entry = GovernorUsage(
            user_id=user.sub, org_id=oid,
            provider=body.provider, model=body.model,
            tokens_in=body.tokensIn or 0, tokens_out=body.tokensOut or 0,
            cout_usd=body.coutUsd or 0, pole_id=_uuid(body.poleId),
        )
        s.add(entry)
        await s.commit()
        await s.refresh(entry)
    return JSONResponse(status_code=201, content=governor_usage(entry))
