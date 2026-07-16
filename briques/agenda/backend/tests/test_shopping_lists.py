"""CRUD listes + membres + invitations (accept/expiré/rejoué)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from models.orm import ShoppingItem, ShoppingListInvitation, ShoppingListMember
from models.schemas import ListInvitationCreate, ShoppingListCreate
from routers import lists as R

OWNER = {"sub": "perso"}
AUTRE = {"sub": "marina"}


@pytest.mark.asyncio
async def test_create_puis_owner(db):
    out = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    assert out.role == "owner" and out.kind == "courses"


@pytest.mark.asyncio
async def test_list_lists_compte_a_prendre(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    db.add(ShoppingItem(list_id=liste.id, name="Lait", added_by="perso", checked=False))
    db.add(ShoppingItem(list_id=liste.id, name="Pain", added_by="perso", checked=True))
    await db.commit()
    mes = await R.list_lists(db=db, user=OWNER)
    assert mes[0].nb_a_prendre == 1


@pytest.mark.asyncio
async def test_delete_exige_owner(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.delete_list(liste.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_invitation_accept_rejoint(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    inv = await R.invite_to_list(liste.id, ListInvitationCreate(role="editor"), db=db, user=OWNER)
    await R.accept_list_invitation(inv["token"], db=db, user=AUTRE)
    from utils.access import get_list_role
    assert await get_list_role(db, liste.id, "marina") == "editor"


@pytest.mark.asyncio
async def test_invitation_expiree_refusee(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    inv = ShoppingListInvitation(
        list_id=liste.id, role="editor", created_by="perso",
        expires_at=datetime.utcnow() - timedelta(hours=1))
    db.add(inv)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.accept_list_invitation(inv.token, db=db, user=AUTRE)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_invitation_rejouee_refusee(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    inv = await R.invite_to_list(liste.id, ListInvitationCreate(role="viewer"), db=db, user=OWNER)
    await R.accept_list_invitation(inv["token"], db=db, user=AUTRE)
    with pytest.raises(HTTPException) as exc:
        await R.accept_list_invitation(inv["token"], db=db, user={"sub": "autre2"})
    assert exc.value.status_code == 410
