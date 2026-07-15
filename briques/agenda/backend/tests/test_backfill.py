"""S174 — backfill : chaque event legacy sans participant reçoit un participant créateur."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, Event, EventParticipant
from services.backfill import creer_participants_createurs


async def _event(db, created_by="perso") -> Event:
    cal = Calendar(user_id=created_by, name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Legacy", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by=created_by, rappels=[10])
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


@pytest.mark.asyncio
async def test_backfill_cree_le_createur(db):
    evt = await _event(db)
    n = await creer_participants_createurs(db)
    assert n == 1
    p = (await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == evt.id)
    )).scalar_one()
    assert p.user_id == "perso" and p.status == "accepted" and p.rappels is None


@pytest.mark.asyncio
async def test_backfill_idempotent(db):
    await _event(db)
    assert await creer_participants_createurs(db) == 1
    assert await creer_participants_createurs(db) == 0  # 2ᵉ passage : rien à faire


@pytest.mark.asyncio
async def test_backfill_ignore_event_deja_pourvu(db):
    evt = await _event(db)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="accepted"))
    await db.commit()
    assert await creer_participants_createurs(db) == 0  # a déjà un participant
