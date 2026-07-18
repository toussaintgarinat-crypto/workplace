"""S181 — client minimal de l'API NetBird Cloud pour générer des setup keys usage-unique
(onboarding d'un proche au mesh). Le PAT (NETBIRD_API_TOKEN) vient de l'env gitignoré ;
jamais commité, jamais renvoyé au front."""
from __future__ import annotations

import os

import httpx

NETBIRD_API_URL = os.environ.get("NETBIRD_API_URL", "https://api.netbird.io").rstrip("/")
NETBIRD_API_TOKEN = os.environ.get("NETBIRD_API_TOKEN", "")
NETBIRD_INVITE_GROUP_ID = os.environ.get("NETBIRD_INVITE_GROUP_ID", "")
NETBIRD_SETUP_KEY_EXPIRES = int(os.environ.get("NETBIRD_SETUP_KEY_EXPIRES", "86400"))


class NetbirdError(RuntimeError):
    """API NetBird injoignable, non authentifiée, ou réponse d'erreur."""


async def creer_setup_key(nom: str, *, client: httpx.AsyncClient | None = None) -> dict:
    """Crée une setup key one-off (usage unique) via POST /api/setup-keys.

    Renvoie {"key", "expires", "name"}. Lève NetbirdError sur toute anomalie."""
    if not NETBIRD_API_TOKEN:
        raise NetbirdError("NETBIRD_API_TOKEN manquant (PAT NetBird non configuré)")

    payload = {
        "name": nom,
        "type": "one-off",
        "expires_in": NETBIRD_SETUP_KEY_EXPIRES,
        "usage_limit": 1,
        "auto_groups": [NETBIRD_INVITE_GROUP_ID] if NETBIRD_INVITE_GROUP_ID else [],
        "ephemeral": False,
    }
    headers = {"Authorization": f"Token {NETBIRD_API_TOKEN}"}

    own = client is None
    c = client or httpx.AsyncClient()
    try:
        try:
            r = await c.post(f"{NETBIRD_API_URL}/api/setup-keys", json=payload, headers=headers, timeout=15)
        except httpx.HTTPError as e:
            raise NetbirdError(f"API NetBird injoignable : {e}") from e
        if r.status_code >= 400:
            raise NetbirdError(f"NetBird {r.status_code} : {r.text[:200]}")
        data = r.json()
    finally:
        if own:
            await c.aclose()

    return {"key": data["key"], "expires": data.get("expires"), "name": data.get("name", nom)}
