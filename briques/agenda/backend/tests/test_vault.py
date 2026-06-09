"""Coffre de tokens — chiffrement round-trip + CRUD + révocation."""

from __future__ import annotations

import pytest

import vault
from config import settings


def test_encrypt_decrypt_roundtrip():
    blob = vault.encrypt("ya29.secret-access-token")
    assert isinstance(blob, bytes)
    assert blob != b"ya29.secret-access-token"  # bien chiffré
    assert vault.decrypt(blob) == "ya29.secret-access-token"


def test_decrypt_wrong_key_fails():
    blob = vault.encrypt("token")
    settings.VAULT_SECRET = "une-toute-autre-cle-completement-xx"
    with pytest.raises(Exception):
        vault.decrypt(blob)


def test_encrypt_requires_secret():
    settings.VAULT_SECRET = ""
    with pytest.raises(RuntimeError):
        vault.encrypt("token")


@pytest.mark.asyncio
async def test_upsert_then_get(db):
    await vault.upsert_token(
        db, "user-1", "access-1", refresh_token="refresh-1", scope="calendar.readonly"
    )
    assert await vault.get_access_token(db, "user-1") == "access-1"
    assert await vault.get_refresh_token(db, "user-1") == "refresh-1"


@pytest.mark.asyncio
async def test_upsert_preserves_refresh_when_absent(db):
    """Google ne renvoie le refresh_token qu'au 1er consentement — ne pas l'écraser."""
    await vault.upsert_token(db, "user-1", "access-1", refresh_token="refresh-1")
    await vault.upsert_token(db, "user-1", "access-2")  # refresh absent
    assert await vault.get_access_token(db, "user-1") == "access-2"
    assert await vault.get_refresh_token(db, "user-1") == "refresh-1"


@pytest.mark.asyncio
async def test_delete_revokes(db):
    await vault.upsert_token(db, "user-1", "access-1")
    assert await vault.delete_token(db, "user-1") is True
    assert await vault.get_access_token(db, "user-1") is None
    assert await vault.delete_token(db, "user-1") is False  # déjà purgé
