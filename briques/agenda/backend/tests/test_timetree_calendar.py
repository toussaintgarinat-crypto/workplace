"""Pont TimeTree → brique : mapping des événements bruts + upsert idempotent.

Sans réseau ni TimeTree : on teste le mapping (epoch ms → datetime, all-day, UID) et
l'upsert idempotent (2ᵉ passage = 0 created) qui ne touche jamais les events `manuel`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, Event, Label
from services import timetree_calendar as ttc


def _raw(uuid="u1", title="RDV Marina", start_ms=1751371200000, end_ms=1751374800000,
         all_day=False, note="note", location="Paris"):
    return {"uuid": uuid, "title": title, "start_at": start_ms, "end_at": end_ms,
            "all_day": all_day, "note": note, "location": location, "type": 0, "category": 1}


# ── Mapping pur ──────────────────────────────────────────────────────────────

def test_map_epoch_ms():
    m = ttc.map_timetree_event(_raw())
    assert m["external_id"] == "u1"
    assert m["title"] == "RDV Marina"
    assert m["start_at"] == datetime(2025, 7, 1, 12, 0)   # 1751371200000 ms = 2025-07-01 12:00 UTC
    assert m["end_at"] == datetime(2025, 7, 1, 13, 0)
    assert m["all_day"] is False


def test_map_sans_uid_ou_dates_ignore():
    assert ttc.map_timetree_event(_raw(uuid=None)) is None
    assert ttc.map_timetree_event(_raw(start_ms=None)) is None
    assert ttc.map_timetree_event(_raw(end_ms=None)) is None


def test_map_titre_par_defaut():
    assert ttc.map_timetree_event(_raw(title=None))["title"] == "(sans titre)"


def test_map_couleur_depuis_label():
    labels = {5: {"name": "Perso", "color": "#ff0000"},
              7: {"name": "Boulot", "color": "#00aa00"}}
    r5 = _raw(uuid="x"); r5["label_id"] = 5
    r7 = _raw(uuid="y"); r7["label_id"] = 7
    assert ttc.map_timetree_event(r5, labels)["color"] == "#ff0000"
    assert ttc.map_timetree_event(r7, labels)["color"] == "#00aa00"


def test_map_sans_label_couleur_none():
    assert ttc.map_timetree_event(_raw())["color"] is None              # pas de labels
    assert ttc.map_timetree_event(_raw(), {})["color"] is None          # labels vide


# ── Upsert idempotent ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_idempotent(db):
    cal = Calendar(user_id="perso", name="TimeTree")
    db.add(cal)
    await db.flush()

    raws = [_raw(uuid="a"), _raw(uuid="b", title="Médecin")]
    s1 = await ttc.upsert_events(db, cal, "perso", raws)
    assert s1 == {"created": 2, "updated": 0, "skipped": 0}

    # 2ᵉ passage : même UID → mise à jour, pas de doublon.
    s2 = await ttc.upsert_events(db, cal, "perso", raws)
    assert s2["created"] == 0 and s2["updated"] == 2

    total = (await db.execute(select(Event).where(Event.calendar_id == cal.id))).scalars().all()
    assert len(total) == 2
    assert all(e.source == "timetree" for e in total)


@pytest.mark.asyncio
async def test_upsert_reporte_la_couleur_du_label(db):
    cal = Calendar(user_id="perso", name="TimeTree")
    db.add(cal)
    await db.flush()
    labels = {3: {"name": "Famille", "color": "#4CD2C0"}}
    raw = _raw(uuid="c1"); raw["label_id"] = 3
    await ttc.upsert_events(db, cal, "perso", [raw], labels)
    e = (await db.execute(select(Event).where(Event.external_id == "c1"))).scalar_one()
    assert e.color == "#4CD2C0"


@pytest.mark.asyncio
async def test_sync_labels_nomme_les_categories(db):
    cal = Calendar(user_id="perso", name="TimeTree")
    db.add(cal)
    await db.flush()
    labels = {5: {"name": "Famille", "color": "#ff0000"},
              7: {"name": "Boulot", "color": "#00aa00"}}
    mapping = await ttc._sync_labels(db, cal, labels)
    assert set(mapping.keys()) == {"5", "7"}
    rows = (await db.execute(select(Label).where(Label.calendar_id == cal.id))).scalars().all()
    assert {r.name for r in rows} == {"Famille", "Boulot"}

    # Idempotent : un re-sync met à jour le nom au lieu de dupliquer l'étiquette.
    labels[5]["name"] = "Maison"
    await ttc._sync_labels(db, cal, labels)
    rows2 = (await db.execute(select(Label).where(Label.calendar_id == cal.id))).scalars().all()
    assert len(rows2) == 2 and any(r.name == "Maison" for r in rows2)


@pytest.mark.asyncio
async def test_upsert_rattache_le_label_id(db):
    cal = Calendar(user_id="perso", name="TimeTree")
    db.add(cal)
    await db.flush()
    labels = {5: {"name": "Famille", "color": "#ff0000"}}
    label_map = await ttc._sync_labels(db, cal, labels)
    raw = _raw(uuid="z"); raw["label_id"] = 5
    await ttc.upsert_events(db, cal, "perso", [raw], labels, label_map)
    e = (await db.execute(select(Event).where(Event.external_id == "z"))).scalar_one()
    assert e.label_id == label_map["5"]


@pytest.mark.asyncio
async def test_upsert_ne_touche_pas_les_events_manuels(db):
    cal = Calendar(user_id="perso", name="TimeTree")
    db.add(cal)
    await db.flush()
    # Un event manuel qui partagerait par hasard le même external_id ne doit pas être écrasé.
    manuel = Event(calendar_id=cal.id, title="Le mien", created_by="perso",
                   source="manuel", external_id="a",
                   start_at=datetime(2030, 1, 1, 9, 0), end_at=datetime(2030, 1, 1, 10, 0))
    db.add(manuel)
    await db.commit()

    await ttc.upsert_events(db, cal, "perso", [_raw(uuid="a", title="TimeTree A")])

    relu = (await db.execute(select(Event).where(Event.id == manuel.id))).scalar_one()
    assert relu.title == "Le mien" and relu.source == "manuel"
    # L'event TimeTree a été créé à côté (même external_id mais source différente).
    tt = (await db.execute(
        select(Event).where(Event.source == "timetree", Event.external_id == "a"))).scalars().all()
    assert len(tt) == 1 and tt[0].title == "TimeTree A"
