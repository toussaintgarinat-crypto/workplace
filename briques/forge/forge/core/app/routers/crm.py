"""Router CRM. Portage de routes/crm.ts (S131). Monté /api, protégé.

Leads commerciaux scopés par pôle + utilisateur.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import CrmLeads
from app.serde import crm_lead

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/crm", dependencies=[Depends(get_current_user)])
async def list_leads(pole_id: str, statut: str | None = None, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    conds = [CrmLeads.pole_id == puid, CrmLeads.user_id == user.sub]
    if statut:
        conds.append(CrmLeads.statut == statut)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(CrmLeads).where(and_(*conds)).order_by(desc(CrmLeads.updated_at))
        )).scalars().all()
    return [crm_lead(x) for x in rows]


class CreateLead(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    email: str | None = None
    telephone: str | None = None
    entreprise: str | None = None
    statut: str | None = None
    valeur: int | None = None
    notes: str | None = None


@router.post("/poles/{pole_id}/crm", dependencies=[Depends(get_current_user)])
async def create_lead(pole_id: str, body: CreateLead, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        lead = CrmLeads(
            pole_id=puid, user_id=user.sub, nom=body.nom,
            email=body.email or "", telephone=body.telephone or "",
            entreprise=body.entreprise or "", statut=body.statut or "prospect",
            valeur=body.valeur or 0, notes=body.notes or "",
        )
        s.add(lead)
        await s.commit()
        await s.refresh(lead)
    return JSONResponse(status_code=201, content=crm_lead(lead))


class UpdateLead(BaseModel):
    nom: str | None = None
    email: str | None = None
    telephone: str | None = None
    entreprise: str | None = None
    statut: str | None = None
    valeur: int | None = None
    notes: str | None = None


@router.patch("/crm/{lead_id}", dependencies=[Depends(get_current_user)])
async def update_lead(lead_id: str, body: UpdateLead, user: UserContext = Depends(get_current_user)):
    luid = _uuid(lead_id)
    cols = body.model_dump(exclude_unset=True)
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        lead = None
        if luid:
            await s.execute(
                update(CrmLeads).where(and_(CrmLeads.id == luid, CrmLeads.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            lead = (await s.execute(
                select(CrmLeads).where(and_(CrmLeads.id == luid, CrmLeads.user_id == user.sub))
            )).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Not found")
    return crm_lead(lead)


@router.delete("/crm/{lead_id}", dependencies=[Depends(get_current_user)])
async def delete_lead(lead_id: str, user: UserContext = Depends(get_current_user)):
    luid = _uuid(lead_id)
    async with SessionLocal() as s:
        if luid:
            await s.execute(sa_delete(CrmLeads).where(and_(CrmLeads.id == luid, CrmLeads.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
