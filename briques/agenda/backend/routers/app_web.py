"""Application web autonome de l'agenda (S172) — /app.

Sert la page HTML/JS de `templates_app.page_app` : login PKCE contre `calendar-app`
(indépendant du dashboard du Cœur), consomme l'API REST déjà existante en
`Authorization: Bearer`. Cf. design :
docs/superpowers/specs/2026-07-15-s172-agenda-application-autonome-design.md
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import settings
from templates_app import page_app

router = APIRouter(tags=["app"])


@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def app_page():
    kc_url = settings.KEYCLOAK_PUBLIC_URL or settings.KEYCLOAK_URL
    return HTMLResponse(page_app(kc_url, settings.KEYCLOAK_REALM, settings.KEYCLOAK_CLIENT_ID))
