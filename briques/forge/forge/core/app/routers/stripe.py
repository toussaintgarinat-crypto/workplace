"""Router stripe. Portage de routes/stripe.ts (S131). Monté /api, protégé.

Plans, abonnement courant, checkout (mock) et webhook. Aucun SDK Stripe réel :
le checkout fabrique un sessionId factice et trace un paiement 'pending', le
webhook le passe à 'complete' — fidèle au comportement du Bun.
"""

from __future__ import annotations

import datetime
import random
import string
import time
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, update

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import Abonnements, StripePayments
from app.serde import abonnement, stripe_payment

router = APIRouter()

PLANS = {
    "free": {"prix": 0, "features": ["5 sessions/mois", "2 pôles", "LLM local"]},
    "starter": {"prix": 29, "features": ["100 sessions/mois", "5 pôles", "Multi-LLM", "KB"]},
    "pro": {"prix": 99, "features": ["Illimité", "Tous pôles", "Agents avancés", "API"]},
    "enterprise": {"prix": 299, "features": ["Illimité", "SSO", "SLA", "Support dédié"]},
}


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/stripe/plans", dependencies=[Depends(get_current_user)])
async def get_plans():
    return PLANS


@router.get("/stripe/abonnement")
async def get_abonnement(org_id: str = Depends(require_org)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        abo = (await s.execute(
            select(Abonnements).where(Abonnements.org_id == oid).limit(1)
        )).scalar_one_or_none()
    return abonnement(abo) if abo else {"plan": "free", "statut": "actif"}


class CheckoutBody(BaseModel):
    plan: str


@router.post("/stripe/checkout")
async def checkout(
    body: CheckoutBody,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    if body.plan not in ("starter", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=11))
    session_id = f"cs_{int(time.time() * 1000)}_{rand}"
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        s.add(StripePayments(
            org_id=oid, user_id=user.sub, stripe_session_id=session_id,
            montant=PLANS[body.plan]["prix"] * 100, statut="pending",
        ))
        await s.commit()
    return {"sessionId": session_id, "checkoutUrl": f"https://checkout.stripe.com/pay/{session_id}"}


@router.post("/stripe/webhook", dependencies=[Depends(get_current_user)])
async def webhook(request: Request):
    body = await request.json()
    if body.get("type") == "checkout.session.completed":
        session_id = (body.get("data") or {}).get("object", {}).get("id")
        if session_id:
            async with SessionLocal() as s:
                await s.execute(
                    update(StripePayments)
                    .where(StripePayments.stripe_session_id == session_id)
                    .values(statut="complete", completed_at=datetime.datetime.utcnow())
                )
                await s.commit()
    return {"received": True}


@router.get("/stripe/payments", dependencies=[Depends(get_current_user)])
async def list_payments(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(StripePayments).where(StripePayments.user_id == user.sub)
            .order_by(desc(StripePayments.created_at))
        )).scalars().all()
    return [stripe_payment(p) for p in rows]
