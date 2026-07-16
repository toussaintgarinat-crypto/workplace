"""Surface `/service` — récurrence (S175, Task 8) : `recurrence` en création,
`scope`/`occurrence` en édition/suppression. Mêmes patrons que `test_events_recurrence.py`
(Task 7), mais via les fonctions `routers/service.py` (dialecte outils LLM)."""

from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from routers import service as S
from services.occurrences import occurrences_calendrier

USER = {"sub": "perso", "service_call": True}


@pytest.mark.asyncio
async def test_service_cree_evenement_recurrent(db):
    c = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(c); await db.commit()
    corps = S.EvenementServiceIn(titre="Sport", debut=datetime(2026, 6, 1, 18, 0),
                                 fin=datetime(2026, 6, 1, 19, 0),
                                 recurrence="FREQ=WEEKLY;BYDAY=MO,WE")
    evt = await S.service_creer_evenement(corps=corps, db=db, user=USER)
    assert evt.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO,WE"


@pytest.mark.asyncio
async def test_service_delete_scope_this(db):
    c = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(c); await db.flush()
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    await S.service_supprimer_evenement(event_id=m.id, scope="this",
                                        occurrence=datetime(2026, 6, 8, 9, 0), db=db, user=USER)
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert datetime(2026, 6, 8, 9, 0) not in {o.occurrence_start for o in occ}


@pytest.mark.asyncio
async def test_service_patch_scope_this_cree_override(db):
    c = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(c); await db.flush()
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    out = await S.service_modifier_evenement(
        event_id=m.id, corps=S.EvenementPatchIn(titre="Hebdo (exception)"), scope="this",
        occurrence=datetime(2026, 6, 8, 9, 0), db=db, user=USER)
    assert out["title"] == "Hebdo (exception)"
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    titres = {o.occurrence_start: o.source.title for o in occ}
    assert titres[datetime(2026, 6, 8, 9, 0)] == "Hebdo (exception)"
    assert titres[datetime(2026, 6, 1, 9, 0)] == "Hebdo"


@pytest.mark.asyncio
async def test_service_patch_scope_invalide_422(db):
    from fastapi import HTTPException
    c = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(c); await db.flush()
    e = Event(calendar_id=c.id, title="RDV", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0))
    db.add(e); await db.commit()
    with pytest.raises(HTTPException) as exc:
        await S.service_modifier_evenement(event_id=e.id, corps=S.EvenementPatchIn(titre="x"),
                                           scope="bogus", db=db, user=USER)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_service_creation_rrule_invalide_rejetee(db):
    with pytest.raises(ValueError):
        S.EvenementServiceIn(titre="Sport", debut=datetime(2026, 6, 1, 18, 0),
                             fin=datetime(2026, 6, 1, 19, 0), recurrence="pas de FREQ ici")
