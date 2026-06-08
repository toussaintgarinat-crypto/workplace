"""Router social (comptes réseaux sociaux). Portage de routes/social.ts (S135).

Monté /api, protégé. Comptes rattachés à un pôle. Chaque compte est enrichi d'un
``meta`` (label/emoji/couleur de la plateforme) issu de la table PLATFORMS.
``config`` est stocké en TEXT JSON (renvoyé brut comme Drizzle).
"""

from __future__ import annotations

import json
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import SocialAccounts
from app.serde import social_account

router = APIRouter()

PLATFORMS: dict[str, dict[str, str]] = {
    "instagram": {"label": "Instagram",   "emoji": "📸", "color": "#e1306c"},
    "linkedin":  {"label": "LinkedIn",    "emoji": "💼", "color": "#0077b5"},
    "facebook":  {"label": "Facebook",    "emoji": "📘", "color": "#1877f2"},
    "twitter":   {"label": "X / Twitter", "emoji": "🐦", "color": "#000000"},
    "tiktok":    {"label": "TikTok",      "emoji": "🎵", "color": "#ff0050"},
    "youtube":   {"label": "YouTube",     "emoji": "▶️", "color": "#ff0000"},
    "bluesky":   {"label": "Bluesky",     "emoji": "🦋", "color": "#0085ff"},
    "pinterest": {"label": "Pinterest",   "emoji": "📌", "color": "#e60023"},
    "threads":   {"label": "Threads",     "emoji": "🧵", "color": "#000000"},
    "mastodon":  {"label": "Mastodon",    "emoji": "🐘", "color": "#6364ff"},
}


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _with_meta(row, default: dict) -> dict:
    out = social_account(row)
    out["meta"] = PLATFORMS.get(row.platform, default)
    return out


@router.get("/social/platforms", dependencies=[Depends(get_current_user)])
async def list_platforms():
    return PLATFORMS


@router.get("/poles/{pole_id}/social", dependencies=[Depends(get_current_user)])
async def list_social(pole_id: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(SocialAccounts).where(and_(
                SocialAccounts.pole_id == u, SocialAccounts.user_id == user.sub,
            )).order_by(desc(SocialAccounts.created_at))
        )).scalars().all() if u else []
    return [_with_meta(r, {"label": r.platform, "emoji": "🌐", "color": "#64748b"}) for r in rows]


class CreateSocial(BaseModel):
    platform: str = Field(min_length=1)
    nom: str = Field(min_length=1, max_length=200)
    config: dict[str, str] | None = None


@router.post("/poles/{pole_id}/social", dependencies=[Depends(get_current_user)])
async def create_social(pole_id: str, body: CreateSocial, response: Response,
                        user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        row = SocialAccounts(
            pole_id=_uuid(pole_id), user_id=user.sub,
            platform=body.platform, nom=body.nom,
            config=json.dumps(body.config or {}),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return _with_meta(row, {})


@router.patch("/social/{sid}", dependencies=[Depends(get_current_user)])
async def update_social(sid: str, body: dict, user: UserContext = Depends(get_current_user)):
    u = _uuid(sid)
    updates: dict = {}
    if body.get("nom") is not None:
        updates["nom"] = body["nom"]
    if body.get("actif") is not None:
        updates["actif"] = body["actif"]
    if body.get("config") is not None:
        updates["config"] = json.dumps(body["config"])
    async with SessionLocal() as s:
        if u and updates:
            await s.execute(
                update(SocialAccounts).where(and_(
                    SocialAccounts.id == u, SocialAccounts.user_id == user.sub,
                )).values(**updates)
            )
            await s.commit()
        row = (await s.execute(
            select(SocialAccounts).where(and_(
                SocialAccounts.id == u, SocialAccounts.user_id == user.sub,
            ))
        )).scalar_one_or_none() if u else None
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _with_meta(row, {})


@router.delete("/social/{sid}", dependencies=[Depends(get_current_user)])
async def delete_social(sid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(sid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(SocialAccounts).where(and_(
                SocialAccounts.id == u, SocialAccounts.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}
