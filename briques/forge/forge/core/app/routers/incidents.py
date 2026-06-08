"""Router incidents. Portage de routes/incidents.ts (S135).

Monté /api, protégé. Incidents rattachés à un pôle. ``resolvedAt`` est posé
automatiquement quand le statut passe à ``resolu``.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Incidents
from app.serde import incident

router = APIRouter()

_SEVERITES = {"critique", "haute", "moyenne", "basse"}
_STATUTS = {"ouvert", "en_cours", "resolu", "ferme"}


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/incidents", dependencies=[Depends(get_current_user)])
async def list_incidents(pole_id: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Incidents).where(and_(
                Incidents.pole_id == u, Incidents.user_id == user.sub,
            )).order_by(desc(Incidents.created_at))
        )).scalars().all() if u else []
    return [incident(r) for r in rows]


class CreateIncident(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    description: str | None = None
    severite: str | None = None


@router.post("/poles/{pole_id}/incidents", dependencies=[Depends(get_current_user)])
async def create_incident(pole_id: str, body: CreateIncident, response: Response,
                          user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        row = Incidents(
            pole_id=_uuid(pole_id), user_id=user.sub,
            titre=body.titre, description=body.description or "",
            severite=body.severite if body.severite in _SEVERITES else "moyenne",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return incident(row)


@router.patch("/incidents/{iid}", dependencies=[Depends(get_current_user)])
async def update_incident(iid: str, body: dict, user: UserContext = Depends(get_current_user)):
    u = _uuid(iid)
    updates: dict = {"updated_at": func.now()}
    if body.get("titre"):
        updates["titre"] = body["titre"]
    if body.get("description") is not None:
        updates["description"] = body["description"]
    if body.get("severite") in _SEVERITES:
        updates["severite"] = body["severite"]
    if body.get("statut") in _STATUTS:
        updates["statut"] = body["statut"]
        if body["statut"] == "resolu":
            updates["resolved_at"] = func.now()
    async with SessionLocal() as s:
        if u:
            await s.execute(
                update(Incidents).where(and_(
                    Incidents.id == u, Incidents.user_id == user.sub,
                )).values(**updates)
            )
            await s.commit()
        row = (await s.execute(
            select(Incidents).where(and_(
                Incidents.id == u, Incidents.user_id == user.sub,
            ))
        )).scalar_one_or_none() if u else None
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return incident(row)


@router.delete("/incidents/{iid}", dependencies=[Depends(get_current_user)])
async def delete_incident(iid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(iid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(Incidents).where(and_(
                Incidents.id == u, Incidents.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}
