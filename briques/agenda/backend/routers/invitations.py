"""Invitations à un calendrier — /calendars/{cal_id}/invitations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from db import get_db
from models.orm import Calendar, CalendarInvitation, CalendarMember
from models.schemas import InvitationCreate, InvitationOut
from templates import page_invitation
from utils.access import require_calendar_access

router = APIRouter(tags=["invitations"])


@router.get("/calendars/{cal_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(
    cal_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="owner")
    result = await db.execute(
        select(CalendarInvitation).where(CalendarInvitation.calendar_id == cal_id)
    )
    return result.scalars().all()


@router.post("/calendars/{cal_id}/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    cal_id: str,
    body: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="owner")
    expires_at = None
    if body.expires_in_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours)
    inv = CalendarInvitation(
        calendar_id=cal_id,
        email=body.email,
        role=body.role,
        created_by=user["sub"],
        expires_at=expires_at,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv


@router.get("/invitations/{token}", response_model=InvitationOut)
async def get_invitation(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CalendarInvitation).where(CalendarInvitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    out = InvitationOut.model_validate(inv)
    cal = await db.get(Calendar, inv.calendar_id)
    out.calendar_name = cal.name if cal else None
    return out


@router.get("/invitations/{token}/page", response_class=HTMLResponse, include_in_schema=False)
async def invitation_page(token: str):
    """Page d'acceptation cliquable (c'est l'URL transmise à l'invité)."""
    kc_url = settings.KEYCLOAK_PUBLIC_URL or settings.KEYCLOAK_URL
    return page_invitation(
        token, settings.AUTH_ENABLED, kc_url,
        settings.KEYCLOAK_REALM, settings.KEYCLOAK_CLIENT_ID,
    )


@router.post("/invitations/{token}/accept", status_code=status.HTTP_200_OK)
async def accept_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(CalendarInvitation).where(CalendarInvitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if inv.used_at:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation already used")
    if inv.expires_at and datetime.now(timezone.utc) > inv.expires_at.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation expired")

    already = await db.execute(
        select(CalendarMember).where(
            CalendarMember.calendar_id == inv.calendar_id,
            CalendarMember.user_id == user["sub"],
        )
    )
    if not already.scalar_one_or_none():
        member = CalendarMember(calendar_id=inv.calendar_id, user_id=user["sub"], role=inv.role)
        db.add(member)

    inv.used_at = datetime.now(timezone.utc)
    await db.commit()
    return {"calendar_id": inv.calendar_id}
