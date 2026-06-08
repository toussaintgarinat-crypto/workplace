"""Router OKR. Portage de routes/okr.ts (S131). Monté /api, protégé.

Objectives & Key Results par pôle. La progression d'un OKR = moyenne des KR
(min((actuelle/cible)*100, 100)), arrondie à l'entier (parité Math.round JS).
"""

from __future__ import annotations

import datetime
import math
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import KeyResults, Okrs
from app.serde import key_result, okr

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _progression(krs) -> int:
    if not krs:
        return 0
    acc = 0.0
    for kr in krs:
        cible = kr.valeur_cible or 0
        actuelle = kr.valeur_actuelle or 0
        acc += min((actuelle / cible) * 100, 100) if cible else 100
    # Math.round JS = arrondi half-up
    return math.floor(acc / len(krs) + 0.5)


@router.get("/poles/{pole_id}/okrs", dependencies=[Depends(get_current_user)])
async def list_okrs(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        okrs_rows = (await s.execute(
            select(Okrs).where(and_(Okrs.pole_id == puid, Okrs.user_id == user.sub))
            .order_by(desc(Okrs.created_at))
        )).scalars().all()
        out = []
        for o in okrs_rows:
            krs = (await s.execute(select(KeyResults).where(KeyResults.okr_id == o.id))).scalars().all()
            out.append({**okr(o), "keyResults": [key_result(k) for k in krs],
                        "progression": _progression(krs)})
    return out


class CreateOkr(BaseModel):
    titre: str = Field(min_length=1)
    description: str | None = None
    periode: str | None = None


@router.post("/poles/{pole_id}/okrs", dependencies=[Depends(get_current_user)])
async def create_okr(pole_id: str, body: CreateOkr, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    extra = {}
    if body.description is not None:
        extra["description"] = body.description
    if body.periode is not None:
        extra["periode"] = body.periode
    async with SessionLocal() as s:
        o = Okrs(titre=body.titre, pole_id=puid, user_id=user.sub, **extra)
        s.add(o)
        await s.commit()
        await s.refresh(o)
    return JSONResponse(status_code=201, content={**okr(o), "keyResults": [], "progression": 0})


class UpdateOkr(BaseModel):
    titre: str | None = None
    description: str | None = None
    statut: str | None = None
    periode: str | None = None


@router.patch("/okrs/{oid}", dependencies=[Depends(get_current_user)])
async def update_okr(oid: str, body: UpdateOkr, user: UserContext = Depends(get_current_user)):
    ouid = _uuid(oid)
    cols = body.model_dump(exclude_unset=True)
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        o = None
        if ouid:
            await s.execute(
                update(Okrs).where(and_(Okrs.id == ouid, Okrs.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            o = (await s.execute(
                select(Okrs).where(and_(Okrs.id == ouid, Okrs.user_id == user.sub))
            )).scalar_one_or_none()
    return okr(o) if o else None


@router.delete("/okrs/{oid}", dependencies=[Depends(get_current_user)])
async def delete_okr(oid: str, user: UserContext = Depends(get_current_user)):
    ouid = _uuid(oid)
    async with SessionLocal() as s:
        if ouid:
            await s.execute(sa_delete(Okrs).where(and_(Okrs.id == ouid, Okrs.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


class CreateKr(BaseModel):
    titre: str = Field(min_length=1)
    valeurCible: float | None = None
    valeurActuelle: float | None = None
    unite: str | None = None


_KR_COLMAP = {"titre": "titre", "valeurCible": "valeur_cible",
              "valeurActuelle": "valeur_actuelle", "unite": "unite"}


@router.post("/okrs/{okr_id}/kr", dependencies=[Depends(get_current_user)])
async def add_kr(okr_id: str, body: CreateKr, user: UserContext = Depends(get_current_user)):
    ouid = _uuid(okr_id)
    raw = body.model_dump(exclude_unset=True)
    cols = {_KR_COLMAP[k]: v for k, v in raw.items() if k in _KR_COLMAP}
    async with SessionLocal() as s:
        kr = KeyResults(okr_id=ouid, **cols)
        s.add(kr)
        await s.commit()
        await s.refresh(kr)
    return JSONResponse(status_code=201, content=key_result(kr))


class UpdateKr(BaseModel):
    valeurActuelle: float | None = None
    titre: str | None = None
    valeurCible: float | None = None


@router.patch("/kr/{kid}", dependencies=[Depends(get_current_user)])
async def update_kr(kid: str, body: UpdateKr, user: UserContext = Depends(get_current_user)):
    kuid = _uuid(kid)
    raw = body.model_dump(exclude_unset=True)
    cols = {_KR_COLMAP[k]: v for k, v in raw.items() if k in _KR_COLMAP}
    async with SessionLocal() as s:
        kr = None
        if kuid:
            if cols:
                await s.execute(update(KeyResults).where(KeyResults.id == kuid).values(**cols))
                await s.commit()
            kr = (await s.execute(select(KeyResults).where(KeyResults.id == kuid))).scalar_one_or_none()
    return key_result(kr) if kr else None


@router.delete("/kr/{kid}", dependencies=[Depends(get_current_user)])
async def delete_kr(kid: str, user: UserContext = Depends(get_current_user)):
    kuid = _uuid(kid)
    async with SessionLocal() as s:
        if kuid:
            await s.execute(sa_delete(KeyResults).where(KeyResults.id == kuid))
            await s.commit()
    return {"ok": True}
