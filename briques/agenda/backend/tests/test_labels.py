"""Étiquettes nommées (catégories) : CRUD des routes + rattachement à un événement +
suppression d'étiquette ⇒ `label_id` remis à NULL sans supprimer l'événement.

On appelle les fonctions de route directement avec la session de test (comme
test_timetree_routes.py), sans monter l'app FastAPI ni toucher au réseau.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, Event
from models.schemas import EventUpdate, LabelCreate, LabelUpdate
from routers import events as EV
from routers import labels as R

USER = {"sub": "perso"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_crud_etiquette(db):
    cal = await _cal(db)
    lab = await R.create_label(cal.id, LabelCreate(name="Famille", color="#ff0000"), db=db, user=USER)
    assert lab.name == "Famille" and lab.color == "#ff0000"

    lst = await R.list_labels(cal.id, db=db, user=USER)
    assert [l.name for l in lst] == ["Famille"]

    # PATCH partiel : on ne change que le nom → la couleur est conservée.
    upd = await R.update_label(lab.id, LabelUpdate(name="Maison"), db=db, user=USER)
    assert upd.name == "Maison" and upd.color == "#ff0000"

    await R.delete_label(lab.id, db=db, user=USER)
    assert (await R.list_labels(cal.id, db=db, user=USER)) == []


@pytest.mark.asyncio
async def test_event_porte_label_et_set_null_a_la_suppression(db):
    cal = await _cal(db)
    lab = await R.create_label(cal.id, LabelCreate(name="Boulot", color="#00aa00"), db=db, user=USER)
    debut = datetime(2030, 1, 1, 9, 0)
    evt = await EV.create_event(
        cal.id,
        EventUpdate(title="Réunion", start_at=debut, end_at=debut + timedelta(hours=1), label_id=lab.id),
        db=db, user=USER,
    )
    assert evt.label_id == lab.id

    # Supprimer l'étiquette ne supprime pas l'événement : il repasse « sans étiquette ».
    await R.delete_label(lab.id, db=db, user=USER)
    relu = (await db.execute(select(Event).where(Event.id == evt.id))).scalar_one()
    assert relu.label_id is None
    assert relu.title == "Réunion"


@pytest.mark.asyncio
async def test_vider_etiquette_via_chaine_vide(db):
    cal = await _cal(db)
    lab = await R.create_label(cal.id, LabelCreate(name="X"), db=db, user=USER)
    debut = datetime(2030, 1, 1, 9, 0)
    evt = await EV.create_event(
        cal.id,
        EventUpdate(title="T", start_at=debut, end_at=debut + timedelta(hours=1), label_id=lab.id),
        db=db, user=USER,
    )
    assert evt.label_id == lab.id
    # PATCH avec label_id="" = « aucune étiquette » explicite (None est ignoré par exclude_none).
    upd = await EV.update_event(evt.id, EventUpdate(label_id=""), db=db, user=USER)
    assert upd.label_id is None


@pytest.mark.asyncio
async def test_supprimer_calendrier_supprime_ses_etiquettes(db):
    cal = await _cal(db)
    await R.create_label(cal.id, LabelCreate(name="A"), db=db, user=USER)
    from models.orm import Label

    await db.delete(cal)
    await db.commit()
    restantes = (await db.execute(select(Label).where(Label.calendar_id == cal.id))).scalars().all()
    assert restantes == []
