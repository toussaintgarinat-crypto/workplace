"""Tests du login Keycloak du Cœur (S171).

$ cd core && python3 -m pytest test_auth.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import auth  # noqa: E402


def test_generer_pkce_format():
    verifier, challenge = auth.generer_pkce()
    assert 43 <= len(verifier) <= 128
    assert verifier != challenge
    # Base64url sans padding : ni '+', '/', ni '='.
    for c in verifier + challenge:
        assert c not in "+/="


def test_generer_pkce_est_aleatoire():
    v1, _ = auth.generer_pkce()
    v2, _ = auth.generer_pkce()
    assert v1 != v2


def test_chiffrer_dechiffrer_cookie_roundtrip():
    payload = {"sub": "marina", "refresh_token": "rt-123"}
    cookie = auth.chiffrer_cookie(payload)
    assert isinstance(cookie, str)
    assert auth.dechiffrer_cookie(cookie) == payload


def test_dechiffrer_cookie_vide_renvoie_none():
    assert auth.dechiffrer_cookie(None) is None
    assert auth.dechiffrer_cookie("") is None


def test_dechiffrer_cookie_corrompu_renvoie_none():
    assert auth.dechiffrer_cookie("pas-du-tout-un-cookie-valide") is None


def test_dechiffrer_cookie_mauvaise_cle_renvoie_none():
    cookie = auth.chiffrer_cookie({"sub": "marina"})
    ancienne_cle = auth.AUTH_SESSION_SECRET
    auth.AUTH_SESSION_SECRET = "une-autre-cle-totalement-differente"
    try:
        assert auth.dechiffrer_cookie(cookie) is None
    finally:
        auth.AUTH_SESSION_SECRET = ancienne_cle
