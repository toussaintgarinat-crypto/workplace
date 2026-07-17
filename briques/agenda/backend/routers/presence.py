"""Présence éphémère (S179) : partager/arrêter/lister sa position. L'identité est TOUJOURS
`user["sub"]` (jamais le corps) — motif anti-usurpation S178. `scope=event` exige que
l'appelant soit participant de l'event et calque l'expiration sur la fin de l'event."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, EventParticipant
from services import presence
from services.pubsub import publish_presence_change

router = APIRouter(tags=["presence"])

TTL_DEFAUT_MIN = 60
TTL_MAX_MIN = 1440


class PresenceEntree(BaseModel):
    lat: float
    lon: float
    accuracy: float | None = None
    label: str | None = None
    scope: str = "famille"
    event_id: str | None = None
    ttl_minutes: int | None = None


@router.post("/presence")
async def partager(body: PresenceEntree, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    """Partage (ou rafraîchit) ma position. `scope=famille` (défaut) : visible de tous,
    expire après `ttl_minutes` (défaut 60, borné). `scope=event` : visible des participants,
    expire à la fin de l'event."""
    uid = user["sub"]
    if body.scope == "event":
        if not body.event_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="event_id requis pour scope=event")
        evt = await db.get(Event, body.event_id)
        if evt is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement introuvable")
        part = (await db.execute(select(EventParticipant).where(
            EventParticipant.event_id == body.event_id,
            EventParticipant.user_id == uid))).scalar_one_or_none()
        if part is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Non participant de cet événement")
        expires_at, scope, event_id = evt.end_at, "event", body.event_id
    else:
        ttl = body.ttl_minutes or TTL_DEFAUT_MIN
        ttl = max(1, min(ttl, TTL_MAX_MIN))
        expires_at, scope, event_id = datetime.utcnow() + timedelta(minutes=ttl), "famille", None

    await presence.upsert_position(db, uid, latitude=body.lat, longitude=body.lon,
                                   expires_at=expires_at, accuracy_m=body.accuracy,
                                   label=body.label, scope=scope, event_id=event_id)
    await publish_presence_change("shared", {"user_id": uid})
    return {"ok": True}


@router.delete("/presence")
async def arreter(db: AsyncSession = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    """Arrête de partager ma position (coupure 1-clic)."""
    await presence.supprimer_position(db, user["sub"])
    await publish_presence_change("stopped", {"user_id": user["sub"]})
    return {"ok": True}


@router.get("/presence")
async def lister(db: AsyncSession = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    """Positions non expirées visibles par moi (famille + events où je participe)."""
    return await presence.positions_visibles(db, user["sub"])
