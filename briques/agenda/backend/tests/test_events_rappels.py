"""Rappels configurables sur les événements (minutes avant le début).

Teste le validateur de schéma (tri/dédoublonnage/bornes/plafond de nombre) et le
round-trip ORM (la colonne JSON `rappels` persiste et se relit), sans monter l'app.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, Event
from models.schemas import (
    RAPPEL_MAX_MINUTES,
    EventCreate,
    EventUpdate,
    normaliser_rappels,
)


# ── Validateur (pur, sans DB) ────────────────────────────────────────────────

def test_normaliser_trie_et_dedoublonne():
    assert normaliser_rappels([30, 10, 30, 1440, 10]) == [10, 30, 1440]


def test_normaliser_none_reste_none():
    # None = champ non fourni au PATCH (≠ liste vide qui efface).
    assert normaliser_rappels(None) is None


def test_normaliser_liste_vide_reste_vide():
    assert normaliser_rappels([]) == []


def test_normaliser_refuse_negatif():
    with pytest.raises(ValueError):
        normaliser_rappels([-5])


def test_normaliser_refuse_hors_plafond():
    with pytest.raises(ValueError):
        normaliser_rappels([RAPPEL_MAX_MINUTES + 1])


def test_normaliser_refuse_trop_nombreux():
    with pytest.raises(ValueError):
        normaliser_rappels([0, 5, 10, 15, 30, 60])  # 6 > max 5


def test_normaliser_refuse_non_entier():
    with pytest.raises(ValueError):
        normaliser_rappels(["10"])
    with pytest.raises(ValueError):
        normaliser_rappels([True])  # bool n'est pas un nombre de minutes valide


def test_schemas_appliquent_le_validateur():
    debut = datetime(2030, 1, 1, 14, 0)
    ec = EventCreate(calendar_id="c1", title="RDV", start_at=debut,
                     end_at=debut + timedelta(hours=1), rappels=[1440, 10, 10])
    assert ec.rappels == [10, 1440]
    eu = EventUpdate(rappels=[])
    assert eu.rappels == []


# ── Round-trip ORM (colonne JSON) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rappels_persistent_en_base(db):
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Dentiste", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso",
                rappels=[30, 1440])
    db.add(evt)
    await db.commit()

    relu = (await db.execute(select(Event).where(Event.id == evt.id))).scalar_one()
    assert relu.rappels == [30, 1440]


@pytest.mark.asyncio
async def test_rappels_defaut_liste_vide(db):
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 9, 0)
    evt = Event(calendar_id=cal.id, title="Sans rappel", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.commit()

    relu = (await db.execute(select(Event).where(Event.id == evt.id))).scalar_one()
    assert relu.rappels == []
