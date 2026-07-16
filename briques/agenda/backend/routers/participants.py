"""Participants à un événement — /events/{event_id}/participants."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, EventParticipant
from models.schemas import ParticipantAdd, ParticipantOut, ParticipantStatusUpdate
from services.journal import consigner
from utils.access import require_calendar_access

router = APIRouter(tags=["participants"])


async def _get_event(event_id: str, db: AsyncSession) -> Event:
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return evt


@router.get("/events/{event_id}/participants", response_model=list[ParticipantOut])
async def list_participants(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _get_event(event_id, db)
    result = await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == event_id)
    )
    return result.scalars().all()


@router.post("/events/{event_id}/participants", response_model=ParticipantOut, status_code=status.HTTP_201_CREATED)
async def add_participant(
    event_id: str,
    body: ParticipantAdd,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _get_event(event_id, db)
    existing = await db.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == body.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Participant already added")
    p = EventParticipant(event_id=event_id, user_id=body.user_id, status=body.status)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.patch("/events/{event_id}/participants/{participant_user_id}", response_model=ParticipantOut)
async def update_participant_status(
    event_id: str,
    participant_user_id: str,
    body: ParticipantStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await _get_event(event_id, db)
    # On édite sa propre ligne (RSVP / rappels perso) → viewer suffit.
    # On édite la ligne de quelqu'un d'autre → il faut editor.
    min_role = "viewer" if participant_user_id == user["sub"] else "editor"
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role=min_role)
    result = await db.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == participant_user_id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    fournis = body.model_dump(exclude_unset=True)
    if "status" in fournis and fournis["status"] is not None:
        p.status = fournis["status"]
        p.responded_at = datetime.now(timezone.utc)
        await consigner(db, event_id, user["sub"], "rsvp", {"statut": p.status})
    if "rappels" in fournis:  # présent (même []) = réglage explicite ; absent = inchangé
        p.rappels = fournis["rappels"]
    await db.commit()
    await db.refresh(p)
    return p


@router.post("/events/{event_id}/participants/all", response_model=list[ParticipantOut], status_code=status.HTTP_201_CREATED)
async def add_all_members(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Ajoute d'un tap tous les membres du calendrier de l'event comme participants
    (status=pending, rappels hérités). Idempotent : n'ajoute que les manquants."""
    from services.membres import membres_du_calendrier
    evt = await _get_event(event_id, db)
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    membres = await membres_du_calendrier(db, evt.calendar_id)
    existants = set((await db.execute(
        select(EventParticipant.user_id).where(EventParticipant.event_id == event_id)
    )).scalars().all())
    for uid in membres - existants:
        db.add(EventParticipant(event_id=event_id, user_id=uid, status="pending"))
    await db.commit()
    result = await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == event_id)
    )
    return result.scalars().all()


@router.delete("/events/{event_id}/participants/{participant_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    event_id: str,
    participant_user_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == participant_user_id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    await db.delete(p)
    await db.commit()
