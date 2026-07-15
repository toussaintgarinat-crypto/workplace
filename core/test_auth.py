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


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None):
        APPELS.append((url, data))
        if data.get("grant_type") == "authorization_code":
            return _Resp({"access_token": "at-123", "refresh_token": "rt-123", "expires_in": 300})
        if data.get("grant_type") == "refresh_token":
            return _Resp({"access_token": "at-456", "refresh_token": "rt-456", "expires_in": 300})
        return _Resp({}, status=400)


APPELS = []


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_echanger_code_appelle_le_bon_endpoint():
    APPELS.clear()
    auth.httpx.AsyncClient = _FakeClient
    r = _run(auth.echanger_code("code-abc", "verifier-xyz", "http://localhost:5100/auth/callback"))
    assert r == {"access_token": "at-123", "refresh_token": "rt-123", "expires_in": 300}
    url, data = APPELS[0]
    assert url == f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/token"
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "code-abc"
    assert data["code_verifier"] == "verifier-xyz"
    assert data["client_id"] == auth.KEYCLOAK_CLIENT_ID


def test_rafraichir_access_token_appelle_le_bon_endpoint():
    APPELS.clear()
    auth.httpx.AsyncClient = _FakeClient
    r = _run(auth.rafraichir_access_token("rt-123"))
    assert r["access_token"] == "at-456"
    url, data = APPELS[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "rt-123"
