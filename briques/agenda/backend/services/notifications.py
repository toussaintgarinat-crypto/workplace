"""Push par personne (S176) : la brique émet directement vers le pont `connexion`
(/pousser) sur ajout/cochage d'item. Best-effort — ne lève jamais, no-op si le pont
n'est pas configuré. Réutilise le contrat de `_pousser_messagerie` du Cœur (S174)."""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.orm import ShoppingList, ShoppingListMember, UserProfile

logger = logging.getLogger(__name__)


async def nom_affichable(db: AsyncSession, user_id: str) -> str:
    """Nom lisible d'un user via UserProfile (S174), repli sur l'id brut."""
    prof = await db.get(UserProfile, user_id)
    return prof.display_name if prof else user_id


async def _membres_uids(db: AsyncSession, liste: ShoppingList) -> set[str]:
    """Tous les user_id concernés : créateur + membres."""
    res = await db.execute(
        select(ShoppingListMember.user_id).where(ShoppingListMember.list_id == liste.id)
    )
    uids = {row[0] for row in res.all()}
    uids.add(liste.created_by)
    return uids


async def notifier_membres(
    db: AsyncSession, liste: ShoppingList, acteur_id: str, texte: str
) -> int:
    """POST best-effort vers connexion /pousser pour chaque membre SAUF l'acteur.
    Renvoie le nb de push tentés. Ne lève jamais."""
    if not settings.CONNEXION_URL:
        return 0
    cibles = await _membres_uids(db, liste)
    cibles.discard(acteur_id)
    if not cibles:
        return 0
    entetes = {}
    if settings.CONNEXION_KEY:
        entetes["X-API-Key"] = settings.CONNEXION_KEY
    base = settings.CONNEXION_URL.rstrip("/")
    n = 0
    for uid in cibles:
        corps = {"utilisateur": uid, "texte": texte}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{base}/pousser", json=corps, headers=entetes)
            n += 1
        except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
            logger.warning("Push liste vers %s échoué : %s", uid, exc)
    return n
