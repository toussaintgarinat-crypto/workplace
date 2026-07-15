"""S174 — recipients hybrides : auto-participant, inviter tous, rappels perso."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, CalendarMember, Event, EventParticipant
from models.schemas import EventUpdate, ParticipantStatusUpdate
from routers import events as EV
from routers import participants as P
from services.membres import membres_du_calendrier

OWNER = {"sub": "perso"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_creation_event_ajoute_le_createur(db):
    cal = await _cal(db)
    debut = datetime(2030, 1, 1, 14, 0)
    evt = await EV.create_event(
        cal.id,
        EventUpdate(title="RDV", start_at=debut, end_at=debut + timedelta(hours=1)),
        db=db, user=OWNER,
    )
    parts = (await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == evt.id)
    )).scalars().all()
    assert [(p.user_id, p.status) for p in parts] == [("perso", "accepted")]


@pytest.mark.asyncio
async def test_membres_du_calendrier(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina", role="editor"))
    await db.commit()
    assert await membres_du_calendrier(db, cal.id) == {"perso", "marina"}


@pytest.mark.asyncio
async def test_inviter_tous_les_membres(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina", role="editor"))
    await db.commit()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Diner", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    parts = await P.add_all_members(evt.id, db=db, user=OWNER)
    users = {p.user_id for p in parts}
    assert users == {"perso", "marina"}
    # Idempotent : 2ᵉ appel ne duplique pas.
    parts2 = await P.add_all_members(evt.id, db=db, user=OWNER)
    assert {p.user_id for p in parts2} == {"perso", "marina"}


@pytest.mark.asyncio
async def test_patch_rappels_perso(db):
    cal = await _cal(db)
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.flush()  # matérialise evt.id avant de l'utiliser comme FK
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending"))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(rappels=[60, 1440]), db=db, user=OWNER)
    assert out.rappels == [60, 1440]
    # rappels: [] efface (aucun) ; distinct de None (hérite).
    out2 = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(rappels=[]), db=db, user=OWNER)
    assert out2.rappels == []


@pytest.mark.asyncio
async def test_patch_status_seul_inchange_rappels(db):
    cal = await _cal(db)
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.flush()  # matérialise evt.id avant de l'utiliser comme FK
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending", rappels=[30]))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(status="accepted"), db=db, user=OWNER)
    assert out.status == "accepted" and out.rappels == [30]  # rappels non touchés
