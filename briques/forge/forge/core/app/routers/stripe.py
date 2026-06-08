"""Router stripe — paiement en ligne RÉEL (S21, remplace le mock S131).

Avant (mock) : `checkout` fabriquait un sessionId factice et le webhook marquait
le paiement `complete` **sans vérifier la signature** — n'importe qui pouvait le
déclencher. Désormais :

- **Checkout réel** via le SDK Stripe officiel si une clé secrète est résolue
  (coffre chiffré `ProviderApiKeys`/`crypto` → repli env `STRIPE_SECRET_KEY`).
  Sans clé : dégradation **honnête** en `mode: "mock"` (jamais de faux encaissement).
- **Webhook à signature vérifiée** : public (Stripe n'envoie pas de token Keycloak)
  mais `stripe.Webhook.construct_event` valide la signature `Stripe-Signature`
  contre `STRIPE_WEBHOOK_SECRET`. Signature absente/falsifiée/corps trafiqué → 400.

La clé n'apparaît jamais en clair : chiffrée au repos (AES-256-GCM, `crypto.py`),
masquée dans les logs (`mask_key`).
"""

from __future__ import annotations

import datetime
import logging
import random
import string
import time
import uuid as uuidlib

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, update

from app.auth import UserContext, get_current_user, require_org
from app.config import settings
from app.crypto import decrypt, mask_key
from app.db import SessionLocal
from app.models import Abonnements, ProviderApiKeys, StripePayments
from app.serde import abonnement, stripe_payment

router = APIRouter()
log = logging.getLogger("forge.stripe")

PLANS = {
    "free": {"prix": 0, "features": ["5 sessions/mois", "2 pôles", "LLM local"]},
    "starter": {"prix": 29, "features": ["100 sessions/mois", "5 pôles", "Multi-LLM", "KB"]},
    "pro": {"prix": 99, "features": ["Illimité", "Tous pôles", "Agents avancés", "API"]},
    "enterprise": {"prix": 299, "features": ["Illimité", "SSO", "SLA", "Support dédié"]},
}
_PLANS_PAYANTS = {"starter", "pro", "enterprise"}


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


# ── Résolution de la clé secrète : coffre chiffré → env ────────────────────────

async def resolve_stripe_key() -> str | None:
    """Clé secrète Stripe : d'abord chiffrée en base (`ProviderApiKeys`, provider
    `stripe`), sinon repli env `STRIPE_SECRET_KEY`. Jamais loggée en clair.

    Workplace est mono-propriétaire : la clé est account-wide, on prend la ligne
    `stripe` la plus récente quel que soit le `user_id` (une seule identité de
    service traverse l'adaptateur — cf. dette d'identité S20). Une clé corrompue
    retombe sur l'env plutôt que de planter l'encaissement.
    """
    async with SessionLocal() as s:
        row = (await s.execute(
            select(ProviderApiKeys)
            .where(ProviderApiKeys.provider == "stripe")
            .order_by(desc(ProviderApiKeys.updated_at))
            .limit(1)
        )).scalar_one_or_none()
    if row and row.encrypted_key:
        try:
            return decrypt(row.encrypted_key)
        except Exception:  # noqa: BLE001 — clé corrompue → repli env
            log.warning("Clé Stripe en base illisible (déchiffrement échoué), repli sur l'env.")
    return settings.STRIPE_SECRET_KEY or None


@router.get("/stripe/plans", dependencies=[Depends(get_current_user)])
async def get_plans():
    return PLANS


@router.get("/stripe/etat")
async def get_etat(_: UserContext = Depends(get_current_user)):
    """État honnête de la configuration paiement : Stripe réel vs mode mock.

    Ne renvoie **jamais** la clé, seulement un indice masqué et son mode (test/live).
    """
    key = await resolve_stripe_key()
    if not key:
        return {"configure": False, "mode": "mock",
                "message": "Aucune clé Stripe : les paiements sont simulés (mode mock)."}
    mode = "test" if key.startswith("sk_test_") else ("live" if key.startswith("sk_live_") else "inconnu")
    return {
        "configure": True,
        "mode": mode,
        "indice_cle": mask_key(key),
        "webhook_verifie": bool(settings.STRIPE_WEBHOOK_SECRET),
        "message": f"Stripe configuré (clé {mode}).",
    }


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
    if body.plan not in _PLANS_PAYANTS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    oid = _uuid(org_id)
    prix = PLANS[body.plan]["prix"]
    key = await resolve_stripe_key()

    if not key:
        # Dégradation honnête : pas de clé ⇒ session simulée, paiement tracé `pending`,
        # réponse explicitement marquée `mock` (on NE prétend PAS encaisser).
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=11))
        session_id = f"cs_{int(time.time() * 1000)}_{rand}"
        async with SessionLocal() as s:
            s.add(StripePayments(
                org_id=oid, user_id=user.sub, stripe_session_id=session_id,
                montant=prix * 100, statut="pending",
            ))
            await s.commit()
        return {"mode": "mock", "sessionId": session_id,
                "checkoutUrl": f"https://checkout.stripe.com/pay/{session_id}",
                "message": "Stripe non configuré : lien de paiement simulé (aucun encaissement réel)."}

    # Checkout RÉEL : session d'abonnement mensuel, prix inline (pas de Price pré-créé).
    stripe.api_key = key
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f"Workplace — plan {body.plan}"},
                    "unit_amount": prix * 100,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
            client_reference_id=str(oid) if oid else None,
            metadata={"plan": body.plan, "user_id": user.sub, "org_id": str(oid) if oid else ""},
        )
    except stripe.StripeError as e:  # erreur API claire, pas de stacktrace
        log.warning("Échec création session Stripe : %s", e.user_message or str(e))
        raise HTTPException(status_code=502, detail="Stripe a refusé la création du paiement.")

    async with SessionLocal() as s:
        s.add(StripePayments(
            org_id=oid, user_id=user.sub, stripe_session_id=session.id,
            montant=prix * 100, statut="pending",
        ))
        await s.commit()
    return {"mode": "live", "sessionId": session.id, "checkoutUrl": session.url}


@router.post("/stripe/webhook")
async def webhook(request: Request):
    """Webhook Stripe **public mais à signature vérifiée**.

    Stripe signe chaque envoi (`Stripe-Signature`) avec le secret de l'endpoint.
    `construct_event` recalcule le HMAC-SHA256 du corps brut : toute falsification
    (signature absente/forgée, corps trafiqué) → 400, aucun effet de bord. Sans
    secret configuré, on **refuse** (on ne réintroduit pas le trou du mock).
    """
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook Stripe non configuré (STRIPE_WEBHOOK_SECRET absent).")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except ValueError:  # corps illisible
        raise HTTPException(status_code=400, detail="Webhook payload invalide.")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Signature webhook invalide.")

    if event.get("type") == "checkout.session.completed":
        session_id = (event.get("data") or {}).get("object", {}).get("id")
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
