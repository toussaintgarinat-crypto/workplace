"""CRUD étiquettes nommées (catégories) — /calendars/{cal_id}/labels et /labels/{id}.

Miroir de `routers/calendars.py` pour le contrôle d'accès (`require_calendar_access`).
Une étiquette appartient à un calendrier ; lire = viewer, créer/modifier/supprimer = editor.
Supprimer une étiquette ne supprime pas les événements : ils repassent « sans étiquette »
(label_id remis à NULL), indépendamment du PRAGMA foreign_keys de SQLite.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, Label
from models.schemas import LabelCreate, LabelOut, LabelUpdate
from utils.access import require_calendar_access

router = APIRouter(tags=["labels"])


@router.get("/calendars/{cal_id}/labels", response_model=list[LabelOut])
async def list_labels(
    cal_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="viewer")
    res = await db.execute(
        select(Label).where(Label.calendar_id == cal_id).order_by(Label.name)
    )
    return res.scalars().all()


@router.post("/calendars/{cal_id}/labels", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
async def create_label(
    cal_id: str,
    body: LabelCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="editor")
    label = Label(calendar_id=cal_id, name=body.name, color=body.color)
    db.add(label)
    await db.commit()
    await db.refresh(label)
    return label


@router.patch("/labels/{label_id}", response_model=LabelOut)
async def update_label(
    label_id: str,
    body: LabelUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    label = await db.get(Label, label_id)
    if not label:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
    await require_calendar_access(db, label.calendar_id, user["sub"], min_role="editor")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(label, k, v)
    await db.commit()
    await db.refresh(label)
    return label


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    label_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    label = await db.get(Label, label_id)
    if not label:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
    await require_calendar_access(db, label.calendar_id, user["sub"], min_role="editor")
    # Détache l'étiquette des événements avant de la supprimer (garantit le « SET NULL »
    # même si les contraintes FK ne sont pas appliquées par le moteur SQLite).
    await db.execute(update(Event).where(Event.label_id == label_id).values(label_id=None))
    await db.delete(label)
    await db.commit()
