"""CRUD événements — /calendars/{cal_id}/events et /events/{event_id}."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event
from models.schemas import EventOut, EventUpdate
from services.pubsub import publish_change
from utils.access import require_calendar_access

router = APIRouter(tags=["events"])
logger = logging.getLogger(__name__)


@router.get("/calendars/{cal_id}/events", response_model=list[EventOut])
async def list_events(
    cal_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="viewer")
    filters = [Event.calendar_id == cal_id]
    if start:
        filters.append(Event.end_at >= start)
    if end:
        filters.append(Event.start_at <= end)
    result = await db.execute(
        select(Event).where(and_(*filters)).order_by(Event.start_at)
    )
    return result.scalars().all()


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
    evt = Event(**data, calendar_id=cal_id, created_by=user["sub"])
    db.add(evt)
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


@router.patch("/events/{event_id}", response_model=EventOut)
async def update_event(
    event_id: str,
    body: EventUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(evt, k, v)
    await db.commit()
    await db.refresh(evt)
    out = EventOut.model_validate(evt)
    await publish_change(evt.calendar_id, "event.updated", out.model_dump(mode="json"))
    return evt


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    cal_id = evt.calendar_id
    await db.delete(evt)
    await db.commit()
    await publish_change(cal_id, "event.deleted", {"id": event_id})
