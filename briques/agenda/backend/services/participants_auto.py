"""Auto-participant (S174) : garantit qu'un utilisateur est participant d'un event.
Sans commit (l'appelant commite) → composable dans la transaction de création d'event."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import EventParticipant


async def assurer_participant(db: AsyncSession, event_id: str, user_id: str,
                              status: str = "accepted") -> None:
    """Ajoute (si absent) un participant pour cet event. Idempotent, ne commite pas."""
    existe = (await db.execute(
        select(EventParticipant.id).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == user_id,
        )
    )).scalar_one_or_none()
    if existe is None:
        db.add(EventParticipant(event_id=event_id, user_id=user_id, status=status))
