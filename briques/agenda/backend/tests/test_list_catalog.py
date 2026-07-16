"""Catalogue d'une liste, groupé et ordonné par rayon."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import ShoppingList
from routers import list_catalog as R
from services.catalogue import semer_catalogue

OWNER = {"sub": "perso"}
INCONNU = {"sub": "zzz"}


@pytest.mark.asyncio
async def test_catalog_groupe_par_rayon(db):
    await semer_catalogue(db)
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    out = await R.get_catalog(liste.id, db=db, user=OWNER)
    rayons = [g["rayon"] for g in out["rayons"]]
    assert rayons[0] == "Fruits & légumes"  # ordre RAYONS
    assert all(g["items"] for g in out["rayons"])  # pas de rayon vide


@pytest.mark.asyncio
async def test_catalog_refuse_sans_acces(db):
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    with pytest.raises(HTTPException) as exc:
        await R.get_catalog(liste.id, db=db, user=INCONNU)
    assert exc.value.status_code == 404
