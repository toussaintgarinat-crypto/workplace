"""Pouls autonome — le cœur qui bat tout seul (Sprint S67).

S66 a donné au Cœur un « lobe frontal » (le co-agent : boucle profonde, lecture seule,
bornée en tokens). S67 lui donne un POULS : l'horloge S29 réveille ce co-agent à
cadence régulière sur un objectif récurrent, et dépose sa synthèse comme rappel proactif
🔔 — exactement comme le briefing S30, mais au lieu d'un simple résumé de faits, c'est une
RÉFLEXION autonome multi-étapes (« fais le point et propose les priorités du jour »).

C'est la jonction de toute l'épopée : horloge (cœur qui bat, S29) → co-agent (lobe
frontal, S66) → rappel proactif (S12/S30). Le Cœur n'attend plus qu'on lui parle.

Garde-fou SOUVERAIN propre à S67 : un **budget quotidien de tokens** (« abonnement »)
borne le coût de cette pensée auto-déclenchée. On compte les tokens déjà dépensés par le
pouls AUJOURD'HUI (étiquette `pouls` au journal d'usage), et :
  • si le budget du jour est épuisé → on ne bat pas (statut `budget_jour_atteint`) ;
  • sinon le budget du run est plafonné au RESTANT du jour (le budget quotidien est un
    plafond DUR, pas seulement un défaut).
Idempotent par jour (clé `pouls:AAAA-MM-JJ`), tolérant (le co-agent est lecture seule :
il ne fait qu'OBSERVER et PROPOSER — l'humain garde le pouvoir d'agir).
"""
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import coagent
import journal_usage
import proactif

logger = logging.getLogger(__name__)

FUSEAU = "Europe/Paris"
ETIQUETTE = "pouls"   # sépare la pensée autonome (S67) du co-agent manuel (S66)

# Budget quotidien de tokens pour la pensée autonome. 0 = illimité (défaut prudent : on
# n'active pas un battement coûteux sans réglage explicite côté ops).
BUDGET_JOUR_TOKENS = int(os.getenv("POULS_BUDGET_JOUR_TOKENS", "0") or 0)

# Objectif récurrent du battement. Réglable par env ; défaut = un point proactif utile.
OBJECTIF_DEFAUT = os.getenv("POULS_OBJECTIF",
    "Fais un point proactif pour aujourd'hui : passe en revue l'état des entreprises "
    "livrées, les documents récents et les rendez-vous, puis propose les 3 actions les "
    "plus prioritaires. Si une action sensible s'impose, recommande-la sans l'exécuter.")


def _aujourdhui() -> datetime:
    try:
        return datetime.now(ZoneInfo(FUSEAU))
    except Exception:  # noqa: BLE001 — fuseau absent : heure système
        return datetime.now()


def _budget_run(date_utc: str) -> int | None:
    """Budget de tokens alloué à CE battement, plafonné au restant du jour.

    Renvoie None si aucun budget quotidien n'est fixé (illimité → défaut du co-agent),
    0 ou moins si le budget du jour est déjà épuisé (→ ne pas battre)."""
    if BUDGET_JOUR_TOKENS <= 0:
        return None
    deja = journal_usage.tokens_jour_etiquette(date_utc, ETIQUETTE)
    return BUDGET_JOUR_TOKENS - deja


async def battre(registre, *, forcer: bool = False, objectif: str | None = None,
                 jour: datetime | None = None) -> dict:
    """Fait battre le cœur : réveille le co-agent sur l'objectif récurrent, dépose la synthèse.

    Idempotent par jour (sauf `forcer`). Borné par le budget quotidien de tokens. Appelé
    par l'horloge S29 (tâche `pouls-autonome` du manifest `noyau`) et exposé en
    `POST /pouls/battre` pour le tester/rejouer."""
    jour = jour or _aujourdhui()
    cle = "pouls:" + jour.strftime("%Y-%m-%d")
    proactif.init_db()
    if proactif.existe_cle(cle):
        if not forcer:
            return {"ok": True, "statut": "deja_fait", "cle": cle}
        proactif.supprimer_cle(cle)  # forcer = rejouer (remplace, ne duplique pas)

    # Garde-fou budget quotidien : compté en date UTC (le journal d'usage est en UTC).
    date_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    restant = _budget_run(date_utc)
    if restant is not None and restant <= 0:
        logger.info("Pouls : budget du jour épuisé (%d tokens) — pas de battement.",
                    BUDGET_JOUR_TOKENS)
        return {"ok": True, "statut": "budget_jour_atteint", "cle": cle,
                "budget_jour_tokens": BUDGET_JOUR_TOKENS}

    objectif = (objectif or OBJECTIF_DEFAUT).strip()
    cr = await coagent.executer_objectif(objectif, registre, budget_tokens=restant,
                                         etiquette=ETIQUETTE)
    if not cr["ok"]:
        logger.warning("Pouls : co-agent en échec (%s)", cr.get("erreur"))
        return {"ok": False, "statut": "echec", "cle": cle,
                "erreur": cr.get("erreur"), "compte_rendu": cr}

    synthese = (cr.get("synthese") or "").strip()
    if not synthese:  # honnêteté : pas de rappel vide
        return {"ok": True, "statut": "rien_a_dire", "cle": cle, "compte_rendu": cr}

    titre = "Point du " + jour.strftime("%A %d %B")
    proactif._ajouter("pouls", titre, synthese, cle)
    logger.info("Pouls du %s déposé (objectif mené en %d étape(s), %d tokens, %.4f$, %s).",
                cle, cr.get("etapes"), cr.get("tokens"), cr.get("cout_usd"),
                cr.get("raison_arret"))
    return {
        "ok": True, "statut": "cree", "cle": cle, "titre": titre,
        "synthese": synthese, "etapes": cr.get("etapes"), "tokens": cr.get("tokens"),
        "cout_usd": cr.get("cout_usd"), "raison_arret": cr.get("raison_arret"),
        "outils_appeles": cr.get("outils_appeles", []), "modele": cr.get("modele"),
    }
