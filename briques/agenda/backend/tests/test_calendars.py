"""CRUD calendriers + contrôle d'accès par rôle (owner/editor/viewer).

On appelle les fonctions de route directement avec la session de test, comme
test_labels.py / test_timetree_routes.py — pas de TestClient, pas de JWT.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import Calendar, CalendarMember
from models.schemas import CalendarCreate, CalendarUpdate
from routers import calendars as R

OWNER = {"sub": "perso"}
AUTRE = {"sub": "marina-sub"}


async def _cal(db, user_id="perso", name="Perso") -> Calendar:
    cal = Calendar(user_id=user_id, name=name, is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_create_calendar_devient_owner(db):
    out = await R.create_calendar(CalendarCreate(name="Perso"), db=db, user=OWNER)
    assert out.name == "Perso"
    assert out.role == "owner"


@pytest.mark.asyncio
async def test_list_calendars_separe_owned_et_membre(db):
    cal_owned = await _cal(db, user_id="perso", name="Perso")
    cal_partage = await _cal(db, user_id="perso", name="Famille")
    db.add(CalendarMember(calendar_id=cal_partage.id, user_id="marina-sub", role="editor"))
    await db.commit()

    lst_owner = await R.list_calendars(db=db, user=OWNER)
    assert {c.name: c.role for c in lst_owner} == {"Perso": "owner", "Famille": "owner"}

    lst_marina = await R.list_calendars(db=db, user=AUTRE)
    assert {c.name: c.role for c in lst_marina} == {"Famille": "editor"}


@pytest.mark.asyncio
async def test_get_calendar_refuse_sans_acces(db):
    cal = await _cal(db)
    with pytest.raises(HTTPException) as exc:
        await R.get_calendar(cal.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_calendar_exige_editor_minimum(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina-sub", role="viewer"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.update_calendar(cal.id, CalendarUpdate(name="Nouveau nom"), db=db, user=AUTRE)
    assert exc.value.status_code == 404

    out = await R.update_calendar(cal.id, CalendarUpdate(name="Nouveau nom"), db=db, user=OWNER)
    assert out.name == "Nouveau nom"


@pytest.mark.asyncio
async def test_delete_calendar_exige_owner(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina-sub", role="editor"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.delete_calendar(cal.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404

    await R.delete_calendar(cal.id, db=db, user=OWNER)
    with pytest.raises(HTTPException):
        await R.get_calendar(cal.id, db=db, user=OWNER)
