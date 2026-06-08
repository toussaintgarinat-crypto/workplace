"""Router auth — profil + RGPD. Portage de routes/auth.ts (S127).

Monté sur /api/auth (+ /v1/api/auth). Protégé par get_current_user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Users
from app.serde import user_export, user_public

router = APIRouter()


class PatchMe(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=100)
    avatarEmoji: str | None = None


@router.patch("/me")
async def patch_me(body: PatchMe, user: UserContext = Depends(get_current_user)):
    updates: dict = {}
    if body.nom:
        updates["nom"] = body.nom.strip()
    if body.avatarEmoji:
        updates["avatar_emoji"] = body.avatarEmoji

    async with SessionLocal() as session:
        if updates:
            await session.execute(update(Users).where(Users.id == user.sub).values(**updates))
            await session.commit()
        row = (await session.execute(select(Users).where(Users.id == user.sub))).scalar_one()
        return {"user": user_public(row)}


@router.get("/me/export")
async def export_me(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as session:
        row = (await session.execute(select(Users).where(Users.id == user.sub))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    from datetime import datetime, timezone

    return {
        "user": user_export(row),
        "exportDate": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "note": "GDPR Export — Article 20 — Right to data portability",
    }


@router.delete("/me")
async def delete_me(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as session:
        await session.execute(
            update(Users)
            .where(Users.id == user.sub)
            .values(
                email=f"deleted_{user.sub}@rgpd.deleted",
                nom="[Deleted account]",
                avatar_emoji="❌",
                keycloak_sub=None,
            )
        )
        await session.commit()
    return {"ok": True}
