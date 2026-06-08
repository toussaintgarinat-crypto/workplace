"""Router calendar (agenda interne). Portage de routes/calendar.ts (S135).

Monté /api, protégé. Événements d'agenda par utilisateur, scopés org (header
X-Org-ID), filtrables par fenêtre [debut, fin] sur ``dateDebut``.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import AgendaEvents
from app.serde import agenda_event

router = APIRouter()


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _parse_dt(v: str | None) -> datetime.datetime | None:
    """ISO 8601 → datetime naïf UTC (équivalent de ``new Date(str)`` côté Bun)."""
    if not v:
        return None
    try:
        dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


@router.get("/calendar/events")
async def list_events(request: Request,
                      org_id: str = Depends(require_org),
                      user: UserContext = Depends(get_current_user)):
    debut = _parse_dt(request.query_params.get("debut"))
    fin = _parse_dt(request.query_params.get("fin"))
    where = [AgendaEvents.user_id == user.sub, AgendaEvents.org_id == org_id]
    if debut is not None:
        where.append(AgendaEvents.date_debut >= debut)
    if fin is not None:
        where.append(AgendaEvents.date_debut <= fin)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AgendaEvents).where(and_(*where)).order_by(desc(AgendaEvents.date_debut))
        )).scalars().all()
    return [agenda_event(r) for r in rows]


class CreateEvent(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    description: str | None = None
    dateDebut: str
    dateFin: str | None = None
    pole: str | None = None


@router.post("/calendar/events")
async def create_event(body: CreateEvent, response: Response,
                       org_id: str = Depends(require_org),
                       user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        row = AgendaEvents(
            user_id=user.sub, org_id=org_id,
            titre=body.titre, description=body.description or "",
            date_debut=_parse_dt(body.dateDebut),
            date_fin=_parse_dt(body.dateFin),
            pole=body.pole or "",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return agenda_event(row)


@router.patch("/calendar/events/{eid}", dependencies=[Depends(get_current_user)])
async def update_event(eid: str, body: dict, user: UserContext = Depends(get_current_user)):
    u = _uuid(eid)
    colmap = {"titre": "titre", "description": "description", "pole": "pole"}
    updates = {colmap[k]: v for k, v in body.items() if k in colmap}
    if body.get("dateDebut"):
        updates["date_debut"] = _parse_dt(body["dateDebut"])
    if body.get("dateFin"):
        updates["date_fin"] = _parse_dt(body["dateFin"])
    async with SessionLocal() as s:
        if u and updates:
            await s.execute(
                update(AgendaEvents).where(and_(
                    AgendaEvents.id == u, AgendaEvents.user_id == user.sub,
                )).values(**updates)
            )
            await s.commit()
        row = (await s.execute(
            select(AgendaEvents).where(and_(
                AgendaEvents.id == u, AgendaEvents.user_id == user.sub,
            ))
        )).scalar_one_or_none() if u else None
    return agenda_event(row) if row else None


@router.delete("/calendar/events/{eid}", dependencies=[Depends(get_current_user)])
async def delete_event(eid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(eid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(AgendaEvents).where(and_(
                AgendaEvents.id == u, AgendaEvents.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}
