"""Access control helpers — owner/editor/viewer."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, CalendarMember

ROLE_ORDER = {"viewer": 0, "editor": 1, "owner": 2}


async def get_user_role(db: AsyncSession, cal_id: str, user_id: str) -> str | None:
    """Return the user's role for a calendar, or None if no access."""
    cal = await db.get(Calendar, cal_id)
    if not cal:
        return None
    if cal.user_id == user_id:
        return "owner"
    result = await db.execute(
        select(CalendarMember).where(
            CalendarMember.calendar_id == cal_id,
            CalendarMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    return member.role if member else None


async def require_calendar_access(
    db: AsyncSession,
    cal_id: str,
    user_id: str,
    min_role: str = "viewer",
) -> tuple[Calendar, str]:
    """Return (calendar, role) if user has >= min_role. Raises 404 otherwise."""
    role = await get_user_role(db, cal_id, user_id)
    if role is None or ROLE_ORDER.get(role, -1) < ROLE_ORDER.get(min_role, 999):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar not found")
    cal = await db.get(Calendar, cal_id)
    return cal, role
