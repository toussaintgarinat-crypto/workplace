"""Access control helpers — owner/editor/viewer."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import (
    Calendar,
    CalendarMember,
    LoyaltyCard,
    ShoppingList,
    ShoppingListMember,
)

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


# ── S176 : accès listes de courses/tâches + cartes de fidélité ────────────────

async def get_list_role(db: AsyncSession, list_id: str, user_id: str) -> str | None:
    """Rôle de l'utilisateur sur une liste, ou None si aucun accès."""
    liste = await db.get(ShoppingList, list_id)
    if not liste:
        return None
    if liste.created_by == user_id:
        return "owner"
    result = await db.execute(
        select(ShoppingListMember).where(
            ShoppingListMember.list_id == list_id,
            ShoppingListMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    return member.role if member else None


async def require_list_access(
    db: AsyncSession,
    list_id: str,
    user_id: str,
    min_role: str = "viewer",
) -> tuple[ShoppingList, str]:
    """(liste, rôle) si accès >= min_role ; 404 sinon (ne divulgue pas l'existence)."""
    role = await get_list_role(db, list_id, user_id)
    if role is None or ROLE_ORDER.get(role, -1) < ROLE_ORDER.get(min_role, 999):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liste introuvable")
    liste = await db.get(ShoppingList, list_id)
    return liste, role


async def require_owned_card(db: AsyncSession, card_id: str, user_id: str) -> LoyaltyCard:
    """Carte si elle appartient à user_id ; 404 sinon."""
    carte = await db.get(LoyaltyCard, card_id)
    if carte is None or carte.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carte introuvable")
    return carte
