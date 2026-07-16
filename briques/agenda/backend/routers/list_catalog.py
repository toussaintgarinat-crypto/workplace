"""Catalogue tap-to-add d'une liste, groupé par rayon — /lists/{id}/catalog."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.schemas import CatalogItemOut
from services.catalogue import RAYONS, catalogue_pour_liste
from utils.access import require_list_access

router = APIRouter(prefix="/lists", tags=["list-catalog"])


@router.get("/{list_id}/catalog")
async def get_catalog(list_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="viewer")
    items = await catalogue_pour_liste(db, list_id)
    par_rayon: dict[str, list] = {}
    for ci in items:
        par_rayon.setdefault(ci.rayon, []).append(CatalogItemOut.model_validate(ci))
    groupes = []
    for rayon in RAYONS:
        if par_rayon.get(rayon):
            items_tries = sorted(par_rayon[rayon], key=lambda c: c.name.lower())
            groupes.append({"rayon": rayon, "items": items_tries})
    return {"rayons": groupes}
