"""Cartes de fidélité personnelles — /loyalty-cards (scope propriétaire)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import LoyaltyCard
from models.schemas import LoyaltyCardCreate, LoyaltyCardOut, LoyaltyCardUpdate
from utils.access import require_owned_card

router = APIRouter(prefix="/loyalty-cards", tags=["loyalty"])

_FORMATS = {"code128", "ean13", "qr"}


@router.get("", response_model=list[LoyaltyCardOut])
async def list_cards(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    rows = (await db.execute(
        select(LoyaltyCard).where(LoyaltyCard.user_id == user["sub"])
        .order_by(LoyaltyCard.enseigne))).scalars().all()
    return [LoyaltyCardOut.model_validate(c) for c in rows]


@router.post("", response_model=LoyaltyCardOut, status_code=status.HTTP_201_CREATED)
async def create_card(body: LoyaltyCardCreate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    fmt = body.format if body.format in _FORMATS else "code128"
    carte = LoyaltyCard(user_id=user["sub"], enseigne=body.enseigne, numero=body.numero,
                        format=fmt, couleur=body.couleur, note=body.note)
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    return LoyaltyCardOut.model_validate(carte)


@router.get("/{card_id}", response_model=LoyaltyCardOut)
async def get_card(card_id: str, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    carte = await require_owned_card(db, card_id, user["sub"])
    return LoyaltyCardOut.model_validate(carte)


@router.patch("/{card_id}", response_model=LoyaltyCardOut)
async def update_card(card_id: str, body: LoyaltyCardUpdate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    carte = await require_owned_card(db, card_id, user["sub"])
    data = body.model_dump(exclude_none=True)
    if "format" in data and data["format"] not in _FORMATS:
        raise HTTPException(status_code=422, detail="Format inconnu")
    for k, v in data.items():
        setattr(carte, k, v)
    await db.commit()
    await db.refresh(carte)
    return LoyaltyCardOut.model_validate(carte)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    carte = await require_owned_card(db, card_id, user["sub"])
    await db.delete(carte)
    await db.commit()
