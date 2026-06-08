"""Router forecast. Portage de routes/forecast.ts (S131). Monté /api, protégé.

Prévisions financières mensuelles (annee_mois 'YYYY-MM') par pôle.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import ForecastEntries
from app.serde import forecast_entry

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/forecast", dependencies=[Depends(get_current_user)])
async def list_forecast(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(ForecastEntries).where(and_(
                ForecastEntries.pole_id == puid, ForecastEntries.user_id == user.sub))
            .order_by(desc(ForecastEntries.annee_mois))
        )).scalars().all()
    return [forecast_entry(e) for e in rows]


class CreateForecast(BaseModel):
    anneeMois: str = Field(pattern=r"^\d{4}-\d{2}$")
    montant: float
    categorie: str | None = None
    type: str | None = None
    source: str | None = None


@router.post("/poles/{pole_id}/forecast", dependencies=[Depends(get_current_user)])
async def create_forecast(pole_id: str, body: CreateForecast, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        e = ForecastEntries(
            pole_id=puid, user_id=user.sub, annee_mois=body.anneeMois, montant=body.montant,
            categorie=body.categorie or "", type=body.type or "recette", source=body.source or "manuel",
        )
        s.add(e)
        await s.commit()
        await s.refresh(e)
    return JSONResponse(status_code=201, content=forecast_entry(e))


@router.delete("/forecast/{eid}", dependencies=[Depends(get_current_user)])
async def delete_forecast(eid: str, user: UserContext = Depends(get_current_user)):
    euid = _uuid(eid)
    async with SessionLocal() as s:
        if euid:
            await s.execute(sa_delete(ForecastEntries).where(and_(
                ForecastEntries.id == euid, ForecastEntries.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
