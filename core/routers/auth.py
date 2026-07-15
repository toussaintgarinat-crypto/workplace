"""Routes d'authentification du Cœur (S171) — login/callback/logout OIDC PKCE contre le
realm Keycloak `forge`, client `assistant-app` (déjà déclaré, jamais câblé avant S171)."""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import auth

router = APIRouter(tags=["auth"])


@router.get("/auth/login")
async def auth_login(request: Request):
    verifier, challenge = auth.generer_pkce()
    state = auth.jeton_aleatoire()
    redirect_uri = str(request.url_for("auth_callback"))
    pending = auth.chiffrer_cookie({
        "code_verifier": verifier,
        "state": state,
        "redirect_uri": redirect_uri,
    })

    params = {
        "client_id": auth.KEYCLOAK_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = (
        f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth"
        f"?{urllib.parse.urlencode(params)}"
    )
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(
        auth.COOKIE_PENDING, pending,
        httponly=True, secure=auth.AUTH_COOKIE_SECURE, samesite="lax",
        max_age=auth.PENDING_COOKIE_MAX_AGE,
    )
    return resp


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str, state: str):
    pending = auth.dechiffrer_cookie(request.cookies.get(auth.COOKIE_PENDING))
    if pending is None or pending.get("state") != state:
        raise HTTPException(status_code=400, detail="Requête d'authentification invalide ou expirée")

    tokens = await auth.echanger_code(code, pending["code_verifier"], pending["redirect_uri"])
    payload = await auth.verify_token(tokens["access_token"], auth.KC)

    session = {
        "sub": payload["sub"],
        "nom": payload.get("nom"),
        "avatarEmoji": payload.get("avatarEmoji"),
        "refresh_token": tokens["refresh_token"],
    }
    resp = RedirectResponse("/dashboard", status_code=307)
    resp.set_cookie(
        auth.COOKIE_SESSION, auth.chiffrer_cookie(session),
        httponly=True, secure=auth.AUTH_COOKIE_SECURE, samesite="lax",
        max_age=auth.SESSION_COOKIE_MAX_AGE,
    )
    resp.delete_cookie(auth.COOKIE_PENDING)
    return resp


@router.post("/auth/logout")
async def auth_logout():
    resp = RedirectResponse("/auth/login", status_code=303)
    resp.delete_cookie(auth.COOKIE_SESSION)
    return resp
