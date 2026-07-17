"""Profils affichables — /profiles (S174). POST /profiles/me sème le profil de l'appelant
depuis les claims de son token ; GET /profiles résout une liste de user_ids en noms."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import UserProfile
from models.schemas import NotifPrefsEntree, ProfileOut
from services import profils

router = APIRouter(tags=["profiles"])


@router.post("/profiles/me", response_model=ProfileOut)
async def upsert_me(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Enregistre/rafraîchit le profil de l'appelant depuis les claims de son token
    (name > preferred_username > sub, + email si présent). Appelé par l'appli /app
    juste après le login."""
    nom = user.get("name") or user.get("preferred_username") or user["sub"]
    return await profils.upsert(db, user["sub"], nom, email=user.get("email"))


@router.get("/profiles", response_model=list[ProfileOut])
async def list_profiles(
    user_ids: str = Query(..., description="user_ids séparés par des virgules"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Résout une liste de user_ids en {user_id, display_name, avatar_color} (défauts
    pour les inconnus). Alimente présence / chat / rappels côté dashboard."""
    ids = [u for u in user_ids.split(",") if u]
    resolus = await profils.resoudre(db, ids)
    return [ProfileOut(**p) for p in resolus.values()]


@router.patch("/profiles/me/notifs")
async def patch_notifs(
    body: NotifPrefsEntree,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Met à jour les préférences de digest de l'appelant (cadence, push, email,
    heures calmes). Seuls les champs fournis sont modifiés ; le profil est créé
    (semé depuis les claims) s'il n'existe pas encore."""
    prof = await db.get(UserProfile, user["sub"])
    if prof is None:
        nom = user.get("name") or user.get("preferred_username") or user["sub"]
        prof = await profils.upsert(db, user["sub"], nom, email=user.get("email"))
    for champ in ("digest_cadence", "digest_push", "digest_email", "heures_calmes"):
        val = getattr(body, champ)
        if val is not None:
            setattr(prof, champ, val)
    await db.commit()
    await db.refresh(prof)
    return {
        "digest_cadence": prof.digest_cadence,
        "digest_push": prof.digest_push,
        "digest_email": prof.digest_email,
        "heures_calmes": prof.heures_calmes,
    }
