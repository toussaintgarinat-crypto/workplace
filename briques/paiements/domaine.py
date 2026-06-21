"""Sous-domaine CŒUR du rail de paiement (DDD pragmatique, dans la brique).

Ce module est **PUR** : aucune I/O, aucune dépendance à SQLite, FastAPI ou Stripe. Il porte
le langage ubiquitaire (Argent, commission plateforme) et les invariants de calcul/transition,
testables en microsecondes. Les repositories (`stockage.py`), les fournisseurs (`fournisseurs.py`)
et l'interface (`main.py`) s'appuient dessus.

Décision d'archi (cf. mémoire) : cette brique possède le RAIL d'argent (comptes connectés,
encaissement, commission, remboursement, webhooks). Le SPLIT/addition partagée reste dans la
brique « restaurant ». Le rail est **réutilisable** par d'autres solutions (Forge, marketplaces),
chacune isolée par sa clé (multi-tenant). Provider-agnostique : Stripe est UN fournisseur.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Objet-valeur : Argent ────────────────────────────────────────
@dataclass(frozen=True)
class Argent:
    """Montant monétaire en CENTIMES + devise. Immuable. On reste en entiers (un euro = 100)
    pour éviter les flottants ; les opérations exigent la même devise."""

    cents: int
    devise: str = "EUR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "cents", int(self.cents))
        object.__setattr__(self, "devise", (self.devise or "EUR").upper())

    def _meme_devise(self, autre: "Argent") -> None:
        if self.devise != autre.devise:
            raise ValueError(f"Devises incompatibles : {self.devise} ≠ {autre.devise}")

    def moins(self, autre: "Argent") -> "Argent":
        self._meme_devise(autre)
        return Argent(self.cents - autre.cents, self.devise)


# ── États (machines à états simples, transitions gardées) ────────
# Compte connecté (le vendeur — ex. un restaurateur) : du brouillon à « peut encaisser ».
COMPTE_CREE = "cree"            # créé côté fournisseur, onboarding pas terminé
COMPTE_ACTIF = "actif"          # capacités de paiement actives → peut encaisser
COMPTE_INCOMPLET = "incomplet"  # onboarding requis (infos KYC manquantes)

# Paiement : du « prévu » au « payé/remboursé ».
PAIEMENT_CREE = "cree"
PAIEMENT_PAYE = "paye"
PAIEMENT_REMBOURSE = "rembourse"
PAIEMENT_ECHOUE = "echoue"

_TRANSITIONS_PAIEMENT = {
    PAIEMENT_CREE: {PAIEMENT_PAYE, PAIEMENT_ECHOUE},
    PAIEMENT_PAYE: {PAIEMENT_REMBOURSE},
    PAIEMENT_REMBOURSE: set(),
    PAIEMENT_ECHOUE: set(),
}


def transition_paiement_permise(de: str, vers: str) -> bool:
    """Vrai si le paiement peut passer de l'état `de` à l'état `vers`. Empêche p.ex. de
    rembourser un paiement jamais encaissé, ou de « repayer » un remboursement. Pur."""
    return vers in _TRANSITIONS_PAIEMENT.get(de, set())


def compte_peut_encaisser(statut: str) -> bool:
    """Un compte ne peut recevoir un paiement que s'il est ACTIF (onboarding/KYC terminé)."""
    return statut == COMPTE_ACTIF


# ── Service de domaine : commission plateforme ───────────────────
def calculer_commission(montant_cents: int, *, commission_bps: int = 0,
                        commission_cents: int | None = None) -> dict:
    """Répartit un montant entre la **commission de la plateforme** et le **net du vendeur**.

    Deux façons de fixer la commission (exclusives, `commission_cents` prioritaire si fourni) :
    - `commission_bps` : en **points de base** (250 = 2,50 %), calculée sur le brut, arrondie
      à l'entier inférieur (on ne sur-prélève jamais le vendeur) ;
    - `commission_cents` : un **montant fixe**.

    Invariants (bornes serveur, jamais la confiance de l'appelant) : montant ≥ 0 ; la commission
    est bornée à **[0, montant]** (jamais négative, jamais supérieure au brut → le net reste ≥ 0).
    Retourne {brut, commission, net} en centimes. C'est ce qui devient `application_fee_amount`
    côté Stripe (destination charge)."""
    brut = max(0, int(montant_cents))
    if commission_cents is not None:
        com = int(commission_cents)
    else:
        com = brut * max(0, int(commission_bps)) // 10_000
    com = max(0, min(com, brut))         # jamais < 0 ni > brut
    return {"brut": brut, "commission": com, "net": brut - com}
