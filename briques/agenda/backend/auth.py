"""Auth double mode : Keycloak JWT (user) + service token S2S (inter-services)."""

from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

# JWT Keycloak : lib partagée unique du monorepo (S120). Remplace la copie vendored
# agent_personnel_shared.keycloak_auth (le reste du paquet vendored — fastapi_setup,
# redis_client… — reste utilisé tel quel).
from shared.workplace_auth import KeycloakSettings, has_role, verify_token
from config import settings

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

_KC = KeycloakSettings(
    url=settings.KEYCLOAK_URL,
    realm=settings.KEYCLOAK_REALM,
    audience=settings.KEYCLOAK_AUDIENCE,
    jwks_ttl=600,
)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    x_user_id: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_compte_id: str | None = Header(None),
) -> dict:
    """Trois dialectes d'identité, dans l'ordre :

    (a) **S2S Workplace (S168)** : `X-API-Key == AGENDA_KEY` (+ `X-Compte-Id`), injecté
        par le Cœur via `_entetes_brique`. Vérifié EN PREMIER, indépendamment
        d'`AUTH_ENABLED` : la clé prouve le droit d'emprunter la surface de service.
        L'utilisateur de calendrier reste **pinné sur `AGENDA_USER_ID`** (« perso »
        mono-user) — toutes les données ET le coffre OAuth/TimeTree sont keyés sur cet
        id, donc pinner = ne rien perdre à la bascule. `X-Compte-Id` est tracé comme
        crochet multi-tenant futur (cf. ADR agenda-surface-de-service).
    (b) **JWT Keycloak** (frontend).
    (c) **service token historique** (`CALENDAR_SERVICE_TOKEN`) + `X-User-Id` (S2S d'origine).
    """
    # (a) S2S Workplace — la présence d'une clé de service configurée + d'un X-API-Key
    # engage ce dialecte : soit la clé matche (identité pinnée), soit on refuse (401).
    if settings.AGENDA_KEY and x_api_key is not None:
        if x_api_key != settings.AGENDA_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid service key")
        return {"sub": settings.AGENDA_USER_ID, "service_call": True, "compte_id": x_compte_id}

    if not settings.AUTH_ENABLED:
        return {"sub": x_user_id or "anonymous"}

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # S2S : token = CALENDAR_SERVICE_TOKEN → identité portée par X-User-Id
    if settings.CALENDAR_SERVICE_TOKEN and token == settings.CALENDAR_SERVICE_TOKEN:
        if not x_user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-Id required for S2S calls")
        return {"sub": x_user_id, "service_call": True}

    # User : JWT Keycloak
    try:
        return await verify_token(token, _KC)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


async def get_current_user_sse(
    access_token: str | None = Query(None),
    token: str | None = Depends(oauth2_scheme),
    x_user_id: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_compte_id: str | None = Header(None),
) -> dict:
    """Identité pour les flux SSE. `EventSource` ne peut PAS poser d'en-tête
    `Authorization` → on accepte le JWT en query `?access_token=`, avec repli sur l'en-tête
    Bearer (et sur les dialectes S2S). Délègue toute la logique à `get_current_user`."""
    return await get_current_user(
        token=access_token or token, x_user_id=x_user_id,
        x_api_key=x_api_key, x_compte_id=x_compte_id)


async def require_admin(token: str | None = Depends(oauth2_scheme)) -> dict:
    if not settings.AUTH_ENABLED:
        logger.warning("Admin endpoint accessed without auth (AUTH_ENABLED=false)")
        return {"sub": "anonymous"}
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = await verify_token(token, _KC)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if not has_role(payload, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return payload
