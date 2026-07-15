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


from fastapi import HTTPException
from starlette.requests import Request


def _fake_request(cookies: dict) -> Request:
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    scope = {
        "type": "http",
        "headers": [(b"cookie", cookie_header.encode())] if cookies else [],
    }
    return Request(scope)


def test_exiger_session_auth_desactivee_renvoie_anonyme():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = False
    try:
        r = _run(auth.exiger_session(_fake_request({})))
        assert r == {"sub": "anonymous", "nom": None, "avatarEmoji": None}
    finally:
        auth.AUTH_ENABLED = ancien


def test_exiger_session_sans_cookie_redirige_vers_login():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        try:
            _run(auth.exiger_session(_fake_request({})))
            assert False, "devait lever HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 303
            assert exc.headers["Location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien


def test_exiger_session_cookie_valide_rafraichit_et_verifie():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth.httpx.AsyncClient = _FakeClient
    auth._cache_access_token.clear()

    async def _verify_fake(token, kc):
        return {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}

    ancien_verify = auth.verify_token
    auth.verify_token = _verify_fake
    try:
        cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-123"})
        r = _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
        assert r == {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}
        assert "marina" in auth._cache_access_token
    finally:
        auth.AUTH_ENABLED = ancien
        auth.verify_token = ancien_verify
        auth._cache_access_token.clear()


def test_exiger_session_cache_chaud_ne_rafraichit_pas():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()
    import time
    auth._cache_access_token["marina"] = ("at-cache", time.time() + 60)
    try:
        cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-123", "nom": "Marina", "avatarEmoji": "🌙"})

        class _ClientQuiEchoue:
            def __init__(self, *a, **k):
                raise AssertionError("ne doit pas être appelé : cache chaud")

        auth.httpx.AsyncClient = _ClientQuiEchoue
        r = _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
        assert r == {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()


def test_exiger_session_refresh_echoue_redirige_vers_login():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()

    class _ClientQuiEchoue:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            return _Resp({"error": "invalid_grant"}, status=400)

    auth.httpx.AsyncClient = _ClientQuiEchoue
    try:
        cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-revoque"})
        try:
            _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
            assert False, "devait lever HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 303
            assert exc.headers["Location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()


def test_sub_session_optionnel_cookie_valide():
    cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})
    r = auth.sub_session_optionnel(_fake_request({auth.COOKIE_SESSION: cookie}))
    assert r == "marina"


def test_sub_session_optionnel_pas_de_cookie():
    assert auth.sub_session_optionnel(_fake_request({})) is None


def test_sub_session_optionnel_cookie_corrompu():
    r = auth.sub_session_optionnel(_fake_request({auth.COOKIE_SESSION: "pas-un-cookie-valide"}))
    assert r is None
