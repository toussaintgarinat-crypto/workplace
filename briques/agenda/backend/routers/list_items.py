"""Items d'une liste — ajout, cochage, clear, delete. Émet SSE + push par personne."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import CatalogItem, ShoppingItem
from models.schemas import ShoppingItemCreate, ShoppingItemOut, ShoppingItemUpdate
from services.catalogue import memoriser_item_perso
from services.notifications import nom_affichable, notifier_membres
from services.pubsub import publish_list_change
from utils.access import require_list_access

router = APIRouter(prefix="/lists", tags=["list-items"])


def _out(item: ShoppingItem) -> ShoppingItemOut:
    return ShoppingItemOut.model_validate(item)


@router.get("/{list_id}/items", response_model=list[ShoppingItemOut])
async def list_items(list_id: str, db: AsyncSession = Depends(get_db),
                     user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="viewer")
    rows = (await db.execute(
        select(ShoppingItem).where(ShoppingItem.list_id == list_id)
        .order_by(ShoppingItem.checked, ShoppingItem.rayon, ShoppingItem.position))).scalars().all()
    return [_out(i) for i in rows]


@router.post("/{list_id}/items", response_model=ShoppingItemOut, status_code=status.HTTP_201_CREATED)
async def add_item(list_id: str, body: ShoppingItemCreate, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="editor")
    nom, emoji, rayon = body.name, body.emoji, body.rayon
    if body.catalog_item_id:
        ci = await db.get(CatalogItem, body.catalog_item_id)
        if ci is None:
            raise HTTPException(status_code=404, detail="Item de catalogue introuvable")
        nom, emoji, rayon = ci.name, ci.emoji, ci.rayon
    if not nom or not nom.strip():
        raise HTTPException(status_code=422, detail="Nom d'item requis")
    nom = nom.strip()

    # Anti-doublon façon Bring! : un item actif de même nom → on ne duplique pas.
    existant = (await db.execute(
        select(ShoppingItem).where(
            ShoppingItem.list_id == list_id,
            ShoppingItem.checked.is_(False),
            func.lower(ShoppingItem.name) == nom.lower(),
        ))).scalars().first()
    if existant is not None:
        item = existant
    else:
        item = ShoppingItem(list_id=list_id, name=nom, emoji=emoji, rayon=rayon,
                            note=body.note, added_by=user["sub"])
        db.add(item)
        await db.commit()
        await db.refresh(item)
        # Mémorise au catalogue perso si saisi à la main (pas depuis un item catalogue).
        if not body.catalog_item_id:
            await memoriser_item_perso(db, list_id, nom, emoji, rayon, user["sub"])

    await publish_list_change(list_id, "item.added", _out(item).model_dump(mode="json"))
    acteur = await nom_affichable(db, user["sub"])
    await notifier_membres(db, liste, user["sub"], f"🛒 {acteur} a ajouté {nom} à {liste.name}")
    return _out(item)


@router.patch("/{list_id}/items/{item_id}", response_model=ShoppingItemOut)
async def update_item(list_id: str, item_id: str, body: ShoppingItemUpdate,
                      db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="editor")
    item = await db.get(ShoppingItem, item_id)
    if item is None or item.list_id != list_id:
        raise HTTPException(status_code=404, detail="Item introuvable")
    data = body.model_dump(exclude_none=True)
    coche_transition = False
    if "checked" in data:
        if data["checked"] and not item.checked:
            item.checked_by = user["sub"]
            item.checked_at = datetime.utcnow()
            coche_transition = True
        elif not data["checked"]:
            item.checked_by = None
            item.checked_at = None
    for k, v in data.items():
        setattr(item, k, v)
    await db.commit()
    await db.refresh(item)

    if "checked" in data:
        evt = "item.checked" if item.checked else "item.unchecked"
    else:
        evt = "item.updated"
    await publish_list_change(list_id, evt, _out(item).model_dump(mode="json"))
    if coche_transition:
        acteur = await nom_affichable(db, user["sub"])
        await notifier_membres(db, liste, user["sub"], f"✅ {acteur} a coché {item.name}")
    return _out(item)


@router.delete("/{list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(list_id: str, item_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="editor")
    item = await db.get(ShoppingItem, item_id)
    if item is None or item.list_id != list_id:
        raise HTTPException(status_code=404, detail="Item introuvable")
    await db.delete(item)
    await db.commit()
    await publish_list_change(list_id, "item.deleted", {"id": item_id})


@router.post("/{list_id}/items/clear-checked", status_code=status.HTTP_200_OK)
async def clear_checked(list_id: str, db: AsyncSession = Depends(get_db),
                        user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="editor")
    coches = (await db.execute(
        select(ShoppingItem).where(
            ShoppingItem.list_id == list_id, ShoppingItem.checked.is_(True)))).scalars().all()
    n = len(coches)
    for it in coches:
        await db.delete(it)
    await db.commit()
    await publish_list_change(list_id, "checked.cleared", {"count": n})
    return {"cleared": n}
