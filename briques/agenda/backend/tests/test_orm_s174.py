"""S174 — round-trip ORM : rappels par participant (3 états), profil, journal."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import (
    Calendar,
    Event,
    EventActivityLog,
    EventParticipant,
    UserProfile,
)


async def _event(db) -> Event:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso", rappels=[10])
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


@pytest.mark.asyncio
@pytest.mark.parametrize("valeur", [None, [], [60], [10, 1440]])
async def test_participant_rappels_persistent(db, valeur):
    evt = await _event(db)
    p = EventParticipant(event_id=evt.id, user_id="marina", status="pending", rappels=valeur)
    db.add(p)
    await db.commit()
    relu = (await db.execute(
        select(EventParticipant).where(EventParticipant.id == p.id)
    )).scalar_one()
    assert relu.rappels == valeur


@pytest.mark.asyncio
async def test_participant_rappels_defaut_none(db):
    evt = await _event(db)
    p = EventParticipant(event_id=evt.id, user_id="marina", status="pending")
    db.add(p)
    await db.commit()
    relu = (await db.execute(
        select(EventParticipant).where(EventParticipant.id == p.id)
    )).scalar_one()
    assert relu.rappels is None  # None = hérite (≠ [] = aucun)


@pytest.mark.asyncio
async def test_user_profile_round_trip(db):
    db.add(UserProfile(user_id="marina", display_name="Marina", avatar_color="#ec4899"))
    await db.commit()
    relu = (await db.execute(
        select(UserProfile).where(UserProfile.user_id == "marina")
    )).scalar_one()
    assert relu.display_name == "Marina" and relu.avatar_color == "#ec4899"


@pytest.mark.asyncio
async def test_activity_log_round_trip(db):
    evt = await _event(db)
    db.add(EventActivityLog(event_id=evt.id, user_id="perso", user_nom="Toi",
                            action="event_created", details={"titre": "RDV"}))
    await db.commit()
    relu = (await db.execute(
        select(EventActivityLog).where(EventActivityLog.event_id == evt.id)
    )).scalar_one()
    assert relu.action == "event_created" and relu.details == {"titre": "RDV"}
