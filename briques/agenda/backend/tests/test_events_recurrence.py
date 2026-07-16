"""Récurrence — test du dépliage de series dans GET /calendars/{cal_id}/events."""

from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from routers import events as E

USER = {"sub": "perso"}


async def _cal(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c)
    await db.flush()
    return c


@pytest.mark.asyncio
async def test_list_events_deplie_la_serie(db):
    c = await _cal(db)
    m = Event(
        calendar_id=c.id,
        title="Hebdo",
        created_by="perso",
        rappels=[],
        start_at=datetime(2026, 6, 1, 9, 0),
        end_at=datetime(2026, 6, 1, 10, 0),
        recurrence_rule="FREQ=WEEKLY",
        exdates=[],
    )
    db.add(m)
    await db.commit()
    res = await E.list_events(
        cal_id=c.id,
        start=datetime(2026, 6, 1),
        end=datetime(2026, 6, 30),
        db=db,
        user=USER,
    )
    assert len(res) == 5  # 5 lundis de juin
    assert all(r["recurrent"] for r in res)
    assert res[0]["id"] == m.id  # id du maître conservé
    assert res[0]["occurrence_start"] != res[1]["occurrence_start"]
