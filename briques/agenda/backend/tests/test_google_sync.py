"""Pont Google → brique : mapping, idempotence, refresh, calendrier dédié."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import vault
from models.orm import Calendar, Event
from services import google_calendar


# ── Mapping pur (pas de DB) ────────────────────────────────────────────────────

def test_map_timed_event():
    item = {
        "id": "g1",
        "summary": "Réunion",
        "description": "ordre du jour",
        "location": "Paris",
        "start": {"dateTime": "2026-06-10T14:00:00+02:00"},
        "end": {"dateTime": "2026-06-10T15:00:00+02:00"},
    }
    m = google_calendar.map_google_event(item)
    assert m["external_id"] == "g1"
    assert m["title"] == "Réunion"
    assert m["all_day"] is False
    # 14h Paris (UTC+2) → 12h UTC, stocké naïf
    assert m["start_at"] == datetime(2026, 6, 10, 12, 0, 0)


def test_map_all_day_event():
    item = {"id": "g2", "summary": "Congé", "start": {"date": "2026-06-11"}, "end": {"date": "2026-06-12"}}
    m = google_calendar.map_google_event(item)
    assert m["all_day"] is True
    assert m["start_at"] == datetime(2026, 6, 11, 0, 0, 0)


def test_map_cancelled_is_skipped():
    assert google_calendar.map_google_event({"id": "g3", "status": "cancelled"}) is None


def test_map_missing_dates_skipped():
    assert google_calendar.map_google_event({"id": "g4", "summary": "x"}) is None


def test_map_untitled_fallback():
    item = {"id": "g5", "start": {"date": "2026-06-11"}, "end": {"date": "2026-06-12"}}
    assert google_calendar.map_google_event(item)["title"] == "(sans titre)"


# ── Upsert idempotent (DB) ──────────────────────────────────────────────────────

ITEMS = [
    {
        "id": "g1",
        "summary": "Réunion",
        "start": {"dateTime": "2026-06-10T14:00:00+00:00"},
        "end": {"dateTime": "2026-06-10T15:00:00+00:00"},
    },
    {
        "id": "g2",
        "summary": "Congé",
        "start": {"date": "2026-06-11"},
        "end": {"date": "2026-06-12"},
    },
    {"id": "g3", "status": "cancelled"},
]


@pytest.mark.asyncio
async def test_upsert_creates_then_is_idempotent(db):
    cal = await google_calendar._get_or_create_google_calendar(db, "user-1")

    s1 = await google_calendar.upsert_events(db, cal, "user-1", ITEMS)
    assert (s1["created"], s1["updated"], s1["skipped"]) == (2, 0, 1)

    # Re-sync des mêmes items : update, pas de doublon
    s2 = await google_calendar.upsert_events(db, cal, "user-1", ITEMS)
    assert (s2["created"], s2["updated"], s2["skipped"]) == (0, 2, 1)

    rows = (await db.execute(select(Event).where(Event.calendar_id == cal.id))).scalars().all()
    assert len(rows) == 2
    assert all(e.source == "google" and e.external_id for e in rows)


@pytest.mark.asyncio
async def test_resync_updates_title(db):
    cal = await google_calendar._get_or_create_google_calendar(db, "user-1")
    await google_calendar.upsert_events(db, cal, "user-1", ITEMS[:1])
    changed = [{**ITEMS[0], "summary": "Réunion (déplacée)"}]
    await google_calendar.upsert_events(db, cal, "user-1", changed)
    row = (await db.execute(select(Event).where(Event.external_id == "g1"))).scalar_one()
    assert row.title == "Réunion (déplacée)"


@pytest.mark.asyncio
async def test_google_calendar_created_once(db):
    c1 = await google_calendar._get_or_create_google_calendar(db, "user-1")
    c2 = await google_calendar._get_or_create_google_calendar(db, "user-1")
    assert c1.id == c2.id
    cals = (await db.execute(select(Calendar).where(Calendar.user_id == "user-1"))).scalars().all()
    assert len(cals) == 1


@pytest.mark.asyncio
async def test_manual_events_untouched(db):
    """Le pont ne modifie jamais un événement saisi à la main."""
    cal = await google_calendar._get_or_create_google_calendar(db, "user-1")
    manual = Event(
        calendar_id=cal.id, title="Perso", created_by="user-1", source="manuel",
        start_at=datetime(2026, 6, 10, 14, 0), end_at=datetime(2026, 6, 10, 15, 0),
        external_id="g1",  # même id qu'un event Google, mais source manuel
    )
    db.add(manual)
    await db.commit()

    await google_calendar.upsert_events(db, cal, "user-1", ITEMS[:1])
    await db.refresh(manual)
    assert manual.title == "Perso"  # intact
    # un nouvel event google a été créé séparément
    googles = (
        await db.execute(select(Event).where(Event.source == "google"))
    ).scalars().all()
    assert len(googles) == 1


# ── Auto-refresh du token (Google mocké) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_access_token_refreshes_when_expired(db, monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await vault.upsert_token(
        db, "user-1", "stale-access", refresh_token="refresh-1", expires_at=past
    )

    async def fake_refresh(refresh_token):
        assert refresh_token == "refresh-1"
        return {
            "access_token": "fresh-access",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "scope": "calendar.readonly",
        }

    monkeypatch.setattr(google_calendar.google_oauth, "refresh_access_token", fake_refresh)

    token = await google_calendar._valid_access_token(db, "user-1")
    assert token == "fresh-access"
    # le nouveau token est rangé au coffre
    assert await vault.get_access_token(db, "user-1") == "fresh-access"


@pytest.mark.asyncio
async def test_valid_access_token_no_refresh_raises(db):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await vault.upsert_token(db, "user-1", "stale", expires_at=past)  # pas de refresh
    with pytest.raises(google_calendar.GoogleSyncError):
        await google_calendar._valid_access_token(db, "user-1")


@pytest.mark.asyncio
async def test_valid_access_token_not_connected_raises(db):
    with pytest.raises(google_calendar.GoogleSyncError):
        await google_calendar._valid_access_token(db, "user-unknown")


@pytest.mark.asyncio
async def test_valid_access_token_returns_live_token(db):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await vault.upsert_token(db, "user-1", "live-access", expires_at=future)
    assert await google_calendar._valid_access_token(db, "user-1") == "live-access"
