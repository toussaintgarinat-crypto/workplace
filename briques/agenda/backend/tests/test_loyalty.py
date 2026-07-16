"""Cartes de fidélité : CRUD isolé par propriétaire."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.schemas import LoyaltyCardCreate, LoyaltyCardUpdate
from routers import loyalty as R

MOI = {"sub": "perso"}
AUTRE = {"sub": "marina"}


@pytest.mark.asyncio
async def test_create_et_list_isole(db):
    await R.create_card(LoyaltyCardCreate(enseigne="Carrefour", numero="123"), db=db, user=MOI)
    await R.create_card(LoyaltyCardCreate(enseigne="Leclerc", numero="456"), db=db, user=AUTRE)
    miennes = await R.list_cards(db=db, user=MOI)
    assert {c.enseigne for c in miennes} == {"Carrefour"}


@pytest.mark.asyncio
async def test_get_autre_proprietaire_404(db):
    c = await R.create_card(LoyaltyCardCreate(enseigne="Carrefour", numero="123"), db=db, user=MOI)
    with pytest.raises(HTTPException) as exc:
        await R.get_card(c.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_et_delete(db):
    c = await R.create_card(LoyaltyCardCreate(enseigne="Carrefour", numero="123"), db=db, user=MOI)
    up = await R.update_card(c.id, LoyaltyCardUpdate(note="carte plastique"), db=db, user=MOI)
    assert up.note == "carte plastique"
    await R.delete_card(c.id, db=db, user=MOI)
    assert await R.list_cards(db=db, user=MOI) == []


@pytest.mark.asyncio
async def test_format_defaut_code128(db):
    c = await R.create_card(LoyaltyCardCreate(enseigne="X", numero="1"), db=db, user=MOI)
    assert c.format == "code128"
