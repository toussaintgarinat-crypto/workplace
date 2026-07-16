"""Contrôle d'accès listes (owner/editor/viewer) + cartes (propriétaire)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import LoyaltyCard, ShoppingList, ShoppingListMember
from utils.access import get_list_role, require_list_access, require_owned_card


async def _liste(db, created_by="perso"):
    liste = ShoppingList(name="Maison", created_by=created_by)
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    return liste


@pytest.mark.asyncio
async def test_createur_est_owner(db):
    liste = await _liste(db)
    assert await get_list_role(db, liste.id, "perso") == "owner"


@pytest.mark.asyncio
async def test_membre_a_son_role(db):
    liste = await _liste(db)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    assert await get_list_role(db, liste.id, "marina") == "editor"


@pytest.mark.asyncio
async def test_sans_acces_none(db):
    liste = await _liste(db)
    assert await get_list_role(db, liste.id, "inconnu") is None


@pytest.mark.asyncio
async def test_require_refuse_role_insuffisant(db):
    liste = await _liste(db)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="viewer"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await require_list_access(db, liste.id, "marina", min_role="editor")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_carte_isolee_par_proprietaire(db):
    carte = LoyaltyCard(user_id="perso", enseigne="Carrefour", numero="123")
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    assert (await require_owned_card(db, carte.id, "perso")).id == carte.id
    with pytest.raises(HTTPException) as exc:
        await require_owned_card(db, carte.id, "autre")
    assert exc.value.status_code == 404
