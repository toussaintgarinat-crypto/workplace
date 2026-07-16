"""Catalogue FR : seed idempotent, union intégré+perso, mémorisation dédupliquée."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from models.orm import CatalogItem, ShoppingList
from services.catalogue import (
    RAYONS,
    catalogue_pour_liste,
    memoriser_item_perso,
    semer_catalogue,
)


@pytest.mark.asyncio
async def test_seed_insere_puis_idempotent(db):
    n1 = await semer_catalogue(db)
    assert n1 > 0
    n2 = await semer_catalogue(db)
    assert n2 == 0
    total = (await db.execute(select(CatalogItem))).scalars().all()
    assert len(total) == n1
    assert all(c.rayon in RAYONS for c in total)


@pytest.mark.asyncio
async def test_catalogue_union_integre_et_perso(db):
    await semer_catalogue(db)
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    db.add(CatalogItem(list_id=liste.id, name="Kombucha", emoji="🍾", rayon="Boissons", created_by="perso"))
    await db.commit()
    cat = await catalogue_pour_liste(db, liste.id)
    noms = {c.name for c in cat}
    assert "Kombucha" in noms and "Lait" in noms  # Lait vient des intégrés


@pytest.mark.asyncio
async def test_memoriser_dedup(db):
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    a = await memoriser_item_perso(db, liste.id, "Yaourt soja", "🥛", "Crèmerie", "perso")
    b = await memoriser_item_perso(db, liste.id, "yaourt soja", "🥛", "Crèmerie", "perso")
    assert a is not None and b is None  # 2e = déjà présent (dédup insensible à la casse)
