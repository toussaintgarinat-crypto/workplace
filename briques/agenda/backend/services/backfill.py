"""Backfill idempotent (S174) : garantit que chaque événement a au moins un participant
(son créateur, accepté). Rend le modèle « destinataire = participant » uniforme pour les
événements créés avant S174. Appelé au démarrage (lifespan) ; une fois posé, re-run = 0.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Event, EventParticipant


async def creer_participants_createurs(db: AsyncSession) -> int:
    """Pour chaque event sans AUCUN participant, crée un participant créateur (accepté,
    rappels=None → hérite du défaut de l'event). Renvoie le nombre de lignes créées."""
    avec_participant = set(
        (await db.execute(select(EventParticipant.event_id).distinct())).scalars().all()
    )
    events = (await db.execute(select(Event))).scalars().all()
    cree = 0
    for e in events:
        if e.id in avec_participant:
            continue
        db.add(EventParticipant(id=str(uuid.uuid4()), event_id=e.id,
                                user_id=e.created_by, status="accepted", rappels=None))
        cree += 1
    if cree:
        await db.commit()
    return cree
