"""Chiffrement des clés API — AES-256-GCM, COMPATIBLE avec le Bun.

Réplique fidèlement ``forge/core/src/config/crypto.ts`` : la DB est partagée, une
clé chiffrée par le Bun doit être déchiffrable par Python (et inversement) pendant
toute la migration strangler.

Schéma (identique au Bun / WebCrypto) :
- clé maître = ENCRYPTION_KEY, ajustée à 32 octets : ``key.padEnd(32,'!').slice(0,32)``
  (équivalent JS char-based ; pour des clés ASCII = 32 octets exactement) ;
- IV = 12 octets aléatoires ;
- AES-GCM ⇒ ciphertext AVEC tag d'authentification 16 octets APPENDU (comportement
  WebCrypto, identique à ``cryptography.AESGCM``) ;
- format stocké : ``base64(iv):base64(cipher+tag)``.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DEV_KEY = "forge-default-dev-key-32chars!!"


def _master_key() -> str:
    key = os.getenv("ENCRYPTION_KEY")
    if os.getenv("NODE_ENV") == "production" and (not key or key == _DEV_KEY):
        raise RuntimeError(
            "[FATAL] ENCRYPTION_KEY doit être défini en production (jamais la clé dev par défaut). "
            "Génère-en une : openssl rand -base64 32"
        )
    return key or _DEV_KEY


def _derive_key(secret: str) -> bytes:
    # JS: secret.padEnd(32, '!').slice(0, 32) puis TextEncoder().encode(...)
    adjusted = secret.ljust(32, "!")[:32]
    raw = adjusted.encode("utf-8")
    if len(raw) != 32:
        # AES-256 exige 32 octets ; le Bun (WebCrypto importKey) échouerait aussi.
        raise ValueError(f"ENCRYPTION_KEY doit faire 32 octets une fois ajustée (reçu {len(raw)}).")
    return raw


def encrypt(plaintext: str) -> str:
    key = AESGCM(_derive_key(_master_key()))
    iv = os.urandom(12)
    cipher = key.encrypt(iv, plaintext.encode("utf-8"), None)  # tag appendu
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"{b64(iv)}:{b64(cipher)}"


def decrypt(ciphertext: str) -> str:
    parts = ciphertext.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid ciphertext format")
    iv = base64.b64decode(parts[0])
    cipher = base64.b64decode(parts[1])
    key = AESGCM(_derive_key(_master_key()))
    return key.decrypt(iv, cipher, None).decode("utf-8")


def mask_key(key: str) -> str:
    """sk-abc...xyz → sk-a••••xyz (identique au Bun maskKey)."""
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}{'•' * min(len(key) - 8, 12)}{key[-4:]}"
