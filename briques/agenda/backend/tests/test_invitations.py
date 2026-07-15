"""Cycle complet d'invitation : créer → consulter → accepter → devenir membre.

Cas limites : expirée, déjà utilisée, calendrier introuvable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from models.orm import Calendar, CalendarInvitation
from models.schemas import InvitationCreate
from routers import invitations as R

OWNER = {"sub": "perso"}
MARINA = {"sub": "marina-sub"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Famille", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_cycle_complet_invitation(db):
    cal = await _cal(db)
    inv = await R.create_invitation(
        cal.id, InvitationCreate(email="marina@example.fr", role="editor"), db=db, user=OWNER
    )
    assert inv.role == "editor" and inv.used_at is None

    lu = await R.get_invitation(inv.token, db=db)
    assert lu.calendar_name == "Famille"

    res = await R.accept_invitation(inv.token, db=db, user=MARINA)
    assert res == {"calendar_id": cal.id}

    lst = await R.list_invitations(cal.id, db=db, user=OWNER)
    assert lst[0].used_at is not None


@pytest.mark.asyncio
async def test_accept_invitation_deja_utilisee_409(db):
    cal = await _cal(db)
    inv = await R.create_invitation(cal.id, InvitationCreate(role="viewer"), db=db, user=OWNER)
    await R.accept_invitation(inv.token, db=db, user=MARINA)
    with pytest.raises(HTTPException) as exc:
        await R.accept_invitation(inv.token, db=db, user={"sub": "quelqu-un-d-autre"})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_invitation_expiree_410(db):
    cal = await _cal(db)
    inv = CalendarInvitation(
        calendar_id=cal.id, role="viewer", created_by="perso",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    with pytest.raises(HTTPException) as exc:
        await R.accept_invitation(inv.token, db=db, user=MARINA)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_get_invitation_introuvable_404(db):
    with pytest.raises(HTTPException) as exc:
        await R.get_invitation("token-inexistant", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_invitations_refuse_si_pas_owner(db):
    cal = await _cal(db)
    with pytest.raises(HTTPException) as exc:
        await R.list_invitations(cal.id, db=db, user=MARINA)
    assert exc.value.status_code == 404
