"""Router contrats. Portage de routes/contrats.ts (S131). Monté /api, protégé.

Contrats scopés par pôle + utilisateur, avec signature (statut 'signe').
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
from app.models import Contrats
from app.serde import contrat

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/contrats", dependencies=[Depends(get_current_user)])
async def list_contrats(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Contrats).where(and_(Contrats.pole_id == puid, Contrats.user_id == user.sub))
            .order_by(desc(Contrats.created_at))
        )).scalars().all()
    return [contrat(x) for x in rows]


class CreateContrat(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    type: str | None = None
    parties: str | None = None
    contenu: str | None = None
    valeur: int | None = None
    dateDebut: str | None = None
    dateFin: str | None = None
    notes: str | None = None


@router.post("/poles/{pole_id}/contrats", dependencies=[Depends(get_current_user)])
async def create_contrat(pole_id: str, body: CreateContrat, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        c = Contrats(
            pole_id=puid, user_id=user.sub, titre=body.titre,
            type=body.type or "Autre", parties=body.parties or "",
            contenu=body.contenu or "", valeur=body.valeur or 0,
            date_debut=body.dateDebut or "", date_fin=body.dateFin or "",
            notes=body.notes or "",
        )
        s.add(c)
        await s.commit()
        await s.refresh(c)
    return JSONResponse(status_code=201, content=contrat(c))


class UpdateContrat(BaseModel):
    titre: str | None = None
    type: str | None = None
    statut: str | None = None
    parties: str | None = None
    contenu: str | None = None
    valeur: int | None = None
    dateDebut: str | None = None
    dateFin: str | None = None
    notes: str | None = None


_PATCH_COLMAP = {
    "titre": "titre", "type": "type", "statut": "statut", "parties": "parties",
    "contenu": "contenu", "valeur": "valeur", "dateDebut": "date_debut",
    "dateFin": "date_fin", "notes": "notes",
}


@router.patch("/contrats/{cid}", dependencies=[Depends(get_current_user)])
async def update_contrat(cid: str, body: UpdateContrat, user: UserContext = Depends(get_current_user)):
    cuid = _uuid(cid)
    raw = body.model_dump(exclude_unset=True)
    cols = {_PATCH_COLMAP[k]: v for k, v in raw.items() if k in _PATCH_COLMAP}
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        c = None
        if cuid:
            await s.execute(
                update(Contrats).where(and_(Contrats.id == cuid, Contrats.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            c = (await s.execute(
                select(Contrats).where(and_(Contrats.id == cuid, Contrats.user_id == user.sub))
            )).scalar_one_or_none()
        if c is None:
            raise HTTPException(status_code=404, detail="Not found")
    return contrat(c)


class SignBody(BaseModel):
    signePar: str = Field(min_length=1)


@router.post("/contrats/{cid}/signer", dependencies=[Depends(get_current_user)])
async def sign_contrat(cid: str, body: SignBody, user: UserContext = Depends(get_current_user)):
    cuid = _uuid(cid)
    now = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        c = None
        if cuid:
            await s.execute(
                update(Contrats).where(and_(Contrats.id == cuid, Contrats.user_id == user.sub))
                .values(statut="signe", signe_par=body.signePar, signe_at=now, updated_at=now)
            )
            await s.commit()
            c = (await s.execute(
                select(Contrats).where(and_(Contrats.id == cuid, Contrats.user_id == user.sub))
            )).scalar_one_or_none()
        if c is None:
            raise HTTPException(status_code=404, detail="Not found")
    return contrat(c)


@router.delete("/contrats/{cid}", dependencies=[Depends(get_current_user)])
async def delete_contrat(cid: str, user: UserContext = Depends(get_current_user)):
    cuid = _uuid(cid)
    async with SessionLocal() as s:
        if cuid:
            await s.execute(sa_delete(Contrats).where(and_(Contrats.id == cuid, Contrats.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
