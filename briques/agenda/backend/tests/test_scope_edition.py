"""Portée d'édition (S175) : `scope=all|this` sur PATCH/DELETE /events/{id}.

`scope=this` sur un event récurrent isole l'occurrence (EXDATE au DELETE,
event-override au PATCH) sans toucher au maître ; `scope=all` (défaut) garde
le comportement historique (modifie/supprime le maître = toute la série)."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException

from models.orm import Calendar, Event
from models.schemas import EventUpdate
from routers import events as E
from services.occurrences import occurrences_calendrier

USER = {"sub": "perso"}


async def _serie(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c); await db.flush()
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    return c, m


@pytest.mark.asyncio
async def test_delete_scope_this_exclut_l_occurrence(db):
    c, m = await _serie(db)
    await E.delete_event(event_id=m.id, scope="this",
                         occurrence=datetime(2026, 6, 8, 9, 0), db=db, user=USER)
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert datetime(2026, 6, 8, 9, 0) not in {o.occurrence_start for o in occ}
    assert await db.get(Event, m.id) is not None            # maître toujours là


@pytest.mark.asyncio
async def test_patch_scope_this_cree_un_override(db):
    c, m = await _serie(db)
    await E.update_event(event_id=m.id, body=EventUpdate(title="Déplacé"),
                         scope="this", occurrence=datetime(2026, 6, 8, 9, 0),
                         db=db, user=USER)
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    depl = next(o for o in occ if o.occurrence_start == datetime(2026, 6, 8, 9, 0))
    assert depl.source.title == "Déplacé"


@pytest.mark.asyncio
async def test_patch_scope_this_occurrence_inexistante_422(db):
    c, m = await _serie(db)
    with pytest.raises(HTTPException) as ex:
        await E.update_event(event_id=m.id, body=EventUpdate(title="x"),
                             scope="this", occurrence=datetime(2026, 6, 3, 9, 0),  # un mercredi
                             db=db, user=USER)
    assert ex.value.status_code == 422


@pytest.mark.asyncio
async def test_delete_scope_all_supprime_la_serie(db):
    c, m = await _serie(db)
    await E.delete_event(event_id=m.id, scope="all", occurrence=None, db=db, user=USER)
    assert await db.get(Event, m.id) is None
