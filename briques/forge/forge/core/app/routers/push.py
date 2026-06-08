"""Router push. Portage de routes/push.ts (S134). Monté /api, protégé.

Web Push (VAPID) — abonnements PWA et envoi de notifications. Remplace le paquet
npm ``web-push`` par ``pywebpush``. Les clés VAPID viennent de l'env ; si absentes,
``/push/send`` renvoie 503 (parité Bun).

Nettoyage des abonnements périmés : sur 404/410 du service de push, l'abonnement est
supprimé (le navigateur l'a révoqué), comme le Bun.
"""

from __future__ import annotations

import json
import logging
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, delete, select

from app.auth import UserContext, get_current_user
from app.config import settings
from app.db import SessionLocal
from app.models import PushSubscriptions
from app.serde import push_subscription, push_subscription_min

logger = logging.getLogger(__name__)
router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


class SubscribeBody(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class SendBody(BaseModel):
    userId: str
    title: str
    body: str
    url: str | None = None


@router.get("/push/subscriptions")
async def list_subscriptions(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(PushSubscriptions).where(PushSubscriptions.user_id == user.sub)
            )
        ).scalars().all()
    return [push_subscription_min(r) for r in rows]


@router.post("/push/subscribe", status_code=201)
async def subscribe(body: SubscribeBody, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        sub = PushSubscriptions(
            user_id=user.sub,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth=body.auth,
        )
        s.add(sub)
        await s.commit()
        await s.refresh(sub)
    return push_subscription(sub)


@router.delete("/push/subscriptions/{sub_id}")
async def unsubscribe(sub_id: str, user: UserContext = Depends(get_current_user)):
    sid = _uuid(sub_id)
    async with SessionLocal() as s:
        if sid is not None:
            await s.execute(
                delete(PushSubscriptions).where(
                    and_(
                        PushSubscriptions.id == sid,
                        PushSubscriptions.user_id == user.sub,
                    )
                )
            )
            await s.commit()
    return {"ok": True}


@router.post("/push/send")
async def send(body: SendBody, user: UserContext = Depends(get_current_user)):
    if not settings.VAPID_PUBLIC_KEY or not settings.VAPID_PRIVATE_KEY:
        raise HTTPException(status_code=503, detail="VAPID keys not configured")

    async with SessionLocal() as s:
        subs = (
            await s.execute(
                select(PushSubscriptions).where(PushSubscriptions.user_id == body.userId)
            )
        ).scalars().all()

    if not subs:
        return {"sent": 0}

    # Import paresseux : évite de charger pywebpush/cryptography au boot si push inutilisé.
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": body.title, "body": body.body, "url": body.url})
    vapid_claims = {"sub": settings.VAPID_EMAIL}
    stale_ids: list = []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims=dict(vapid_claims),  # pywebpush mute le dict (exp) → copie
            )
        except WebPushException as err:
            status = getattr(getattr(err, "response", None), "status_code", None)
            if status in (404, 410):
                stale_ids.append(sub.id)
        except Exception as err:  # erreur réseau / clé : on ne purge pas
            logger.warning("[push:send] %s", str(err)[:160])

    if stale_ids:
        async with SessionLocal() as s:
            await s.execute(
                delete(PushSubscriptions).where(PushSubscriptions.id.in_(stale_ids))
            )
            await s.commit()

    return {"sent": len(subs) - len(stale_ids)}
