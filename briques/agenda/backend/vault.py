"""Coffre de tokens OAuth chiffrés, par utilisateur.

Rapatrié de workspace/assistant (vault.py) et adapté au style SQLAlchemy 2.0
async de la brique Agenda : les fonctions prennent une AsyncSession plutôt que
de s'appuyer sur la lib `databases`.

Chiffrement : AES-GCM (clé = SHA-256 du VAULT_SECRET). Le nonce de 12 octets est
préfixé au chiffré. Sans VAULT_SECRET configuré, toute écriture lève — on ne
stocke jamais un token en clair par accident.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.orm import UserToken


def _key() -> bytes:
    if not settings.VAULT_SECRET:
        raise RuntimeError(
            "VAULT_SECRET n'est pas configuré — impossible de chiffrer un token OAuth"
        )
    return hashlib.sha256(settings.VAULT_SECRET.encode()).digest()


def encrypt(plaintext: str) -> bytes:
    aesgcm = AESGCM(_key())
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ct


def decrypt(data: bytes) -> str:
    aesgcm = AESGCM(_key())
    blob = bytes(data)
    return aesgcm.decrypt(blob[:12], blob[12:], None).decode()


async def get_token_row(db: AsyncSession, user_id: str, provider: str = "google") -> UserToken | None:
    res = await db.execute(
        select(UserToken).where(
            UserToken.user_id == user_id, UserToken.provider == provider
        )
    )
    return res.scalar_one_or_none()


async def get_access_token(db: AsyncSession, user_id: str, provider: str = "google") -> str | None:
    row = await get_token_row(db, user_id, provider)
    if not row or not row.access_token_enc:
        return None
    try:
        return decrypt(row.access_token_enc)
    except Exception:
        return None


async def get_refresh_token(db: AsyncSession, user_id: str, provider: str = "google") -> str | None:
    row = await get_token_row(db, user_id, provider)
    if not row or not row.refresh_token_enc:
        return None
    try:
        return decrypt(row.refresh_token_enc)
    except Exception:
        return None


async def upsert_token(
    db: AsyncSession,
    user_id: str,
    access_token: str,
    *,
    provider: str = "google",
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
    scope: str | None = None,
) -> UserToken:
    """Range/remplace les tokens chiffrés pour (user_id, provider).

    Un refresh_token absent (Google ne le renvoie qu'au premier consentement)
    ne doit pas écraser celui déjà stocké.
    """
    row = await get_token_row(db, user_id, provider)
    enc_access = encrypt(access_token)
    enc_refresh = encrypt(refresh_token) if refresh_token else None

    if row is None:
        row = UserToken(
            user_id=user_id,
            provider=provider,
            access_token_enc=enc_access,
            refresh_token_enc=enc_refresh,
            expires_at=expires_at,
            scope=scope,
        )
        db.add(row)
    else:
        row.access_token_enc = enc_access
        if enc_refresh is not None:
            row.refresh_token_enc = enc_refresh
        row.expires_at = expires_at
        if scope is not None:
            row.scope = scope

    await db.commit()
    await db.refresh(row)
    return row


async def delete_token(db: AsyncSession, user_id: str, provider: str = "google") -> bool:
    """Purge le coffre pour (user_id, provider) — révocation du consentement.

    Retourne True si une ligne existait.
    """
    existed = await get_token_row(db, user_id, provider) is not None
    await db.execute(
        delete(UserToken).where(
            UserToken.user_id == user_id, UserToken.provider == provider
        )
    )
    await db.commit()
    return existed
