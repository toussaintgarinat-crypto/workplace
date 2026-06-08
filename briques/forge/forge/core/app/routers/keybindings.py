"""Router keybindings (raccourcis clavier). Portage de routes/keybindings.ts (S135).

Monté /api, protégé. CRUD minimal par utilisateur avec upsert sur (userId, touche).
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Keybindings
from app.serde import keybinding

router = APIRouter()


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/keybindings", dependencies=[Depends(get_current_user)])
async def list_keybindings(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Keybindings).where(Keybindings.user_id == user.sub)
        )).scalars().all()
    return [keybinding(r) for r in rows]


class UpsertKeybinding(BaseModel):
    touche: str = Field(min_length=1)
    action: str = Field(min_length=1)


@router.put("/keybindings", dependencies=[Depends(get_current_user)])
async def upsert_keybinding(body: UpsertKeybinding, response: Response,
                            user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(Keybindings).where(and_(
                Keybindings.user_id == user.sub, Keybindings.touche == body.touche,
            )).limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            await s.execute(
                update(Keybindings).where(Keybindings.id == existing.id).values(action=body.action)
            )
            await s.commit()
            await s.refresh(existing)
            return keybinding(existing)
        row = Keybindings(user_id=user.sub, touche=body.touche, action=body.action)
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return keybinding(row)


@router.delete("/keybindings/{kid}", dependencies=[Depends(get_current_user)])
async def delete_keybinding(kid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(kid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(Keybindings).where(and_(
                Keybindings.id == u, Keybindings.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}
