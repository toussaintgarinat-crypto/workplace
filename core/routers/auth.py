"""Routes d'authentification du Cœur (S171) — login/callback/logout OIDC PKCE contre le
realm Keycloak `forge`, client `assistant-app` (déjà déclaré, jamais câblé avant S171)."""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import auth

router = APIRouter(tags=["auth"])


def _next_sur(brut: str | None) -> str:
    """Destination post-login SÛRE : chemin interne uniquement (commence par un seul `/`,
    jamais `//` ni `/\\` — anti open-redirect). Sinon défaut `/dashboard` (S182b)."""
    if brut and brut.startswith("/") and not brut.startswith("//") and not brut.startswith("/\\"):
        return brut
    return "/dashboard"


@router.get("/auth/login")
async def auth_login(request: Request):
    verifier, challenge = auth.generer_pkce()
    state = auth.jeton_aleatoire()
    redirect_uri = str(request.url_for("auth_callback"))
    pending = auth.chiffrer_cookie({
        "code_verifier": verifier,
        "state": state,
        "redirect_uri": redirect_uri,
        # Destination après login (ex. accepter une invitation d'agenda) ; validée à l'aller.
        "next": _next_sur(request.query_params.get("next")),
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
        f"{auth.KEYCLOAK_PUBLIC_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth"
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

    try:
        tokens = await auth.echanger_code(code, pending["code_verifier"], pending["redirect_uri"])
        payload = await auth.verify_token(tokens["access_token"], auth.KC)
        sub = payload["sub"]
        refresh_token = tokens["refresh_token"]
    except Exception:
        # Code expiré/déjà utilisé (retour arrière, double-soumission), Keycloak
        # injoignable, JWT invalide, ou réponse/JWT de forme inattendue (clé manquante) :
        # jamais de 500 nu sur ce chemin facilement atteignable (spec S171, cf.
        # `exiger_session` dans core/auth.py qui suit déjà exactement ce motif) — on
        # renvoie vers le point d'entrée normal plutôt que de laisser fuiter l'exception.
        return RedirectResponse("/auth/login", status_code=303)

    session = {
        "sub": sub,
        "nom": payload.get("nom"),
        "avatarEmoji": payload.get("avatarEmoji"),
        "refresh_token": refresh_token,
    }
    resp = RedirectResponse(_next_sur(pending.get("next")), status_code=307)
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
