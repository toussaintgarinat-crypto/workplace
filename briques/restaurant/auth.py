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
_SECRET = os.getenv("RESTAURANT_SECRET", "dev-restaurant-secret-NON-SECRET").encode()

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


def creer_session(compte_id: str) -> str:
    """Émet un jeton de session signé pour un compte. Format « compte_id.exp.signature »."""
    exp = int(time.time()) + DUREE_SESSION
    corps = f"{compte_id}.{exp}".encode()
    return f"{compte_id}.{exp}.{_signer(corps)}"


def lire_session(jeton: str | None) -> str | None:
    """Valide un jeton de session et renvoie le compte_id, ou None si invalide/expiré.

    Vérifie la signature (anti-falsification) PUIS l'expiration. Tout écart → None
    (fail-closed) : aucune donnée ne fuit sur un jeton douteux."""
    if not jeton:
        return None
    try:
        compte_id, exp_str, sig = jeton.rsplit(".", 2)
    except ValueError:
        return None
    corps = f"{compte_id}.{exp_str}".encode()
    if not hmac.compare_digest(sig, _signer(corps)):
        return None
    try:
        if int(exp_str) < int(time.time()):
            return None
    except ValueError:
        return None
    return compte_id or None
