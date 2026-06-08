"""CRUD calendriers — /calendars."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Calendar, CalendarMember
from models.schemas import CalendarCreate, CalendarOut, CalendarUpdate, CalendarWithRoleOut
from utils.access import require_calendar_access

router = APIRouter(prefix="/calendars", tags=["calendars"])


@router.get("", response_model=list[CalendarWithRoleOut])
async def list_calendars(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    user_id = user["sub"]

    owned_res = await db.execute(select(Calendar).where(Calendar.user_id == user_id))
    owned_cals = owned_res.scalars().all()
    owned_ids = {c.id for c in owned_cals}

    member_res = await db.execute(
        select(CalendarMember, Calendar)
        .join(Calendar, CalendarMember.calendar_id == Calendar.id)
        .where(CalendarMember.user_id == user_id)
    )
    member_rows = member_res.all()

    result = [
        CalendarWithRoleOut(**CalendarOut.model_validate(c).model_dump(), role="owner")
        for c in owned_cals
    ]
    for member, cal in member_rows:
        if cal.id not in owned_ids:
            result.append(
                CalendarWithRoleOut(**CalendarOut.model_validate(cal).model_dump(), role=member.role)
            )
    return result


@router.post("", response_model=CalendarWithRoleOut, status_code=status.HTTP_201_CREATED)
async def create_calendar(
    body: CalendarCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    cal = Calendar(**body.model_dump(), user_id=user["sub"])
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return CalendarWithRoleOut(**CalendarOut.model_validate(cal).model_dump(), role="owner")


@router.get("/{cal_id}", response_model=CalendarWithRoleOut)
async def get_calendar(
    cal_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    cal, role = await require_calendar_access(db, cal_id, user["sub"], min_role="viewer")
    return CalendarWithRoleOut(**CalendarOut.model_validate(cal).model_dump(), role=role)


@router.patch("/{cal_id}", response_model=CalendarWithRoleOut)
async def update_calendar(
    cal_id: str,
    body: CalendarUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    cal, role = await require_calendar_access(db, cal_id, user["sub"], min_role="editor")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(cal, k, v)
    await db.commit()
    await db.refresh(cal)
    return CalendarWithRoleOut(**CalendarOut.model_validate(cal).model_dump(), role=role)


@router.delete("/{cal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar(
    cal_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    cal, _ = await require_calendar_access(db, cal_id, user["sub"], min_role="owner")
    await db.delete(cal)
    await db.commit()
