"""Router staging. Portage de routes/staging.ts (S132). Monté /api, protégé.

Propositions de "mise en avant" (staging) scopées par organisation. S18 (Chantier 1) :
org issue du ``UserContext`` validé (``require_org``), jamais d'un ``X-Org-ID`` brut.
L'ancien fallback « absent => liste/maj globale (sql 1=1) » exposait tous les tenants.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update

from app.auth import require_org
from app.db import SessionLocal
from app.models import StagingProposals
from app.serde import staging_proposal

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/staging")
async def list_staging(org_id: str = Depends(require_org)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(StagingProposals).where(StagingProposals.org_id == oid)
            .order_by(desc(StagingProposals.created_at))
        )).scalars().all()
    return [staging_proposal(x) for x in rows]


class CreateStaging(BaseModel):
    contenu: str = Field(min_length=1)
    scoreMea: float | None = None


@router.post("/staging")
async def create_staging(
    body: CreateStaging,
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        p = StagingProposals(org_id=oid, contenu=body.contenu, score_mea=body.scoreMea or 0)
        s.add(p)
        await s.commit()
        await s.refresh(p)
    return JSONResponse(status_code=201, content=staging_proposal(p))


class PatchStaging(BaseModel):
    statut: str
    scoreMea: float | None = None


@router.patch("/staging/{pid}")
async def patch_staging(
    pid: str,
    body: PatchStaging,
    org_id: str = Depends(require_org),
):
    puid = _uuid(pid)
    oid = _uuid(org_id)
    cols: dict = {"statut": body.statut}
    if body.scoreMea is not None:
        cols["score_mea"] = body.scoreMea
    async with SessionLocal() as s:
        p = None
        if puid:
            cond = and_(StagingProposals.id == puid, StagingProposals.org_id == oid)
            await s.execute(update(StagingProposals).where(cond).values(**cols))
            await s.commit()
            p = (await s.execute(select(StagingProposals).where(cond))).scalar_one_or_none()
        if p is None:
            raise HTTPException(status_code=404, detail="Not found")
    return staging_proposal(p)
