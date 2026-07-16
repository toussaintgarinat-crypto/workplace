"""Portée d'édition (S175) : `scope=all|this` sur PATCH/DELETE /events/{id}.

`scope=this` sur un event récurrent isole l'occurrence (EXDATE au DELETE,
event-override au PATCH) sans toucher au maître ; `scope=all` (défaut) garde
le comportement historique (modifie/supprime le maître = toute la série)."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.orm import Calendar, Event
from models.schemas import EventUpdate
from routers import events as E
from services.occurrences import creer_ou_maj_override, occurrences_calendrier

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


# ── Correctifs revue (fix 1/2/3) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_scope_invalide_422_ne_modifie_pas_la_serie(db):
    """Une faute de frappe sur `scope` (ex. "thsi") ne doit JAMAIS retomber sur le
    comportement scope=all : elle doit être rejetée avant toute écriture."""
    c, m = await _serie(db)
    with pytest.raises(HTTPException) as ex:
        await E.update_event(event_id=m.id, body=EventUpdate(title="Oups"),
                             scope="thsi", occurrence=None, db=db, user=USER)
    assert ex.value.status_code == 422
    assert (await db.get(Event, m.id)).title == "Hebdo"  # maître intact


@pytest.mark.asyncio
async def test_delete_scope_invalide_422_ne_supprime_pas_la_serie(db):
    c, m = await _serie(db)
    with pytest.raises(HTTPException) as ex:
        await E.delete_event(event_id=m.id, scope="thsi", occurrence=None, db=db, user=USER)
    assert ex.value.status_code == 422
    assert await db.get(Event, m.id) is not None  # série toujours là


@pytest.mark.asyncio
async def test_delete_scope_this_supprime_l_override_orphelin(db):
    """Un override créé par PATCH scope=this sur une occurrence, puis exclue par
    DELETE scope=this sur la MÊME occurrence, ne doit pas laisser de ligne fantôme."""
    c, m = await _serie(db)
    occ_dt = datetime(2026, 6, 8, 9, 0)
    await E.update_event(event_id=m.id, body=EventUpdate(title="Déplacé"),
                         scope="this", occurrence=occ_dt, db=db, user=USER)
    await E.delete_event(event_id=m.id, scope="this", occurrence=occ_dt, db=db, user=USER)
    reste = (await db.execute(
        select(Event).where(Event.recurrence_parent_id == m.id, Event.recurrence_date == occ_dt)
    )).scalar_one_or_none()
    assert reste is None
    occs = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert occ_dt not in {o.occurrence_start for o in occs}


@pytest.mark.asyncio
async def test_creer_ou_maj_override_deux_fois_une_seule_ligne(db):
    """Deux appels sur la même occurrence = MAJ de la même ligne (contrainte unique
    recurrence_parent_id+recurrence_date), jamais deux overrides."""
    c, m = await _serie(db)
    occ_dt = datetime(2026, 6, 8, 9, 0)
    await creer_ou_maj_override(db, m, occ_dt, {"title": "Premier titre"})
    await creer_ou_maj_override(db, m, occ_dt, {"title": "Titre final"})
    lignes = (await db.execute(
        select(Event).where(Event.recurrence_parent_id == m.id, Event.recurrence_date == occ_dt)
    )).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].title == "Titre final"
