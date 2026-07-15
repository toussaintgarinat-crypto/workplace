"""S174 — journal d'activité : écriture (snapshot du nom) + lecture antéchronologique."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from models.orm import Calendar, Event
from routers import activity as A
from services import journal, profils


async def _event(db) -> Event:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


@pytest.mark.asyncio
async def test_consigner_capture_le_nom(db):
    evt = await _event(db)
    await profils.upsert(db, "marina", "Marina")
    await journal.consigner(db, evt.id, "marina", "rsvp", {"statut": "accepted"})
    await db.commit()
    out = await A.list_activity(evt.id, db=db, user={"sub": "perso"})
    assert len(out) == 1
    assert out[0].user_nom == "Marina" and out[0].action == "rsvp"
    assert out[0].details == {"statut": "accepted"}


@pytest.mark.asyncio
async def test_consigner_nom_defaut_si_inconnu(db):
    evt = await _event(db)
    await journal.consigner(db, evt.id, "perso", "event_created")
    await db.commit()
    out = await A.list_activity(evt.id, db=db, user={"sub": "perso"})
    assert out[0].user_nom == "Toi"  # défaut propriétaire local


@pytest.mark.asyncio
async def test_list_activity_anterochronologique(db):
    evt = await _event(db)
    await journal.consigner(db, evt.id, "perso", "event_created")
    await journal.consigner(db, evt.id, "perso", "event_updated", {"champ": "start_at"})
    await db.commit()
    out = await A.list_activity(evt.id, db=db, user={"sub": "perso"})
    assert [a.action for a in out] == ["event_updated", "event_created"]  # plus récent d'abord
