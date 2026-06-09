"""Flux OAuth2 Google (authorization code) — sans dépendance au SDK Google.

On parle directement aux endpoints HTTP de Google (accounts.google.com pour le
consentement, oauth2.googleapis.com pour l'échange/refresh). Cela évite d'ajouter
google-auth/google-api-python-client : httpx (déjà présent) suffit.

Le pont est désactivé si GOOGLE_CLIENT_ID/SECRET ne sont pas configurés.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from config import settings

AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def build_auth_url(state: str) -> str:
    """URL de consentement Google.

    access_type=offline + prompt=consent garantit un refresh_token au premier
    consentement (sinon Google ne le renvoie pas sur les autorisations suivantes).
    `state` lie le callback à l'utilisateur qui a initié la connexion.
    """
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_BASE}?{urlencode(params)}"


def _expires_at(data: dict) -> datetime | None:
    if "expires_in" not in data:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(data["expires_in"]))


async def exchange_code(code: str) -> dict:
    """Échange un code d'autorisation contre des tokens.

    Retourne un dict normalisé : access_token, refresh_token, expires_at, scope.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            },
        )
    if not r.is_success:
        raise GoogleOAuthError(f"Échange du code échoué ({r.status_code}): {r.text}")
    data = r.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": _expires_at(data),
        "scope": data.get("scope"),
    }


async def refresh_access_token(refresh_token: str) -> dict:
    """Renouvelle un access_token expiré à partir du refresh_token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
            },
        )
    if not r.is_success:
        raise GoogleOAuthError(f"Refresh du token échoué ({r.status_code}): {r.text}")
    data = r.json()
    return {
        # Google ne renvoie pas de nouveau refresh_token au refresh.
        "access_token": data["access_token"],
        "expires_at": _expires_at(data),
        "scope": data.get("scope"),
    }


class GoogleOAuthError(RuntimeError):
    """Échec d'un échange/refresh OAuth Google."""
