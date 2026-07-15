"""Profils affichables (S174) : résout un user_id (sub Keycloak / « perso ») en nom +
couleur, semé au login depuis les claims du token. Résolution 100 % locale."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.orm import UserProfile

# Même palette que le front (templates_app.COULEURS) — pastilles cohérentes UI/back.
PALETTE = ["#5865F2", "#3B82F6", "#22c55e", "#eab308", "#f97316", "#ef4444", "#ec4899", "#a855f7"]


def couleur_pour(user_id: str) -> str:
    """Couleur de pastille déterministe pour un user_id (hash stable → palette)."""
    h = int(hashlib.md5(user_id.encode("utf-8")).hexdigest(), 16)
    return PALETTE[h % len(PALETTE)]


def nom_affiche(user_id: str, profil: UserProfile | None) -> str:
    """Nom lisible : profil connu > « Toi » pour le propriétaire local > user_id brut."""
    if profil and profil.display_name:
        return profil.display_name
    if user_id == settings.AGENDA_USER_ID:
        return "Toi"
    return user_id


async def upsert(db: AsyncSession, user_id: str, display_name: str,
                 avatar_color: str | None = None) -> UserProfile:
    """Crée ou met à jour le profil d'un utilisateur (nom + couleur)."""
    prof = await db.get(UserProfile, user_id)
    couleur = avatar_color or couleur_pour(user_id)
    if prof is None:
        prof = UserProfile(user_id=user_id, display_name=display_name, avatar_color=couleur)
        db.add(prof)
    else:
        prof.display_name = display_name
        if avatar_color:
            prof.avatar_color = avatar_color
    await db.commit()
    await db.refresh(prof)
    return prof


async def resoudre(db: AsyncSession, user_ids: list[str]) -> dict[str, dict]:
    """{user_id: {user_id, display_name, avatar_color}} pour chaque id, avec défauts
    pour les inconnus (« Toi » pour le propriétaire, sinon id brut ; couleur dérivée)."""
    uniques = list(dict.fromkeys(user_ids))
    if not uniques:
        return {}
    rows = (await db.execute(
        select(UserProfile).where(UserProfile.user_id.in_(uniques))
    )).scalars().all()
    connus = {p.user_id: p for p in rows}
    res: dict[str, dict] = {}
    for uid in uniques:
        p = connus.get(uid)
        res[uid] = {"user_id": uid, "display_name": nom_affiche(uid, p),
                    "avatar_color": p.avatar_color if p else couleur_pour(uid)}
    return res
