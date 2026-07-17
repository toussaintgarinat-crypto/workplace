"""Abonnement webcal (S179) : jeton ICS par utilisateur (capacité), stocké sur
`UserProfile.ics_token`. Génération/révocation + construction des URLs. Le jeton est la
SEULE porte du flux `.ics` (lecture seule) — régénérer invalide instantanément l'ancien."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import UserProfile
from services import profils


def _nouveau_token() -> str:
    return secrets.token_urlsafe(32)


async def _profil(db: AsyncSession, user_id: str) -> UserProfile:
    prof = await db.get(UserProfile, user_id)
    if prof is None:
        prof = await profils.upsert(db, user_id, profils.nom_affiche(user_id, None))
    return prof


async def obtenir_ou_creer_token(db: AsyncSession, user_id: str) -> str:
    prof = await _profil(db, user_id)
    if not prof.ics_token:
        prof.ics_token = _nouveau_token()
        await db.commit()
        await db.refresh(prof)
    return prof.ics_token


async def regenerer_token(db: AsyncSession, user_id: str) -> str:
    prof = await _profil(db, user_id)
    prof.ics_token = _nouveau_token()
    await db.commit()
    await db.refresh(prof)
    return prof.ics_token


async def user_pour_token(db: AsyncSession, token: str) -> str | None:
    if not token:
        return None
    prof = (await db.execute(
        select(UserProfile).where(UserProfile.ics_token == token))).scalar_one_or_none()
    return prof.user_id if prof else None


def url_https(base: str, token: str) -> str:
    return f"{base.rstrip('/')}/ics/{token}.ics"


def url_webcal(base: str, token: str) -> str:
    b = base.rstrip("/")
    for prefixe in ("https://", "http://"):
        if b.startswith(prefixe):
            b = b[len(prefixe):]
            break
    return f"webcal://{b}/ics/{token}.ics"
