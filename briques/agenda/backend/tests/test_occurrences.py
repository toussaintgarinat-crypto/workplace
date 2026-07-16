from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from services.occurrences import occurrences_calendrier, occurrence_en_dict


async def _cal(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c); await db.flush()
    return c


@pytest.mark.asyncio
async def test_maitre_recurrent_avant_fenetre_est_deplie(db):
    # Piège fenêtre : maître démarré en JANVIER, on regarde JUIN → doit apparaître.
    c = await _cal(db)
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 1, 5, 9, 0), end_at=datetime(2026, 1, 5, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert len(occ) >= 4 and all(o.start.month == 6 for o in occ)


@pytest.mark.asyncio
async def test_override_et_exdate_appliques(db):
    c = await _cal(db)
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[datetime(2026, 6, 15, 9, 0).isoformat()])
    db.add(m); await db.flush()
    ov = Event(calendar_id=c.id, title="Déplacé", created_by="perso", rappels=[],
               start_at=datetime(2026, 6, 8, 14, 0), end_at=datetime(2026, 6, 8, 15, 0),
               recurrence_parent_id=m.id, recurrence_date=datetime(2026, 6, 8, 9, 0))
    db.add(ov); await db.commit()
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    starts = {o.occurrence_start for o in occ}
    assert datetime(2026, 6, 15, 9, 0) not in starts          # exdate sautée
    depl = next(o for o in occ if o.occurrence_start == datetime(2026, 6, 8, 9, 0))
    assert depl.source.title == "Déplacé"                     # override substitué
    d = occurrence_en_dict(depl)
    assert d["title"] == "Déplacé" and d["recurrent"] is True
