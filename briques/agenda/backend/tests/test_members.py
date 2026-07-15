"""Membres d'un calendrier — ajout/suppression, contrôle d'accès owner-only."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import Calendar, CalendarMember
from models.schemas import MemberAdd
from routers import members as R

OWNER = {"sub": "perso"}
MARINA = {"sub": "marina-sub"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_add_member_par_owner(db):
    cal = await _cal(db)
    out = await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="editor"), db=db, user=OWNER)
    assert out.user_id == "marina-sub" and out.role == "editor"

    lst = await R.list_members(cal.id, db=db, user=OWNER)
    assert [m.user_id for m in lst] == ["marina-sub"]


@pytest.mark.asyncio
async def test_add_member_refuse_si_pas_owner(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina-sub", role="editor"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.add_member(cal.id, MemberAdd(user_id="autre", role="viewer"), db=db, user=MARINA)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_member_doublon_409(db):
    cal = await _cal(db)
    await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="viewer"), db=db, user=OWNER)
    with pytest.raises(HTTPException) as exc:
        await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="editor"), db=db, user=OWNER)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_member(db):
    cal = await _cal(db)
    await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="viewer"), db=db, user=OWNER)
    await R.remove_member(cal.id, "marina-sub", db=db, user=OWNER)
    assert await R.list_members(cal.id, db=db, user=OWNER) == []


@pytest.mark.asyncio
async def test_remove_member_introuvable_404(db):
    cal = await _cal(db)
    with pytest.raises(HTTPException) as exc:
        await R.remove_member(cal.id, "jamais-invite", db=db, user=OWNER)
    assert exc.value.status_code == 404
