"""S174 — /service/events porte les participants + leurs rappels effectifs."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from models.orm import Calendar, Event, EventParticipant
from services.agregation import evenements_agreges


@pytest.mark.asyncio
async def test_agregation_expose_participants_et_rappels(db):
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Diner", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso", rappels=[10])
    db.add(evt)
    await db.flush()
    db.add(EventParticipant(event_id=evt.id, user_id="perso", status="accepted", rappels=None))
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="accepted", rappels=[60]))
    await db.commit()

    evts = await evenements_agreges(db, "perso", None, None)
    e = next(x for x in evts if x["id"] == evt.id)
    parts = {p["user_id"]: p for p in e["participants"]}
    assert parts["perso"]["rappels_effectifs"] == [10]   # None → hérite [10]
    assert parts["marina"]["rappels_effectifs"] == [60]  # override
