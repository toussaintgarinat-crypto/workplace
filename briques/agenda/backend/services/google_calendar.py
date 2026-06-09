"""Pont Google Calendar → brique Agenda (pull one-way, idempotent).

Lit les événements du calendrier principal Google de l'utilisateur et les
projette dans un calendrier dédié « Google » de la brique. Le pull est
idempotent : un événement déjà importé (même `external_id`) est mis à jour, pas
dupliqué. On ne touche jamais aux événements `source="manuel"`.

Auto-refresh : si l'access_token est expiré, on le renouvelle via le
refresh_token du coffre avant l'appel, et on range le nouveau token.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, Event
from services import google_oauth
from vault import get_refresh_token, get_token_row, upsert_token

logger = logging.getLogger(__name__)

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GOOGLE_CALENDAR_NAME = "Google"


class GoogleSyncError(RuntimeError):
    pass


async def _valid_access_token(db: AsyncSession, user_id: str) -> str:
    """Retourne un access_token valide, en le rafraîchissant si expiré."""
    row = await get_token_row(db, user_id, "google")
    if row is None:
        raise GoogleSyncError("Aucun compte Google connecté pour cet utilisateur")

    now = datetime.now(timezone.utc)
    expired = row.expires_at is not None and _aware(row.expires_at) <= now
    if not expired:
        from vault import decrypt

        try:
            return decrypt(row.access_token_enc)
        except Exception as exc:  # token illisible → on tente le refresh
            logger.warning("access_token illisible, refresh: %s", exc)

    refresh = await get_refresh_token(db, user_id, "google")
    if not refresh:
        raise GoogleSyncError("Token expiré et aucun refresh_token disponible — reconnecte Google")
    fresh = await google_oauth.refresh_access_token(refresh)
    await upsert_token(
        db,
        user_id,
        fresh["access_token"],
        provider="google",
        expires_at=fresh["expires_at"],
        scope=fresh.get("scope"),
    )
    return fresh["access_token"]


def _aware(dt: datetime) -> datetime:
    """Force un datetime naïf (stocké SQLite) en UTC pour comparer sans planter."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def _get_or_create_google_calendar(db: AsyncSession, user_id: str) -> Calendar:
    res = await db.execute(
        select(Calendar).where(
            Calendar.user_id == user_id, Calendar.name == GOOGLE_CALENDAR_NAME
        )
    )
    cal = res.scalar_one_or_none()
    if cal is None:
        cal = Calendar(
            user_id=user_id,
            name=GOOGLE_CALENDAR_NAME,
            color="#4285F4",
            description="Événements rapatriés de Google Agenda (lecture seule)",
        )
        db.add(cal)
        await db.commit()
        await db.refresh(cal)
    return cal


def _parse_google_dt(node: dict) -> tuple[datetime, bool]:
    """Convertit le bloc start/end d'un event Google en (datetime, all_day).

    Google donne soit `dateTime` (ISO avec offset) soit `date` (jour entier).
    On normalise en datetime naïf UTC pour coller au modèle DateTime de la brique.
    """
    if "dateTime" in node:
        dt = datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None), False
    # all-day : "date" = "YYYY-MM-DD"
    d = datetime.fromisoformat(node["date"])
    return d, True


def map_google_event(item: dict) -> dict | None:
    """Projette un item de l'API Google sur les champs d'un Event de la brique.

    Retourne None pour les entrées non importables (annulées, sans dates).
    """
    if item.get("status") == "cancelled":
        return None
    start, end = item.get("start"), item.get("end")
    if not start or not end:
        return None
    start_at, all_day = _parse_google_dt(start)
    end_at, _ = _parse_google_dt(end)
    return {
        "external_id": item["id"],
        "title": item.get("summary") or "(sans titre)",
        "description": item.get("description"),
        "location": item.get("location"),
        "start_at": start_at,
        "end_at": end_at,
        "all_day": all_day,
    }


async def _fetch_events(access_token: str, time_min: str | None, time_max: str | None) -> list[dict]:
    params: dict = {"singleEvents": "true", "maxResults": 250, "orderBy": "startTime"}
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            EVENTS_URL,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if not r.is_success:
        raise GoogleSyncError(f"Lecture Google Calendar échouée ({r.status_code}): {r.text}")
    return r.json().get("items", [])


async def upsert_events(
    db: AsyncSession, calendar: Calendar, user_id: str, items: list[dict]
) -> dict:
    """Upsert idempotent des events Google dans le calendrier dédié."""
    created = updated = skipped = 0
    for item in items:
        mapped = map_google_event(item)
        if mapped is None:
            skipped += 1
            continue
        res = await db.execute(
            select(Event).where(
                Event.calendar_id == calendar.id,
                Event.external_id == mapped["external_id"],
                Event.source == "google",
            )
        )
        existing = res.scalar_one_or_none()
        if existing is None:
            db.add(
                Event(
                    calendar_id=calendar.id,
                    created_by=user_id,
                    source="google",
                    **mapped,
                )
            )
            created += 1
        else:
            existing.title = mapped["title"]
            existing.description = mapped["description"]
            existing.location = mapped["location"]
            existing.start_at = mapped["start_at"]
            existing.end_at = mapped["end_at"]
            existing.all_day = mapped["all_day"]
            updated += 1
    await db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


async def sync_user(
    db: AsyncSession,
    user_id: str,
    *,
    time_min: str | None = None,
    time_max: str | None = None,
) -> dict:
    """Orchestration complète d'un pull pour un utilisateur."""
    access_token = await _valid_access_token(db, user_id)
    items = await _fetch_events(access_token, time_min, time_max)
    calendar = await _get_or_create_google_calendar(db, user_id)
    stats = await upsert_events(db, calendar, user_id, items)
    stats["calendar_id"] = calendar.id
    stats["fetched"] = len(items)
    return stats
