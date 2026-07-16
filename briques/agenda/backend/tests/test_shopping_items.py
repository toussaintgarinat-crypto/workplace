"""Items : ajout (nom / catalog_item_id / anti-doublon), cochage, clear, delete, gating."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import CatalogItem, ShoppingList, ShoppingListMember
from models.schemas import ShoppingItemCreate, ShoppingItemUpdate
from routers import list_items as R

OWNER = {"sub": "perso"}
VIEWER = {"sub": "marina"}


async def _liste(db, kind="courses"):
    liste = ShoppingList(name="Maison", kind=kind, created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    return liste


@pytest.mark.asyncio
async def test_ajout_par_nom_memorise_catalogue(db):
    liste = await _liste(db)
    out = await R.add_item(liste.id, ShoppingItemCreate(name="Kombucha", rayon="Boissons", emoji="🍾"),
                           db=db, user=OWNER)
    assert out.name == "Kombucha" and out.checked is False
    from services.catalogue import catalogue_pour_liste
    cat = await catalogue_pour_liste(db, liste.id)
    assert any(c.name == "Kombucha" for c in cat)


@pytest.mark.asyncio
async def test_ajout_par_catalog_item_id(db):
    liste = await _liste(db)
    ci = CatalogItem(list_id=None, name="Lait", emoji="🥛", rayon="Crèmerie")
    db.add(ci)
    await db.commit()
    await db.refresh(ci)
    out = await R.add_item(liste.id, ShoppingItemCreate(catalog_item_id=ci.id), db=db, user=OWNER)
    assert out.name == "Lait" and out.emoji == "🥛" and out.rayon == "Crèmerie"


@pytest.mark.asyncio
async def test_anti_doublon_ne_recree_pas(db):
    liste = await _liste(db)
    await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=OWNER)
    await R.add_item(liste.id, ShoppingItemCreate(name="lait"), db=db, user=OWNER)
    items = await R.list_items(liste.id, db=db, user=OWNER)
    actifs = [i for i in items if not i.checked]
    assert len(actifs) == 1


@pytest.mark.asyncio
async def test_cocher_pose_checked_by(db):
    liste = await _liste(db)
    it = await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=OWNER)
    out = await R.update_item(liste.id, it.id, ShoppingItemUpdate(checked=True), db=db, user=OWNER)
    assert out.checked is True and out.checked_by == "perso" and out.checked_at is not None


@pytest.mark.asyncio
async def test_clear_checked(db):
    liste = await _liste(db)
    a = await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=OWNER)
    await R.update_item(liste.id, a.id, ShoppingItemUpdate(checked=True), db=db, user=OWNER)
    await R.add_item(liste.id, ShoppingItemCreate(name="Pain"), db=db, user=OWNER)
    await R.clear_checked(liste.id, db=db, user=OWNER)
    restants = await R.list_items(liste.id, db=db, user=OWNER)
    assert {i.name for i in restants} == {"Pain"}


@pytest.mark.asyncio
async def test_ajout_refuse_viewer(db):
    liste = await _liste(db)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="viewer"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=VIEWER)
    assert exc.value.status_code == 404
