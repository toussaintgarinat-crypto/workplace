"""Chiffrement au repos des champs sensibles (S180).

Réutilise l'AES-GCM éprouvé du coffre OAuth (vault.py) et l'expose en `TypeDecorator`
SQLAlchemy transparents. Enveloppe : base64(version || nonce(12) || ciphertext). La
clé dérive de AGENDA_ENCRYPTION_KEY (dédiée) ou, à défaut, d'une sous-clé HKDF
DISTINCTE de VAULT_SECRET (séparation des usages). Sans aucune clé : lève (fail-closed).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import settings

VERSION = 1
_HKDF_SALT = b"agenda-fields-v1"
_HKDF_INFO = b"chiffrement-champs-agenda"


def field_key() -> bytes:
    """Clé AES-GCM (32 octets) des colonnes chiffrées."""
    if settings.AGENDA_ENCRYPTION_KEY:
        return hashlib.sha256(settings.AGENDA_ENCRYPTION_KEY.encode()).digest()
    if settings.VAULT_SECRET:
        return HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=_HKDF_SALT, info=_HKDF_INFO,
        ).derive(settings.VAULT_SECRET.encode())
    raise RuntimeError(
        "Ni AGENDA_ENCRYPTION_KEY ni VAULT_SECRET configuré — "
        "impossible de chiffrer un champ sensible"
    )


def encrypt_raw(key: bytes, plaintext: bytes) -> bytes:
    """Chiffré brut, SANS version : nonce(12) || ciphertext. Partagé avec vault.py."""
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, plaintext, None)


def decrypt_raw(key: bytes, blob: bytes) -> bytes:
    aesgcm = AESGCM(key)
    blob = bytes(blob)
    return aesgcm.decrypt(blob[:12], blob[12:], None)


def chiffrer(plaintext: str) -> str:
    """Enveloppe versionnée base64 d'une chaîne en clair."""
    raw = encrypt_raw(field_key(), plaintext.encode())
    return base64.b64encode(bytes([VERSION]) + raw).decode()


def dechiffrer(token: str) -> str:
    blob = base64.b64decode(token)
    # blob[0] = version (0x01 aujourd'hui) ; réservé pour une rotation future.
    return decrypt_raw(field_key(), blob[1:]).decode()
