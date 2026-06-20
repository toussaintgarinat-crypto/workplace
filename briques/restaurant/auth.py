"""Authentification multi-tenant de la brique « restaurant ».

Chaque restaurateur possède un COMPTE (email + mot de passe). Tout le reste —
restaurants, tables, menu, commandes, paiements — est rattaché à un compte et un
restaurateur ne voit JAMAIS les données d'un autre (frontière fail-closed).

Conçu sans dépendance lourde (stdlib uniquement) :
  • mot de passe haché en PBKDF2-HMAC-SHA256 + sel aléatoire par compte ;
  • session = jeton SIGNÉ (HMAC-SHA256, stateless) « compte_id.expiration.signature ».
    Pas de table de sessions à purger : la validité tient dans la signature.

Le secret de signature vient de RESTAURANT_SECRET. En dev il a une valeur par défaut
(non secrète) — à définir impérativement pour vendre / exposer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

# Secret de signature des sessions. Défaut DEV non secret : à surcharger en prod.
_DEFAUT = "dev-restaurant-secret-NON-SECRET"
_SECRET = os.getenv("RESTAURANT_SECRET", _DEFAUT).encode()


def secret_est_par_defaut() -> bool:
    """Vrai si on tourne encore avec le secret de dev (interdit en prod)."""
    return _SECRET == _DEFAUT.encode()


def verifier_secret_pour_prod() -> None:
    """Refuse de démarrer en prod avec le secret de dev (fail-closed au boot).

    Active uniquement si RESTAURANT_ENV=prod : en dev/démo on laisse le défaut pour
    ne pas friction­ner. En prod, un secret faible = sessions forgeables → on bloque."""
    if os.getenv("RESTAURANT_ENV", "").lower() == "prod" and secret_est_par_defaut():
        raise RuntimeError(
            "RESTAURANT_SECRET non défini en prod : refuse de démarrer (sessions "
            "forgeables). Génère-en un : `openssl rand -hex 32`.")


# Durée de vie d'une session (secondes). 30 jours par défaut.
DUREE_SESSION = int(os.getenv("RESTAURANT_SESSION_TTL", str(30 * 24 * 3600)))

_ITERATIONS = 200_000


# ── Mots de passe ────────────────────────────────────────────────
def hacher_mot_de_passe(mot_de_passe: str) -> str:
    """Hache un mot de passe (PBKDF2-HMAC-SHA256, sel aléatoire). Renvoie « sel$hash »."""
    sel = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), sel, _ITERATIONS)
    return f"{sel.hex()}${h.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, stocke: str) -> bool:
    """Vérifie un mot de passe contre la valeur stockée « sel$hash » (comparaison constante)."""
    try:
        sel_hex, hash_hex = stocke.split("$", 1)
    except ValueError:
        return False
    h = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), bytes.fromhex(sel_hex), _ITERATIONS)
    return hmac.compare_digest(h.hex(), hash_hex)


# ── Jetons de session (signés, stateless) ────────────────────────
def _signer(message: bytes) -> str:
    sig = hmac.new(_SECRET, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def creer_session(compte_id: str, version: int = 1) -> str:
    """Émet un jeton de session signé. Format « compte_id.version.exp.signature ».

    `version` = numéro de révocation du compte : changer le mot de passe ou « se
    déconnecter partout » l'incrémente côté base → tous les anciens jetons deviennent
    invalides (cf. lire_session, validé contre la base dans main.compte_actuel)."""
    exp = int(time.time()) + DUREE_SESSION
    corps = f"{compte_id}.{version}.{exp}".encode()
    return f"{compte_id}.{version}.{exp}.{_signer(corps)}"


def lire_session(jeton: str | None) -> dict | None:
    """Valide signature + expiration d'un jeton. Renvoie {compte_id, version} ou None.

    Ne vérifie QUE la cryptographie et l'expiration (stateless). La révocation (version
    à jour) est vérifiée par l'appelant contre la base. Tout écart → None (fail-closed)."""
    if not jeton:
        return None
    try:
        compte_id, version_str, exp_str, sig = jeton.rsplit(".", 3)
    except ValueError:
        return None
    corps = f"{compte_id}.{version_str}.{exp_str}".encode()
    if not hmac.compare_digest(sig, _signer(corps)):
        return None
    try:
        if int(exp_str) < int(time.time()):
            return None
        version = int(version_str)
    except ValueError:
        return None
    return {"compte_id": compte_id, "version": version} if compte_id else None


# ── Jetons d'ADHÉSION de table (côté CLIENT, ≠ compte restaurateur) ──
def creer_jeton_table(table_id: str, session_id: int) -> str:
    """Émet un jeton prouvant qu'un APPAREIL a rejoint la bonne tablée (après « Démarrer »
    ou « Rejoindre » avec le PIN). Distinct du prénom du convive (un appareil peut en porter
    plusieurs) et du jeton de compte restaurateur.

    Lié à (table, numéro de session) : à la clôture, le numéro de session change en base →
    tous les anciens jetons deviennent automatiquement invalides (la session est fermée,
    le groupe suivant doit re-rejoindre). Format « t.table_id.session.exp.signature »."""
    exp = int(time.time()) + DUREE_SESSION
    corps = f"t.{table_id}.{session_id}.{exp}".encode()
    return f"t.{table_id}.{session_id}.{exp}.{_signer(corps)}"


def lire_jeton_table(jeton: str | None) -> dict | None:
    """Valide un jeton d'adhésion de table → {table_id, session_id} ou None (fail-closed)."""
    if not jeton or not jeton.startswith("t."):
        return None
    try:
        prefixe, table_id, session_str, exp_str, sig = jeton.rsplit(".", 4)
    except ValueError:
        return None
    corps = f"t.{table_id}.{session_str}.{exp_str}".encode()
    if prefixe != "t" or not hmac.compare_digest(sig, _signer(corps)):
        return None
    try:
        if int(exp_str) < int(time.time()):
            return None
        session_id = int(session_str)
    except ValueError:
        return None
    return {"table_id": table_id, "session_id": session_id} if table_id else None
