"""Pont TimeTree → brique Agenda (pull one-way, idempotent, lecture seule).

Miroir de `services/google_calendar.py` : lit les événements du calendrier TimeTree
partagé (via le client NON OFFICIEL `timetree_client`) et les projette dans un calendrier
dédié « TimeTree » de la brique. Idempotent : un événement déjà importé (même
`external_id` = UID TimeTree) est mis à jour, pas dupliqué. On ne touche JAMAIS aux
événements `source="manuel"`, et on n'écrit JAMAIS vers TimeTree.

Identifiants : rangés chiffrés au coffre (vault.py) sous `provider="timetree"` —
`access_token_enc` = mot de passe, `refresh_token_enc` = email, `scope` = id du calendrier.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from timetree_exporter.event import TimeTreeEvent

from models.orm import Calendar, Event, Label
from services import timetree_client
from vault import get_access_token, get_refresh_token, get_token_row

logger = logging.getLogger(__name__)

TIMETREE_CALENDAR_NAME = "TimeTree"


class TimeTreeSyncError(RuntimeError):
    pass


def _from_ms(value) -> datetime | None:
    """Convertit un horodatage TimeTree (epoch en millisecondes) en datetime naïf UTC.

    Tolérant : si la valeur ressemble à des secondes (< 1e11), on ne divise pas — colle
    au modèle DateTime naïf de la brique (comme le parse Google)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if abs(v) >= 1e11:  # millisecondes
        v /= 1000.0
    return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None, microsecond=0)


def map_timetree_event(raw: dict, labels: dict | None = None) -> dict | None:
    """Projette un événement brut TimeTree sur les champs d'un Event de la brique.

    `labels` = {label_id: {'name', 'color'}} (de get_labels) : la COULEUR d'un événement
    TimeTree vient de son étiquette. On reporte ce hex sur Event.color pour que chaque
    rendez-vous garde sa couleur. Retourne None pour les entrées non importables."""
    ev = TimeTreeEvent.from_dict(raw)
    if not ev.uuid:
        return None
    start_at = _from_ms(ev.start_at)
    end_at = _from_ms(ev.end_at)
    if start_at is None or end_at is None:
        return None
    color = None
    if labels:
        info = labels.get(ev.label_id)
        if info:
            color = info.get("color")
    return {
        "external_id": ev.uuid,
        "title": ev.title or "(sans titre)",
        "description": ev.note,
        "location": ev.location or None,
        "start_at": start_at,
        "end_at": end_at,
        "all_day": bool(ev.all_day),
        "color": color,
        # Étiquette TimeTree d'origine (id de label), résolue en Label local par l'upsert.
        # Clé interne (préfixe _) : retirée avant de construire l'Event ORM.
        "_label_external_id": None if ev.label_id is None else str(ev.label_id),
    }


async def _sync_labels(db: AsyncSession, calendar: Calendar, labels: dict | None) -> dict:
    """Projette les étiquettes TimeTree (get_labels) en `Label` nommés du calendrier.

    Idempotent par `external_id` (= id du label TimeTree) : une re-sync met à jour le
    nom/couleur au lieu de dupliquer. Renvoie {external_id(str): Label.id} pour rattacher
    chaque événement à son étiquette locale → la légende affiche les VRAIS noms de
    catégories TimeTree, pas seulement des couleurs."""
    mapping: dict = {}
    if not labels:
        return mapping
    for tt_id, info in labels.items():
        ext = str(tt_id)
        info = info or {}
        name = info.get("name") or "(sans nom)"
        color = info.get("color")
        res = await db.execute(
            select(Label).where(Label.calendar_id == calendar.id, Label.external_id == ext)
        )
        label = res.scalar_one_or_none()
        if label is None:
            label = Label(calendar_id=calendar.id, name=name,
                          color=color or "#5865F2", external_id=ext)
            db.add(label)
            await db.flush()
        else:
            label.name = name
            if color:
                label.color = color
        mapping[ext] = label.id
    await db.flush()
    return mapping


async def _get_or_create_timetree_calendar(db: AsyncSession, user_id: str) -> Calendar:
    res = await db.execute(
        select(Calendar).where(
            Calendar.user_id == user_id, Calendar.name == TIMETREE_CALENDAR_NAME
        )
    )
    cal = res.scalar_one_or_none()
    if cal is None:
        cal = Calendar(
            user_id=user_id,
            name=TIMETREE_CALENDAR_NAME,
            color="#4CD2C0",  # turquoise TimeTree
            description="Événements rapatriés de TimeTree (lecture seule, non officiel)",
        )
        db.add(cal)
        await db.commit()
        await db.refresh(cal)
    return cal


async def upsert_events(
    db: AsyncSession, calendar: Calendar, user_id: str, raw_events: list[dict],
    labels: dict | None = None, label_map: dict | None = None,
) -> dict:
    """Upsert idempotent des événements TimeTree dans le calendrier dédié.

    `label_map` = {external_id(str): Label.id} (de `_sync_labels`) : rattache chaque
    événement à son étiquette locale nommée."""
    label_map = label_map or {}
    created = updated = skipped = 0
    for raw in raw_events:
        mapped = map_timetree_event(raw, labels)
        if mapped is None:
            skipped += 1
            continue
        ext_label = mapped.pop("_label_external_id", None)
        label_id = label_map.get(ext_label) if ext_label else None
        res = await db.execute(
            select(Event).where(
                Event.calendar_id == calendar.id,
                Event.external_id == mapped["external_id"],
                Event.source == "timetree",
            )
        )
        existing = res.scalar_one_or_none()
        if existing is None:
            db.add(Event(calendar_id=calendar.id, created_by=user_id,
                         source="timetree", label_id=label_id, **mapped))
            created += 1
        else:
            existing.title = mapped["title"]
            existing.description = mapped["description"]
            existing.location = mapped["location"]
            existing.start_at = mapped["start_at"]
            existing.end_at = mapped["end_at"]
            existing.all_day = mapped["all_day"]
            existing.color = mapped["color"]
            existing.label_id = label_id
            updated += 1
    await db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


async def sync_user(db: AsyncSession, user_id: str) -> dict:
    """Orchestration complète d'un pull TimeTree pour un utilisateur."""
    email = await get_refresh_token(db, user_id, "timetree")
    password = await get_access_token(db, user_id, "timetree")
    if not email or not password:
        raise TimeTreeSyncError("Aucun compte TimeTree connecté pour cet utilisateur")
    row = await get_token_row(db, user_id, "timetree")
    calendar_id = row.scope if row else None
    if not calendar_id:
        raise TimeTreeSyncError("Aucun calendrier TimeTree sélectionné — choisis-en un")

    # Le client TimeTree est synchrone (requests) → thread dédié. Events + couleurs (labels).
    data = await asyncio.to_thread(
        timetree_client.fetch, email, password, calendar_id)
    raw_events = data.get("events", [])
    labels = data.get("labels", {})
    calendar = await _get_or_create_timetree_calendar(db, user_id)
    label_map = await _sync_labels(db, calendar, labels)
    stats = await upsert_events(db, calendar, user_id, raw_events, labels, label_map)
    stats["labels"] = len(label_map)
    stats["calendar_id"] = calendar.id
    stats["fetched"] = len(raw_events)
    return stats
