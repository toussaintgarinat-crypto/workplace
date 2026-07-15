"""Journal d'activité — GET /events/{id}/activity (S174). Lecture seule, antéchronologique."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, EventActivityLog
from models.schemas import ActivityLogOut

router = APIRouter(tags=["activity"])


@router.get("/events/{event_id}/activity", response_model=list[ActivityLogOut])
async def list_activity(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    rows = (await db.execute(
        select(EventActivityLog)
        .where(EventActivityLog.event_id == event_id)
        .order_by(EventActivityLog.created_at.desc())
    )).scalars().all()
    return rows
