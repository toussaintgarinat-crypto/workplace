"""Auth double mode : Keycloak JWT (user) + service token S2S (inter-services)."""

from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from agent_personnel_shared.keycloak_auth import KeycloakSettings, has_role, verify_token
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
) -> dict:
    """Accepte un JWT Keycloak (frontend) ou un service token + X-User-Id (S2S)."""
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
