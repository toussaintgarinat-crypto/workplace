"""Crypto AES-256-GCM — round-trip + COMPATIBILITÉ CROISÉE avec le Bun.

La compat croisée est la garantie strangler : une clé chiffrée par le Bun doit
être déchiffrable par Python (DB partagée). Le ciphertext de référence a été
généré par le Bun (WebCrypto) avec la clé dev par défaut.
"""

import importlib

import pytest


@pytest.fixture
def crypto(monkeypatch):
    # Force la clé dev par défaut (pas de NODE_ENV=production).
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    import app.crypto as c

    return importlib.reload(c)


def test_round_trip(crypto):
    secret = "sk-ant-très-secret-éàü-123"
    assert crypto.decrypt(crypto.encrypt(secret)) == secret


def test_decrypt_bun_ciphertext(crypto):
    """Ciphertext produit par le Bun (forge/core, clé dev) → Python le déchiffre."""
    bun_ct = "lUPaGLB2blfhf4LE:T7GD6YOfHFewA9dmTOey4TA+13y/WMWDSxsO+M4RUsj/xA=="
    assert crypto.decrypt(bun_ct) == "sk-test-secret-123"


def test_invalid_format(crypto):
    with pytest.raises(ValueError):
        crypto.decrypt("not-a-valid-ciphertext")


def test_mask_key(crypto):
    assert crypto.mask_key("0123456789abcdef") == "0123" + "•" * 8 + "cdef"  # len 16 → 8 dots
    assert crypto.mask_key("sk-" + "x" * 30) == "sk-x" + "•" * 12 + "xxxx"   # capé à 12 dots
    assert crypto.mask_key("short") == "••••••••"


def test_master_key_fail_fast_in_prod(monkeypatch):
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    import app.crypto as c

    importlib.reload(c)
    with pytest.raises(RuntimeError):
        c.encrypt("x")
    # restore module state for other tests
    monkeypatch.delenv("NODE_ENV", raising=False)
    importlib.reload(c)
