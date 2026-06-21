"""Fournisseurs de paiement — interface PROVIDER-AGNOSTIQUE.

La brique expose UN rail ; Stripe en est l'implémentation. On garde une couture pour brancher
d'autres prestataires plus tard. Deux fournisseurs :

  • `Mock`   : par défaut, **honnête**. Aucune clé requise, aucun argent ne bouge, tout est
               étiqueté « mock » (jamais de faux encaissement présenté comme réel). Sert la
               démo, les tests et le développement souverain.
  • `Stripe` : réel, **mode test** dès qu'une clé `sk_test_`/`rk_test_` est fournie (LIVE =
               clé `sk_live_` + validation plateforme Stripe + KYC vendeurs = étape externe).
               Connect via **controller properties** (recommandation Stripe : pas le label legacy
               « Express ») + **destination charges** (`transfer_data.destination` +
               `application_fee_amount` = la commission plateforme). Import `stripe` PARESSEUX :
               le mock et les tests tournent sans le SDK installé.

Le choix se fait comme dans `ecoute/paiement.py` : clé présente ⇒ Stripe, sinon ⇒ mock.
On ne met JAMAIS la clé en clair dans une réponse, un log ou un message d'erreur (cf. règles
de sécurité Stripe).
"""
from __future__ import annotations

import os
import random
import string
import time

import domaine

PUBLIC_URL = os.getenv("PAIEMENTS_PUBLIC_URL", "http://localhost:6020")


def _ref(prefixe: str) -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
    return f"{prefixe}_{int(time.time() * 1000)}_{rand}"


def resoudre_cle() -> str | None:
    """Clé secrète/ restreinte Stripe (env). None → mode mock honnête. (On préfère une clé
    RESTREINTE `rk_` à une clé secrète `sk_` — principe du moindre privilège.)"""
    return os.getenv("STRIPE_SECRET_KEY") or None


def _mask(cle: str) -> str:
    return cle[:7] + "…" + cle[-4:] if len(cle) > 12 else "***"


def etat_config() -> dict:
    """État HONNÊTE de la configuration (jamais la clé en clair). Sert /config et le bandeau UI."""
    cle = resoudre_cle()
    if not cle:
        return {"configure": False, "fournisseur": "mock",
                "message": "Aucune clé Stripe : rail SIMULÉ (mock), aucun mouvement d'argent réel."}
    mode = ("test" if "_test_" in cle else "live" if "_live_" in cle else "inconnu")
    return {"configure": True, "fournisseur": "stripe", "mode": mode, "indice_cle": _mask(cle),
            "webhook_verifie": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "message": f"Stripe configuré (clé {mode})."}


# ── Fournisseur MOCK (honnête) ───────────────────────────────────
class Mock:
    """Simulation locale. Un compte naît « incomplet » (onboarding à faire) ; l'onboarding mock
    pointe vers une page de la brique qui l'active (aucune vérification KYC réelle, c'est dit).
    Un paiement est simulé « payé » immédiatement (étiqueté mock). Aucun argent ne bouge."""

    nom = "mock"

    def creer_compte(self, infos: dict) -> dict:
        return {"ref_externe": _ref("acct_mock"), "statut": domaine.COMPTE_INCOMPLET}

    def lien_onboarding(self, compte: dict) -> dict:
        # Page interne qui activera le compte au clic (cf. main.py /demo/onboarding).
        return {"url": f"{PUBLIC_URL}/demo/onboarding/{compte['id']}", "mode": "mock"}

    def statut_compte(self, compte: dict) -> dict:
        # En mock, on fait foi de l'état stocké (activé via la page d'onboarding mock).
        statut = compte.get("statut", domaine.COMPTE_INCOMPLET)
        return {"statut": statut, "peut_encaisser": domaine.compte_peut_encaisser(statut)}

    def creer_paiement(self, compte: dict, montant_cents: int, devise: str,
                       commission_cents: int, description: str) -> dict:
        return {"ref_externe": _ref("pi_mock"), "statut": domaine.PAIEMENT_PAYE,
                "mode": "mock",
                "message": "Paiement SIMULÉ (mock) : aucun débit, aucun virement réel."}

    def rembourser(self, paiement: dict) -> dict:
        return {"ref_externe": _ref("re_mock"), "statut": domaine.PAIEMENT_REMBOURSE, "mode": "mock"}


# ── Fournisseur STRIPE (réel, paresseux) ─────────────────────────
class Stripe:
    """Connect réel. Suit les bonnes pratiques Stripe : controller properties (pas le label
    legacy « Express »), onboarding HÉBERGÉ par Stripe (Account Links → aucune PII collectée
    par nous), destination charges + application_fee. Toutes les méthodes chargent le SDK
    paresseusement et n'exposent jamais la clé."""

    nom = "stripe"

    def __init__(self, cle: str):
        import stripe  # paresseux : seul le vrai rail charge le SDK
        self._stripe = stripe
        stripe.api_key = cle

    def creer_compte(self, infos: dict) -> dict:
        # Controller properties : la plateforme assume les pertes et collecte les exigences ;
        # le vendeur a un tableau de bord « express ». (Stripe recommande Accounts v2 pour les
        # nouvelles plateformes — à confirmer lors du branchement LIVE ; l'API controller est le
        # bon vocabulaire entre-temps.)
        acct = self._stripe.Account.create(
            country=infos.get("pays", "FR"),
            email=infos.get("email") or None,
            controller={
                "losses": {"payments": "application"},
                "fees": {"payer": "application"},
                "stripe_dashboard": {"type": "express"},
                "requirement_collection": "stripe",
            },
            capabilities={"card_payments": {"requested": True},
                          "transfers": {"requested": True}},
            metadata={"solution": infos.get("solution", "")},
        )
        return {"ref_externe": acct.id, "statut": self._statut(acct)}

    def lien_onboarding(self, compte: dict) -> dict:
        lien = self._stripe.AccountLink.create(
            account=compte["ref_externe"],
            refresh_url=f"{PUBLIC_URL}/comptes-connectes/{compte['id']}/onboarding",
            return_url=f"{PUBLIC_URL}/comptes-connectes/{compte['id']}",
            type="account_onboarding",
        )
        return {"url": lien.url, "mode": "stripe"}

    def statut_compte(self, compte: dict) -> dict:
        acct = self._stripe.Account.retrieve(compte["ref_externe"])
        statut = self._statut(acct)
        return {"statut": statut, "peut_encaisser": domaine.compte_peut_encaisser(statut)}

    def _statut(self, acct) -> str:
        return domaine.COMPTE_ACTIF if getattr(acct, "charges_enabled", False) else domaine.COMPTE_INCOMPLET

    def creer_paiement(self, compte: dict, montant_cents: int, devise: str,
                       commission_cents: int, description: str) -> dict:
        # Destination charge : la plateforme encaisse, prélève sa commission
        # (application_fee_amount), le reste est transféré au compte connecté du vendeur.
        pi = self._stripe.PaymentIntent.create(
            amount=int(montant_cents), currency=devise.lower(),
            description=description or None,
            application_fee_amount=int(commission_cents),
            transfer_data={"destination": compte["ref_externe"]},
            automatic_payment_methods={"enabled": True},
        )
        statut = domaine.PAIEMENT_PAYE if pi.status == "succeeded" else domaine.PAIEMENT_CREE
        return {"ref_externe": pi.id, "statut": statut, "client_secret": pi.client_secret,
                "mode": "stripe"}

    def rembourser(self, paiement: dict) -> dict:
        r = self._stripe.Refund.create(payment_intent=paiement["ref_externe"],
                                       refund_application_fee=True)
        return {"ref_externe": r.id, "statut": domaine.PAIEMENT_REMBOURSE, "mode": "stripe"}


def fournisseur():
    """Le fournisseur ACTIF : Stripe si une clé est configurée, sinon le mock honnête."""
    cle = resoudre_cle()
    return Stripe(cle) if cle else Mock()


def verifier_webhook(payload: bytes, signature: str) -> dict:
    """Vérifie la signature Stripe d'un webhook (corps brut) et renvoie l'événement. Lève
    `ValueError('non_configure'|'payload_invalide'|'signature_invalide')`. On ne traite JAMAIS
    un webhook non signé (pas de trou de sécurité)."""
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
