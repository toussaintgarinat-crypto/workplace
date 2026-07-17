"""Présence éphémère (S179) : partage/retrait/lecture des positions. Une ligne par personne
(upsert). La lecture PURGE d'abord les positions expirées (opportuniste), puis renvoie
celles visibles par l'observateur : toutes les `famille`, les `event` des events où il est
participant, et les siennes. Enrichi du profil (nom + couleur). Aucun historique."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import EventParticipant, LivePosition
from services import profils


async def upsert_position(db: AsyncSession, user_id: str, *, latitude: float, longitude: float,
                          expires_at: datetime, accuracy_m: float | None = None,
                          label: str | None = None, scope: str = "famille",
                          event_id: str | None = None) -> LivePosition:
    pos = await db.get(LivePosition, user_id)
    if pos is None:
        pos = LivePosition(user_id=user_id)
        db.add(pos)
    pos.latitude = latitude
    pos.longitude = longitude
    pos.accuracy_m = accuracy_m
    pos.label = label
    pos.scope = scope
    pos.event_id = event_id
    pos.expires_at = expires_at
    pos.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(pos)
    return pos


async def supprimer_position(db: AsyncSession, user_id: str) -> None:
    pos = await db.get(LivePosition, user_id)
    if pos is not None:
        await db.delete(pos)
        await db.commit()


async def positions_visibles(db: AsyncSession, user_id: str) -> list[dict]:
    now = datetime.utcnow()
    # Purge opportuniste : les positions expirées disparaissent dès la première lecture.
    await db.execute(delete(LivePosition).where(LivePosition.expires_at < now))
    await db.commit()

    rows = (await db.execute(
        select(LivePosition).where(LivePosition.expires_at >= now))).scalars().all()

    mes_events = set((await db.execute(
        select(EventParticipant.event_id).where(
            EventParticipant.user_id == user_id))).scalars().all())

    visibles = [p for p in rows
                if p.scope == "famille" or p.user_id == user_id
                or (p.scope == "event" and p.event_id in mes_events)]

    profs = await profils.resoudre(db, [p.user_id for p in visibles])
    return [{
        "user_id": p.user_id,
        "display_name": profs[p.user_id]["display_name"],
        "avatar_color": profs[p.user_id]["avatar_color"],
        "latitude": p.latitude,
        "longitude": p.longitude,
        "accuracy_m": p.accuracy_m,
        "label": p.label,
        "scope": p.scope,
        "event_id": p.event_id,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "expires_at": p.expires_at.isoformat(),
    } for p in visibles]
