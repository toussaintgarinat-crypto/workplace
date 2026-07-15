"""Tests des routes /auth/* du Cœur (S171).

$ cd core && python3 -m pytest test_auth_routes.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import main  # noqa: E402
import auth  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_login_redirige_vers_keycloak_avec_pkce():
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith(f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth?")
    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
    assert f"client_id={auth.KEYCLOAK_CLIENT_ID}" in location
    assert auth.COOKIE_PENDING in r.cookies


def test_callback_state_invalide_renvoie_400():
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": "state-different"},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 400


def test_callback_ok_pose_session_et_redirige_dashboard(monkeypatch):
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    pending = auth.dechiffrer_cookie(pending_cookie)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        assert code == "code-abc"
        assert code_verifier == pending["code_verifier"]
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": pending["state"]},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 307
    assert r2.headers["location"] == "/dashboard"
    session = auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])
    assert session["sub"] == "marina"
    assert session["refresh_token"] == "rt-1"


def test_logout_supprime_le_cookie_de_session():
    r = client.post("/auth/logout", follow_redirects=False)
    assert r.status_code == 303
    # httpx TestClient expose la suppression via un cookie expiré (Max-Age=0) dans les headers.
    set_cookie = r.headers.get("set-cookie", "")
    assert auth.COOKIE_SESSION in set_cookie


def test_dashboard_accessible_sans_session_quand_auth_desactivee():
    """Non-régression : AUTH_ENABLED=false (défaut) — comportement historique inchangé,
    /dashboard reste accessible en accès direct (core/test_dashboard.py doit continuer
    de passer sans modification)."""
    assert auth.AUTH_ENABLED is False
    r = client.get("/dashboard")
    assert r.status_code == 200


def test_dashboard_redirige_vers_login_quand_auth_activee():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        r = client.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien


def test_dashboard_accessible_avec_session_valide_quand_auth_activee():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()
    try:
        cookie = auth.chiffrer_cookie({
            "sub": "marina", "refresh_token": "rt-1", "nom": "Marina", "avatarEmoji": "🌙",
        })
        import time
        auth._cache_access_token["marina"] = ("at-cache", time.time() + 60)
        r = client.get("/dashboard", cookies={auth.COOKIE_SESSION: cookie})
        assert r.status_code == 200
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()
