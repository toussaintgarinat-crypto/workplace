"""Tests de shared.workplace_auth (S120) — la validation JWT Keycloak mutualisée.

Couvre la construction de l'URL JWKS, les options de décodage (verify_aud conditionnel +
fusion des extra_decode_options), le rôle realm, le cache JWKS (TTL) et le décodage
sync/async. Aucun réseau ni clé réelle : on injecte un faux httpx et un faux jose.jwt.
"""
import asyncio
import time

import pytest

from shared import workplace_auth as wa
from shared.workplace_auth import KeycloakSettings, has_role


def test_jwks_url():
    kc = KeycloakSettings(url="http://kc:8080", realm="acme")
    assert kc.jwks_url == "http://kc:8080/realms/acme/protocol/openid-connect/certs"


def test_decode_options_sans_audience_desactive_verify_aud():
    kc = KeycloakSettings(url="x", realm="r")  # audience vide
    assert kc.decode_options() == {"verify_aud": False}


def test_decode_options_avec_audience_ne_force_rien():
    kc = KeycloakSettings(url="x", realm="r", audience="app")
    assert kc.decode_options() == {}


def test_decode_options_fusionne_extra():
    kc = KeycloakSettings(url="x", realm="r", extra_decode_options={"verify_at_hash": False})
    opts = kc.decode_options()
    assert opts["verify_at_hash"] is False
    assert opts["verify_aud"] is False  # audience vide → ajouté en plus


def test_has_role():
    payload = {"realm_access": {"roles": ["admin", "user"]}}
    assert has_role(payload, "admin") is True
    assert has_role(payload, "absent") is False
    assert has_role({}, "admin") is False


def test_fetch_jwks_sync_met_en_cache(monkeypatch):
    appels = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": ["k1"]}

    def _faux_get(url, timeout):
        appels["n"] += 1
        return _Resp()

    monkeypatch.setattr(wa, "httpx", type("M", (), {"get": staticmethod(_faux_get)}), raising=False)
    # httpx est importé paresseusement DANS la fonction : on patche le module importé.
    import httpx
    monkeypatch.setattr(httpx, "get", _faux_get)

    kc = KeycloakSettings(url="http://kc", realm="r", jwks_ttl=600)
    assert wa._fetch_jwks_sync(kc) == {"keys": ["k1"]}
    assert wa._fetch_jwks_sync(kc) == {"keys": ["k1"]}  # 2e appel servi par le cache
    assert appels["n"] == 1


def test_fetch_jwks_sync_expire_le_cache(monkeypatch):
    appels = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": [appels["n"]]}

    def _faux_get(url, timeout):
        appels["n"] += 1
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "get", _faux_get)

    kc = KeycloakSettings(url="http://kc", realm="r", jwks_ttl=0)  # expire immédiatement
    wa._fetch_jwks_sync(kc)
    wa._fetch_jwks_sync(kc)
    assert appels["n"] == 2


def test_verify_token_sync_decode(monkeypatch):
    import httpx

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": ["k"]}

    monkeypatch.setattr(httpx, "get", lambda url, timeout: _Resp())

    from jose import jwt
    capture = {}

    def _faux_decode(token, jwks, algorithms, audience, options):
        capture.update(token=token, jwks=jwks, algorithms=algorithms,
                        audience=audience, options=options)
        return {"sub": "u1"}

    monkeypatch.setattr(jwt, "decode", _faux_decode)

    kc = KeycloakSettings(url="http://kc", realm="r")
    payload = wa.verify_token_sync("tok", kc)
    assert payload == {"sub": "u1"}
    assert capture["token"] == "tok"
    assert capture["algorithms"] == ["RS256"]
    assert capture["audience"] is None  # audience vide → None
    assert capture["options"] == {"verify_aud": False}


def test_verify_token_async_decode(monkeypatch):
    import httpx

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": ["k"]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, timeout):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda: _Client())

    from jose import jwt
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"sub": "async"})

    kc = KeycloakSettings(url="http://kc", realm="r", audience="app")
    payload = asyncio.run(wa.verify_token("tok", kc))
    assert payload == {"sub": "async"}
