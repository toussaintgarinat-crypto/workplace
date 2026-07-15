"""Résolution des membres d'un calendrier (S174) : propriétaire + membres partagés."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, CalendarMember


async def membres_du_calendrier(db: AsyncSession, calendar_id: str) -> set[str]:
    """user_ids ayant accès au calendrier : son propriétaire + tous ses membres."""
    users: set[str] = set()
    cal = await db.get(Calendar, calendar_id)
    if cal:
        users.add(cal.user_id)
    rows = (await db.execute(
        select(CalendarMember.user_id).where(CalendarMember.calendar_id == calendar_id)
    )).scalars().all()
    users.update(rows)
    return users
