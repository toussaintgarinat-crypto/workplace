"""ORM listes + cartes : insertion, contraintes, cascade (SQLite create_all)."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.orm import (
    CatalogItem,
    LoyaltyCard,
    ShoppingItem,
    ShoppingList,
    ShoppingListInvitation,
    ShoppingListMember,
)


@pytest.mark.asyncio
async def test_creer_liste_defaut_courses(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    assert liste.id
    assert liste.kind == "courses"


@pytest.mark.asyncio
async def test_membre_unique_par_liste(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="viewer"))
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_cascade_supprime_items_et_membres(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    db.add(ShoppingItem(list_id=liste.id, name="Lait", added_by="perso"))
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    await db.delete(liste)
    await db.commit()
    items = (await db.execute(select(ShoppingItem))).scalars().all()
    membres = (await db.execute(select(ShoppingListMember))).scalars().all()
    assert items == [] and membres == []


@pytest.mark.asyncio
async def test_catalog_item_integre_sans_liste(db):
    db.add(CatalogItem(list_id=None, name="Lait", emoji="🥛", rayon="Crèmerie"))
    await db.commit()
    row = (await db.execute(select(CatalogItem))).scalar_one()
    assert row.list_id is None and row.created_by is None


@pytest.mark.asyncio
async def test_loyalty_card_defaut_code128(db):
    carte = LoyaltyCard(user_id="perso", enseigne="Carrefour", numero="1234567890")
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    assert carte.format == "code128" and carte.couleur == "#3B82F6"
