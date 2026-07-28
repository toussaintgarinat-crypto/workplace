"""Chiffrement au repos des configurations de source (S214).

Une configuration de connecteur porte des **identifiants tiers** (jeton GitHub, clé
d'API Stripe…). Elle ne peut pas dormir en clair dans le SQLite de la brique : c'est la
seule donnée de `connecteurs` qui a une valeur en dehors de Workplace.

Motif repris tel quel de `briques/agenda/backend/crypto.py` (S180) — AES-GCM, enveloppe
`base64(version || nonce(12) || ciphertext)` — mais SANS SQLAlchemy : cette brique stocke
en `sqlite3` nu, comme `ingestion` et `veille-info`. La clé dérive de
`CONNECTEURS_ENCRYPTION_KEY` (dédiée) ou, à défaut, d'une sous-clé HKDF **distincte** de
`VAULT_SECRET` (séparation des usages : la même racine ne doit jamais produire la même
clé pour deux briques). Sans aucune clé : on lève — fail-closed, jamais de repli en clair.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 1
_HKDF_SALT = b"connecteurs-config-v1"
_HKDF_INFO = b"chiffrement-config-connecteurs"


class SecretIndisponible(RuntimeError):
    """Aucune clé de chiffrement configurée — refus explicite d'écrire en clair."""


def cle() -> bytes:
    """Clé AES-GCM (32 octets) des configurations de source."""
    dediee = os.environ.get("CONNECTEURS_ENCRYPTION_KEY")
    if dediee:
        return hashlib.sha256(dediee.encode()).digest()
    racine = os.environ.get("VAULT_SECRET")
    if racine:
        return HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=_HKDF_SALT, info=_HKDF_INFO,
        ).derive(racine.encode())
    raise SecretIndisponible(
        "Ni CONNECTEURS_ENCRYPTION_KEY ni VAULT_SECRET configuré — la configuration "
        "d'une source contient des identifiants tiers, elle ne sera pas stockée en clair."
    )


def chiffrer(config: dict) -> str:
    """Enveloppe versionnée base64 d'une configuration (dict JSON-sérialisable)."""
    aesgcm = AESGCM(cle())
    nonce = os.urandom(12)
    clair = json.dumps(config, ensure_ascii=False).encode()
    return base64.b64encode(bytes([VERSION]) + nonce + aesgcm.encrypt(nonce, clair, None)).decode()


def dechiffrer(jeton: str) -> dict:
    blob = base64.b64decode(jeton)
    # blob[0] = version (0x01 aujourd'hui) ; réservé pour une rotation future.
    aesgcm = AESGCM(cle())
    return json.loads(aesgcm.decrypt(blob[1:13], blob[13:], None).decode())


def masquer(config: dict) -> dict:
    """Vue rendue par l'API : les clés, pas les valeurs.

    Une config n'est JAMAIS relue en clair par une route — ni par une capacité de
    l'assistant, qui recracherait le jeton dans une conversation LLM. On rend la forme
    (quels champs sont renseignés), ce qui suffit à diagnostiquer « il manque le token »
    sans jamais réexposer le secret.
    """
    return {k: ("(renseigné)" if v not in (None, "", [], {}) else "(vide)") for k, v in config.items()}
