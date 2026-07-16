"""S174 — gating d'accès (I1) sur activity/participants + contrainte unique participant."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models.orm import Calendar, CalendarMember, Event, EventParticipant
from models.schemas import ParticipantStatusUpdate
from routers import activity as A
from routers import participants as P

OWNER = {"sub": "perso"}
EDITOR = {"sub": "marina"}
VIEWER = {"sub": "bob"}
INTRUS = {"sub": "intrus"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


async def _evt(db, cal) -> Event:
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


async def _cal_avec_membres(db) -> Calendar:
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina", role="editor"))
    db.add(CalendarMember(calendar_id=cal.id, user_id="bob", role="viewer"))
    await db.commit()
    return cal


# ---------------------------------------------------------------------------
# GET /events/{id}/activity — viewer requis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activity_refuse_non_membre(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    with pytest.raises(HTTPException) as exc:
        await A.list_activity(evt.id, db=db, user=INTRUS)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activity_autorise_owner(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    out = await A.list_activity(evt.id, db=db, user=OWNER)
    assert out == []


@pytest.mark.asyncio
async def test_activity_autorise_viewer(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    out = await A.list_activity(evt.id, db=db, user=VIEWER)
    assert out == []


@pytest.mark.asyncio
async def test_activity_autorise_editor(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    out = await A.list_activity(evt.id, db=db, user=EDITOR)
    assert out == []


# ---------------------------------------------------------------------------
# POST /events/{id}/participants/all — editor requis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_all_members_refuse_non_membre(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    with pytest.raises(HTTPException) as exc:
        await P.add_all_members(evt.id, db=db, user=INTRUS)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_all_members_refuse_viewer(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    with pytest.raises(HTTPException) as exc:
        await P.add_all_members(evt.id, db=db, user=VIEWER)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_all_members_autorise_owner(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    out = await P.add_all_members(evt.id, db=db, user=OWNER)
    assert {p.user_id for p in out} == {"perso", "marina", "bob"}


@pytest.mark.asyncio
async def test_add_all_members_autorise_editor(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    out = await P.add_all_members(evt.id, db=db, user=EDITOR)
    assert {p.user_id for p in out} == {"perso", "marina", "bob"}


# ---------------------------------------------------------------------------
# PATCH /events/{id}/participants/{participant_user_id} — self=viewer, autrui=editor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_participant_refuse_non_membre(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await P.update_participant_status(
            evt.id, "marina", ParticipantStatusUpdate(status="accepted"), db=db, user=INTRUS)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_participant_viewer_sur_soi_meme_autorise(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    db.add(EventParticipant(event_id=evt.id, user_id="bob", status="pending"))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "bob", ParticipantStatusUpdate(status="accepted"), db=db, user=VIEWER)
    assert out.status == "accepted"


@pytest.mark.asyncio
async def test_patch_participant_viewer_sur_autrui_refuse(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await P.update_participant_status(
            evt.id, "marina", ParticipantStatusUpdate(status="accepted"), db=db, user=VIEWER)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_participant_editor_sur_autrui_autorise(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    db.add(EventParticipant(event_id=evt.id, user_id="bob", status="pending"))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "bob", ParticipantStatusUpdate(status="accepted"), db=db, user=EDITOR)
    assert out.status == "accepted"


@pytest.mark.asyncio
async def test_patch_participant_owner_sur_autrui_autorise(db):
    cal = await _cal_avec_membres(db)
    evt = await _evt(db, cal)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending"))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(status="accepted"), db=db, user=OWNER)
    assert out.status == "accepted"


# ---------------------------------------------------------------------------
# Contrainte unique (event_id, user_id) sur EventParticipant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_participant_doublon_leve_integrity_error(db):
    cal = await _cal(db)
    evt = await _evt(db, cal)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending"))
    await db.commit()
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="accepted"))
    with pytest.raises(IntegrityError):
        await db.commit()
