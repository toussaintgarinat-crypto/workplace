# tests/test_recurrence_orm.py
from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from models.schemas import EventCreate, EventUpdate


@pytest.mark.asyncio
async def test_colonnes_recurrence_persistees(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c)
    await db.flush()
    maitre = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
                   start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
                   recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(maitre)
    await db.flush()
    ov = Event(calendar_id=c.id, title="Hebdo (déplacé)", created_by="perso", rappels=[],
               start_at=datetime(2026, 6, 8, 14, 0), end_at=datetime(2026, 6, 8, 15, 0),
               recurrence_parent_id=maitre.id, recurrence_date=datetime(2026, 6, 8, 9, 0))
    db.add(ov)
    await db.flush()
    assert ov.recurrence_parent_id == maitre.id
    assert maitre.exdates == []


def test_eventcreate_valide_rrule():
    ec = EventCreate(calendar_id="c1", title="x",
                     start_at=datetime(2026, 6, 1, 9, 0),
                     end_at=datetime(2026, 6, 1, 10, 0),
                     recurrence_rule="RRULE:FREQ=WEEKLY;BYDAY=MO")
    assert ec.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO"  # préfixe strippé


def test_eventcreate_rejette_rrule_invalide():
    with pytest.raises(ValueError):
        EventCreate(calendar_id="c1", title="x",
                    start_at=datetime(2026, 6, 1, 9, 0),
                    end_at=datetime(2026, 6, 1, 10, 0),
                    recurrence_rule="FREQ=MINUTELY")
