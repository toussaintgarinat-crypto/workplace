"""Domaine pur de la brique « mail » — AUCUN effet de bord (ni réseau, ni base, ni LLM).

On y range la seule chose qui mérite d'être testée à froid : comment on *comprend* un
message (sa catégorie) et comment on *priorise* une boîte de réception (le score
d'importance + le tri). Tout est heuristique, déterministe et explicable — jamais une
« IA » déguisée. Le résumé en langage naturel, lui, vit dans `resume.py` (Gateway + repli).

Un « message » est un simple dict normalisé :
    {id, de, de_nom, sujet, date, extrait, corps, lu, dossier}
Les fonctions ci-dessous n'ajoutent que des champs DÉRIVÉS (`categorie`, `score`) ;
elles ne mutent jamais l'entrée.
"""
from __future__ import annotations

# ── Catégories (valeurs stables, servent l'UI et le tri) ─────────────────────
FACTURE = "facture"
RENDEZ_VOUS = "rendez_vous"
PERSONNEL = "personnel"
NEWSLETTER = "newsletter"
NOTIFICATION = "notification"
AUTRE = "autre"

# Mots-clés (FR + EN) — minuscules, comparés sans accent serait mieux mais on reste
# simple : on teste l'inclusion sur sujet+extrait+expéditeur en minuscules.
_MOTS = {
    FACTURE: ("facture", "invoice", "paiement", "payment", "reçu", "receipt", "abonnement",
              "subscription", "devis", "montant", "échéance", "relance", "impayé"),
    RENDEZ_VOUS: ("rendez-vous", "rdv", "réunion", "meeting", "invitation", "agenda",
                  "réservation", "booking", "appel", "call", "confirmation", "créneau"),
    NEWSLETTER: ("newsletter", "promo", "promotion", "offre", "soldes", "sale", "-30%", "-50%",
                 "désabonner", "unsubscribe", "nouveautés"),
    NOTIFICATION: ("notification", "alerte", "alert", "sécurité", "security", "connexion",
                   "login", "code", "vérification", "verify", "mot de passe", "password"),
}

# Marqueurs d'urgence (poussent le score vers le haut, quelle que soit la catégorie).
_URGENCE = ("urgent", "important", "action requise", "action required", "deadline",
            "échéance", "dernier rappel", "immédiat", "asap", "dès que possible", "rappel")

# Expéditeurs « machine » (poussent le score vers le bas : on y répond rarement).
_NO_REPLY = ("no-reply", "noreply", "ne-pas-repondre", "nepasrepondre", "donotreply",
             "mailer-daemon", "notification", "notifications")


def _foin(msg: dict) -> str:
    """Botte de texte minuscule où chercher les mots-clés (sujet + extrait + expéditeur)."""
    return " ".join(str(msg.get(c) or "") for c in ("sujet", "extrait", "de", "de_nom")).lower()


def _contient(foin: str, mots) -> bool:
    return any(m in foin for m in mots)


def categoriser(msg: dict) -> str:
    """Range un message dans UNE catégorie (heuristique mots-clés, ordre de priorité).

    L'ordre compte : une « facture urgente » reste une facture ; une pure promo passe en
    newsletter. Rien ne correspond → `personnel` si l'expéditeur a l'air humain, sinon `autre`."""
    foin = _foin(msg)
    for cat in (FACTURE, RENDEZ_VOUS, NOTIFICATION, NEWSLETTER):
        if _contient(foin, _MOTS[cat]):
            return cat
    de = str(msg.get("de") or "").lower()
    return AUTRE if _contient(de, _NO_REPLY) else PERSONNEL


# Synonymes courants → catégorie canonique (l'assistant/l'utilisateur dit « pub », « promo »…).
_SYNONYMES = {
    "pub": NEWSLETTER, "pubs": NEWSLETTER, "publicité": NEWSLETTER, "publicites": NEWSLETTER,
    "promo": NEWSLETTER, "promos": NEWSLETTER, "promotion": NEWSLETTER, "spam": NEWSLETTER,
    "newsletters": NEWSLETTER, "factures": FACTURE, "paiement": FACTURE, "paiements": FACTURE,
    "rdv": RENDEZ_VOUS, "rendez-vous": RENDEZ_VOUS, "rendezvous": RENDEZ_VOUS,
    "perso": PERSONNEL, "personnels": PERSONNEL, "notif": NOTIFICATION, "notifs": NOTIFICATION,
    "notifications": NOTIFICATION, "autres": AUTRE,
}
_CANONIQUES = {FACTURE, RENDEZ_VOUS, PERSONNEL, NOTIFICATION, NEWSLETTER, AUTRE}


def normaliser_categorie(libelle: str) -> str:
    """Tolère les libellés humains (« pub », « promos », « rdv »…) → catégorie canonique.
    Renvoie "" si on ne reconnaît rien (= pas de filtre, on liste tout)."""
    s = (libelle or "").strip().lower()
    if s in _CANONIQUES:
        return s
    return _SYNONYMES.get(s, "")


def score_importance(msg: dict, expediteurs_connus: set[str] | None = None) -> int:
    """Score 0–100 : à quel point ce message mérite l'attention MAINTENANT.

    Transparent et borné. Les pondérations : non-lu, expéditeur du carnet, urgence dans le
    sujet, catégorie (facture/rdv ↑, newsletter ↓), expéditeur « machine » ↓."""
    connus = {e.lower() for e in (expediteurs_connus or set())}
    foin = _foin(msg)
    de = str(msg.get("de") or "").lower()
    cat = categoriser(msg)

    score = 30
    if not msg.get("lu"):
        score += 25
    if de in connus:
        score += 20
    if _contient(foin, _URGENCE):
        score += 25
    if cat in (FACTURE, RENDEZ_VOUS):
        score += 15
    if cat == NEWSLETTER:
        score -= 30
    if _contient(de, _NO_REPLY):
        score -= 10
    return max(0, min(100, score))


def correspond_filtre(msg: dict, mots: list[str] | None = None, expediteur: str = "") -> bool:
    """Un message correspond-il à un filtre PERSONNALISÉ ? (logique pure, testable)

    • `mots` : le message matche s'il contient AU MOINS UN des mots (dans sujet/extrait/expéditeur).
    • `expediteur` : sous-chaîne devant figurer dans l'adresse de l'expéditeur (ex. « @banque.fr »).
    Les deux contraintes se cumulent (ET). Un filtre vide (ni mots ni expéditeur) matche tout."""
    foin = _foin(msg)
    if mots:
        if not any(m.strip().lower() in foin for m in mots if m.strip()):
            return False
    if expediteur:
        if expediteur.strip().lower() not in str(msg.get("de") or "").lower():
            return False
    return True


def enrichir(msg: dict, expediteurs_connus: set[str] | None = None) -> dict:
    """Copie du message + champs dérivés `categorie` et `score` (n'altère pas l'entrée)."""
    return {**msg, "categorie": categoriser(msg),
            "score": score_importance(msg, expediteurs_connus)}


def trier(messages: list[dict], expediteurs_connus: set[str] | None = None) -> list[dict]:
    """Boîte triée par importance décroissante (puis date décroissante), enrichie."""
    enrichis = [enrichir(m, expediteurs_connus) for m in messages]
    return sorted(enrichis, key=lambda m: (m["score"], str(m.get("date") or "")), reverse=True)


def grouper_par_categorie(messages: list[dict]) -> dict[str, list[dict]]:
    """Regroupe (déjà enrichis ou non) par catégorie, dans un ordre d'affichage stable."""
    groupes: dict[str, list[dict]] = {}
    for m in messages:
        cat = m.get("categorie") or categoriser(m)
        groupes.setdefault(cat, []).append(m)
    ordre = [FACTURE, RENDEZ_VOUS, PERSONNEL, NOTIFICATION, NEWSLETTER, AUTRE]
    return {c: groupes[c] for c in ordre if c in groupes}
