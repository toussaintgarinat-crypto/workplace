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


# ── Cagnotte universelle par ID (S166, « OMNI-SPLIT épuré ») ─────
# Une cagnotte est AVEUGLE au métier : un id partageable, une cible, des contributions.
# Deux sortes de contributions :
#   • « digitale » : passe par le RAIL (paiement + commission → compte connecté) ;
#   • « externe »  : le client RÉFRACTAIRE — quelqu'un a payé en espèces/CB physique
#     hors du rail (le POS/la caisse notifie) → la cible effective DESCEND pour les
#     payeurs digitaux, sans qu'un centime ne transite ici. On le dit tel quel.
CAGNOTTE_OUVERTE = "ouverte"
CAGNOTTE_ANNULEE = "annulee"
CAGNOTTE_ATTEINTE = "atteinte"   # état DÉRIVÉ (reste = 0), jamais stocké : rien à désynchroniser

CONTRIB_DIGITALE = "digitale"
CONTRIB_EXTERNE = "externe"


def reste_cagnotte(cible_cents: int, solde_cents: int) -> int:
    """Ce qui manque encore pour atteindre la cible, borné ≥ 0 (jamais de reste négatif,
    même si la caisse a encaissé plus que prévu). Pur."""
    return max(0, max(0, int(cible_cents)) - max(0, int(solde_cents)))


def statut_effectif(statut: str, reste_cents: int) -> str:
    """Statut PRÉSENTÉ d'une cagnotte : « atteinte » est dérivé du reste (source unique
    de vérité = les contributions), « annulée » prime toujours."""
    if statut == CAGNOTTE_ANNULEE:
        return CAGNOTTE_ANNULEE
    return CAGNOTTE_ATTEINTE if reste_cents <= 0 else CAGNOTTE_OUVERTE


def contribution_bornee(reste_cents: int, montant_cents: int) -> int:
    """Montant réellement admissible d'une contribution : borné au RESTE de la cagnotte
    (anti-surpaiement, même invariant que `montant_a_encaisser` du resto S83). 0 → rien
    à contribuer (cagnotte déjà atteinte / saisie vide ou négative). Pur."""
    reste = max(0, int(reste_cents))
    if reste <= 0:
        return 0
    return min(max(0, int(montant_cents)), reste)


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
