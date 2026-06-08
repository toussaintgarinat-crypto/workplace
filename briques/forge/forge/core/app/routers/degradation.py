"""Router degradation. Portage de routes/degradation.ts (S133). Monté /api, protégé.

Modes de dégradation par ressource (actif/graceMode) + épisodes. S18 (Chantier 1) :
org issue du ``UserContext`` validé (``require_org``), jamais d'un ``X-Org-ID`` brut.
L'ancien fallback « absent => global (sql 1=1) » exposait tous les tenants : supprimé.
Les épisodes sont scopés via le mode parent (vérifié appartenir à l'org).
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update

from app.auth import require_org
from app.db import SessionLocal
from app.models import DegradationEpisodes, DegradationModes
from app.serde import degradation_episode, degradation_mode

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


async def _mode_in_org(s, muid, oid):
    """Renvoie le mode si (et seulement si) il appartient à l'org. Sinon None."""
    if muid is None:
        return None
    return (await s.execute(
        select(DegradationModes).where(
            and_(DegradationModes.id == muid, DegradationModes.org_id == oid)
        )
    )).scalar_one_or_none()


@router.get("/degradation")
async def list_degradation(org_id: str = Depends(require_org)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(DegradationModes).where(DegradationModes.org_id == oid)
        )).scalars().all()
    return [degradation_mode(x) for x in rows]


class CreateMode(BaseModel):
    ressource: str = Field(min_length=1)
    actif: bool | None = None
    graceMode: bool | None = None


@router.post("/degradation")
async def create_degradation(
    body: CreateMode, org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        m = DegradationModes(
            org_id=oid, ressource=body.ressource,
            actif=body.actif if body.actif is not None else False,
            grace_mode=body.graceMode if body.graceMode is not None else False,
        )
        s.add(m)
        await s.commit()
        await s.refresh(m)
    return JSONResponse(status_code=201, content=degradation_mode(m))


class PatchMode(BaseModel):
    actif: bool | None = None
    graceMode: bool | None = None


@router.patch("/degradation/{mid}")
async def patch_degradation(
    mid: str, body: PatchMode, org_id: str = Depends(require_org),
):
    muid = _uuid(mid)
    oid = _uuid(org_id)
    raw = body.model_dump(exclude_unset=True)
    cols: dict = {}
    if "actif" in raw:
        cols["actif"] = raw["actif"]
    if "graceMode" in raw:
        cols["grace_mode"] = raw["graceMode"]
    async with SessionLocal() as s:
        m = None
        if muid:
            cond = and_(DegradationModes.id == muid, DegradationModes.org_id == oid)
            if cols:
                await s.execute(update(DegradationModes).where(cond).values(**cols))
                await s.commit()
            m = (await s.execute(select(DegradationModes).where(cond))).scalar_one_or_none()
    return degradation_mode(m) if m is not None else None


class CreateEpisode(BaseModel):
    dureeMinutes: int
    raison: str | None = None


@router.post("/degradation/{mid}/episodes")
async def create_episode(mid: str, body: CreateEpisode, org_id: str = Depends(require_org)):
    muid = _uuid(mid)
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        if await _mode_in_org(s, muid, oid) is None:
            raise HTTPException(status_code=404, detail="Not found")
        ep = DegradationEpisodes(mode_id=muid, duree_minutes=body.dureeMinutes, raison=body.raison or "")
        s.add(ep)
        await s.commit()
        await s.refresh(ep)
    return JSONResponse(status_code=201, content=degradation_episode(ep))


@router.get("/degradation/{mid}/episodes")
async def list_episodes(mid: str, org_id: str = Depends(require_org)):
    muid = _uuid(mid)
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        if await _mode_in_org(s, muid, oid) is None:
            raise HTTPException(status_code=404, detail="Not found")
        rows = (await s.execute(
            select(DegradationEpisodes).where(DegradationEpisodes.mode_id == muid)
            .order_by(desc(DegradationEpisodes.created_at))
        )).scalars().all()
    return [degradation_episode(x) for x in rows]
