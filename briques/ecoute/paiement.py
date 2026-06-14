"""Facturation du palier payant (S43) — achat **one-off** d'un nom de marque.

Réutilise **fidèlement le motif prouvé en S21** (`briques/forge/.../routers/stripe.py`) :
clé secrète résolue d'abord par l'environnement, **dégradation honnête en mode mock**
(on ne fabrique JAMAIS un faux encaissement), et **webhook à signature vérifiée**
(HMAC du corps brut — falsification → 400).

Décision d'archi assumée : le Stripe de **Forge** est *abonnement mensuel + org-scopé
(Keycloak)*. Un nom d'éveil est un **achat unique anonyme** → on ne tord pas le routeur
d'abonnement de Forge ; on rejoue son **pattern** ici en `mode="payment"`. Pas de
duplication de la *clé* (même secret `STRIPE_SECRET_KEY` au niveau compte), juste du
*flux* adapté au one-off. (Le coffre chiffré de Forge n'est pas accessible depuis cette
brique ; ici la clé vient de l'env — repli honnête, documenté.)

Import `stripe` **paresseux** : le mode mock et le webhook-non-configuré ne l'exigent
pas → la brique et ses tests tournent sans le SDK installé.
"""
from __future__ import annotations

import logging
import os
import random
import string
import time

logger = logging.getLogger(__name__)

SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:5800/commandes")
CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "http://localhost:5800/commandes")


def resoudre_cle() -> str | None:
    """Clé secrète Stripe au niveau compte (env). None → mode mock honnête."""
    return os.getenv("STRIPE_SECRET_KEY") or None


def _mask(cle: str) -> str:
    return cle[:7] + "…" + cle[-4:] if len(cle) > 12 else "***"


def etat() -> dict:
    """État honnête de la config paiement (jamais la clé en clair)."""
    cle = resoudre_cle()
    if not cle:
        return {"configure": False, "mode": "mock",
                "message": "Aucune clé Stripe : commandes simulées (mock), aucun encaissement."}
    mode = ("test" if cle.startswith("sk_test_")
            else "live" if cle.startswith("sk_live_") else "inconnu")
    return {"configure": True, "mode": mode, "indice_cle": _mask(cle),
            "webhook_verifie": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "message": f"Stripe configuré (clé {mode})."}


def creer_checkout(commande: dict) -> dict:
    """Crée un paiement unique pour une commande. Renvoie {mode, session_id, url}.

    Sans clé : session simulée explicitement `mock` (le webhook mock confirmera).
    """
    cle = resoudre_cle()
    prix = commande["prix_cents"]
    devise = commande["devise"]

    if not cle:
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=11))
        session_id = f"cs_mock_{int(time.time() * 1000)}_{rand}"
        return {"mode": "mock", "session_id": session_id,
                "url": f"{SUCCESS_URL}?session_id={session_id}",
                "message": "Stripe non configuré : lien simulé (aucun encaissement réel)."}

    import stripe  # paresseux : seul le vrai paiement charge le SDK
    stripe.api_key = cle
    try:
        session = stripe.checkout.Session.create(
            mode="payment",  # one-off (≠ subscription de Forge)
            line_items=[{
                "price_data": {
                    "currency": devise,
                    "product_data": {"name": f"Nom d'éveil sur mesure — « {commande['nom_marque']} »"},
                    "unit_amount": prix,
                },
                "quantity": 1,
            }],
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            client_reference_id=commande["id"],
            metadata={"commande_id": commande["id"], "modele": commande["modele"]},
        )
    except stripe.StripeError as e:  # noqa: F841 - message API clair, pas de stacktrace
        logger.warning("Échec création session Stripe : %s", getattr(e, "user_message", str(e)))
        raise RuntimeError("Stripe a refusé la création du paiement.")
    return {"mode": "live", "session_id": session.id, "url": session.url}


def verifier_webhook(payload: bytes, signature: str) -> dict:
    """Vérifie la signature Stripe et renvoie l'événement. Lève `ValueError` si non
    configuré / signature invalide (le routeur traduit en 503/400). On ne réintroduit
    PAS le trou du mock non signé (cf. S21)."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("non_configure")
    import stripe
    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except ValueError:
        raise ValueError("payload_invalide")
    except stripe.SignatureVerificationError:
        raise ValueError("signature_invalide")
