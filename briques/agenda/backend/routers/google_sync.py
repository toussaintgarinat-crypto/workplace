"""Pont Google Agenda — /google/*.

Flux consenti, pull one-way, consentement révocable :
  GET    /google/connect     → URL de consentement Google (state = user)
  GET    /google/callback    → échange le code, range les tokens chiffrés au coffre
  GET    /google/status      → connecté ou non + expiration
  POST   /google/sync        → pull les événements Google → calendrier « Google »
  DELETE /google/disconnect  → purge les tokens (révocation du consentement)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from services import google_calendar, google_oauth, oauth_state
from vault import delete_token, get_token_row, upsert_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["google"])


def _require_configured() -> None:
    if not google_oauth.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pont Google non configuré (GOOGLE_CLIENT_ID/SECRET absents)",
        )


@router.get("/connect")
async def google_connect(user: dict = Depends(get_current_user)):
    """Renvoie l'URL de consentement Google à ouvrir côté navigateur.

    Le `state` est un jeton **signé** (anti-CSRF, S35) liant ce flux à l'utilisateur
    connecté — pas son identifiant brut.
    """
    _require_configured()
    state = oauth_state.emettre(user["sub"])
    return {"authorization_url": google_oauth.build_auth_url(state=state)}


@router.get("/callback", response_class=HTMLResponse)
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Callback OAuth Google. Google appelle cette URL sans le JWT de la brique :
    l'identité provient du `state` **signé** émis à `/connect` (S35). On vérifie sa
    signature et son expiration (anti-CSRF) avant d'en extraire le `user_id` — on ne
    fait plus confiance à un identifiant transmis en clair.
    """
    _require_configured()
    try:
        user_id = oauth_state.verifier(state)
    except oauth_state.StateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"state OAuth invalide : {exc}")
    try:
        tokens = await google_oauth.exchange_code(code)
    except google_oauth.GoogleOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await upsert_token(
        db,
        user_id=user_id,
        access_token=tokens["access_token"],
        provider="google",
        refresh_token=tokens.get("refresh_token"),
        expires_at=tokens.get("expires_at"),
        scope=tokens.get("scope"),
    )
    return HTMLResponse(
        "<html><body><h3>Google Agenda connecté ✅</h3>"
        "<p>Tu peux fermer cet onglet et relancer une synchronisation.</p></body></html>"
    )


@router.get("/status")
async def google_status(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    row = await get_token_row(db, user["sub"], "google")
    if row is None:
        return {"connected": False}
    return {
        "connected": True,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "scope": row.scope,
    }


@router.post("/sync")
async def google_sync(
    time_min: str | None = Query(None, description="Borne basse ISO 8601 (timeMin Google)"),
    time_max: str | None = Query(None, description="Borne haute ISO 8601 (timeMax Google)"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    _require_configured()
    try:
        return await google_calendar.sync_user(
            db, user["sub"], time_min=time_min, time_max=time_max
        )
    except google_calendar.GoogleSyncError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/disconnect")
async def google_disconnect(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    existed = await delete_token(db, user["sub"], "google")
    return {"disconnected": existed}
