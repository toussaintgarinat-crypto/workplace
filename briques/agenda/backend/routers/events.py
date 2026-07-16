"""CRUD événements — /calendars/{cal_id}/events et /events/{event_id}."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event
from models.schemas import EventOut, EventUpdate
from services.journal import consigner
from services.occurrences import (
    creer_ou_maj_override,
    exclure_occurrence,
    occurrence_en_dict,
    occurrence_naive,
    occurrence_valide,
    occurrences_calendrier,
)
from services.pubsub import publish_change
from services.recurrence import Occurrence
from utils.access import require_calendar_access

router = APIRouter(tags=["events"])
logger = logging.getLogger(__name__)


@router.get("/calendars/{cal_id}/events", response_model=None)
async def list_events(
    cal_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="viewer")
    occ = await occurrences_calendrier(db, cal_id, start, end)
    return [occurrence_en_dict(o) for o in occ]


@router.post("/calendars/{cal_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    cal_id: str,
    body: EventUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="editor")
    data = body.model_dump(exclude_none=True)
    if "title" not in data or "start_at" not in data or "end_at" not in data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title, start_at, end_at required")
    data.pop("calendar_id", None)
    if data.get("label_id") == "":  # chaîne vide = « aucune étiquette » explicite
        data["label_id"] = None
    evt = Event(**data, calendar_id=cal_id, created_by=user["sub"])
    db.add(evt)
    await db.flush()  # matérialise evt.id (default=_uuid appliqué au flush)
    from services.participants_auto import assurer_participant
    await assurer_participant(db, evt.id, user["sub"])
    await consigner(db, evt.id, user["sub"], "event_created", {"titre": evt.title})
    await db.commit()
    await db.refresh(evt)
    out = EventOut.model_validate(evt)
    await publish_change(cal_id, "event.created", out.model_dump(mode="json"))
    return evt


@router.get("/events/{event_id}", response_model=EventOut)
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="viewer")
    return evt


@router.patch("/events/{event_id}", response_model=None)
async def update_event(
    event_id: str,
    body: EventUpdate,
    scope: str = "all",
    occurrence: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    if scope not in ("all", "this"):
        raise HTTPException(status_code=422, detail="scope doit être 'all' ou 'this'")
    data = body.model_dump(exclude_unset=True)
    if data.get("label_id") == "":  # chaîne vide = « aucune étiquette » explicite
        data["label_id"] = None
    if scope == "this" and evt.recurrence_rule:
        # Portée « cette occurrence » : crée/maj un event-override, le maître (la
        # série) reste intact. L'occurrence doit être produite par la règle.
        occ = occurrence_naive(occurrence)
        if not occ or not occurrence_valide(evt, occ):
            raise HTTPException(status_code=422, detail="occurrence invalide")
        ov = await creer_ou_maj_override(db, evt, occ, data)
        await consigner(db, evt.id, user["sub"], "event_updated",
                        {"portee": "occurrence", "occurrence": occ.isoformat()})
        await db.commit()
        out = occurrence_en_dict(Occurrence(ov, ov.start_at, ov.end_at, occ, True))
        await publish_change(evt.calendar_id, "event.updated", out)
        return out
    for k, v in data.items():
        setattr(evt, k, v)
    await consigner(db, evt.id, user["sub"], "event_updated", {"champs": list(data.keys())})
    await db.commit()
    await db.refresh(evt)
    out = EventOut.model_validate(evt)
    # Modèle pydantic (pas le dict) : préserve l'accès par attribut pour les appelants
    # historiques (ex. tests appelant la route directement) ; sérialisable tel quel
    # côté HTTP (jsonable_encoder gère les BaseModel même sans response_model).
    await publish_change(evt.calendar_id, "event.updated", out.model_dump(mode="json"))
    return out


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    scope: str = "all",
    occurrence: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    if scope not in ("all", "this"):
        raise HTTPException(status_code=422, detail="scope doit être 'all' ou 'this'")
    cal_id = evt.calendar_id
    if scope == "this" and evt.recurrence_rule:
        # Portée « cette occurrence » : EXDATE sur le maître, la série survit.
        occ = occurrence_naive(occurrence)
        if not occ or not occurrence_valide(evt, occ):
            raise HTTPException(status_code=422, detail="occurrence invalide")
        await exclure_occurrence(db, evt, occ)
        await publish_change(cal_id, "event.updated", {"id": event_id})
        return
    await db.delete(evt)
    await db.commit()
    await publish_change(cal_id, "event.deleted", {"id": event_id})
