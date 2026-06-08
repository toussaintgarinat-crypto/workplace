"""Router SLO. Portage de routes/slo.ts (S127).

Monté sur /api (routes /slo, /slo/{module}). Protégé.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, select, update

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import SloEntries
from app.serde import slo_entry

router = APIRouter()


@router.get("/slo")
async def get_slo(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    # S18 (Chantier 1) : le SLO est une métrique d'org. Avant, sans header on
    # renvoyait TOUS les SLO de tous les orgs (fuite). Désormais org validée obligatoire.
    async with SessionLocal() as session:
        stmt = select(SloEntries).where(SloEntries.org_id == uuidlib.UUID(org_id))
        rows = (await session.execute(stmt)).scalars().all()
    modules = [slo_entry(r) for r in rows]
    if rows:
        health_score = round(sum((r.health_score if r.health_score is not None else 100) for r in rows) / len(rows))
    else:
        health_score = 100
    return {"modules": modules, "healthScore": health_score}


class PutSlo(BaseModel):
    healthScore: int | None = None
    sloTarget: float | None = None
    sloCurrent: float | None = None
    erreurs24h: int | None = None


_FIELD_MAP = {
    "healthScore": "health_score",
    "sloTarget": "slo_target",
    "sloCurrent": "slo_current",
    "erreurs24h": "erreurs_24h",
}


@router.put("/slo/{module}")
async def put_slo(
    module: str, body: PutSlo, response: Response,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    # S18 (Chantier 1) : org validée obligatoire (avant, sans header on écrasait le
    # SLO d'un module tous orgs confondus — fuite d'écriture).
    org_uuid = uuidlib.UUID(org_id)

    cols = {_FIELD_MAP[k]: v for k, v in body.model_dump(exclude_none=True).items()}

    async with SessionLocal() as session:
        stmt = select(SloEntries).where(and_(
            SloEntries.module == module, SloEntries.org_id == org_uuid,
        ))
        existing = (await session.execute(stmt.limit(1))).scalar_one_or_none()

        if existing:
            if cols:
                await session.execute(
                    update(SloEntries).where(SloEntries.id == existing.id).values(updated_at=func.now(), **cols)
                )
                await session.commit()
            row = (await session.execute(select(SloEntries).where(SloEntries.id == existing.id))).scalar_one()
            return slo_entry(row)

        row = SloEntries(org_id=org_uuid, module=module, **cols)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        response.status_code = 201
        return slo_entry(row)
