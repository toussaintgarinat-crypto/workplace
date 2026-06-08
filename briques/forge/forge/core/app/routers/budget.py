"""Router budget. Portage de routes/budget.ts (S131). Monté /api, protégé.

Entrées de budget (recette/dépense) par pôle, avec agrégats total/recettes/dépenses.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import BudgetEntries
from app.serde import budget_entry

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/budget", dependencies=[Depends(get_current_user)])
async def list_budget(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(BudgetEntries).where(and_(BudgetEntries.pole_id == puid, BudgetEntries.user_id == user.sub))
            .order_by(desc(BudgetEntries.date))
        )).scalars().all()
    total = sum((e.montant if e.type == "recette" else -e.montant) for e in rows)
    recettes = sum(e.montant for e in rows if e.type == "recette")
    depenses = sum(e.montant for e in rows if e.type == "depense")
    return {"entries": [budget_entry(e) for e in rows], "total": total,
            "recettes": recettes, "depenses": depenses}


class CreateEntry(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    montant: int = Field(gt=0)
    type: str
    categorie: str | None = None
    date: str | None = None


@router.post("/poles/{pole_id}/budget", dependencies=[Depends(get_current_user)])
async def create_entry(pole_id: str, body: CreateEntry, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    when = datetime.datetime.fromisoformat(body.date.replace("Z", "+00:00")) if body.date else datetime.datetime.utcnow()
    async with SessionLocal() as s:
        e = BudgetEntries(
            pole_id=puid, user_id=user.sub, label=body.label, montant=body.montant,
            type=body.type, categorie=body.categorie or "", date=when,
        )
        s.add(e)
        await s.commit()
        await s.refresh(e)
    return JSONResponse(status_code=201, content=budget_entry(e))


@router.delete("/budget/{eid}", dependencies=[Depends(get_current_user)])
async def delete_entry(eid: str, user: UserContext = Depends(get_current_user)):
    euid = _uuid(eid)
    async with SessionLocal() as s:
        if euid:
            await s.execute(sa_delete(BudgetEntries).where(and_(
                BudgetEntries.id == euid, BudgetEntries.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
