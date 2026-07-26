"""Validation JWT Keycloak partagée (JWKS cache + verify_aud conditionnel).

Usage type :

    from agent_personnel_shared.keycloak_auth import KeycloakSettings, verify_token, require_role

    KC = KeycloakSettings(
        url="http://keycloak:8080",
        realm="forge",
        audience="assistant-app",  # vide = verify_aud désactivé
        jwks_ttl=600,
    )

    async def get_current_user(token: str = Depends(oauth2_scheme)):
        return await verify_token(token, KC)

    admin_required = require_role("admin", KC)

Rationale :
- `audience` vide ⇒ `options={"verify_aud": False}` (multi-tenant / dev).
- `audience` rempli ⇒ `options={"audience": <value>}` (prod single-tenant).
- Cache JWKS TTL configurable (default 600s) pour absorber la rotation de clés Keycloak.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class KeycloakSettings:
    url: str
    realm: str
    audience: str = ""  # vide ⇒ verify_aud désactivé (multi-tenant)
    jwks_ttl: int = 600  # seconds
    algorithms: tuple[str, ...] = ("RS256",)
    # Options additionnelles passées à jwt.decode (ex: verify_at_hash=False pour Oria).
    extra_decode_options: dict = field(default_factory=dict)
    # cache interne — ne pas modifier manuellement
    _jwks_cache: Optional[dict] = field(default=None, repr=False)
    _jwks_cached_at: float = field(default=0.0, repr=False)

    @property
    def jwks_url(self) -> str:
        return f"{self.url}/realms/{self.realm}/protocol/openid-connect/certs"

    def decode_options(self) -> dict:
        """Options passées au kwarg `options=` de jwt.decode (sans `audience`).

        NB: `audience` est passée comme kwarg distinct à jwt.decode (cf. verify_token),
        pas via options — python-jose ignore une `audience` placée dans options.
        """
        opts: dict = dict(self.extra_decode_options)
        if not self.audience:
            opts["verify_aud"] = False
        return opts


async def _fetch_jwks(kc: KeycloakSettings) -> dict:
    now = time.monotonic()
    if kc._jwks_cache and (now - kc._jwks_cached_at) < kc.jwks_ttl:
        return kc._jwks_cache
    import httpx  # lazy import
    async with httpx.AsyncClient() as client:
        r = await client.get(kc.jwks_url, timeout=10)
        r.raise_for_status()
    kc._jwks_cache = r.json()
    kc._jwks_cached_at = time.monotonic()
    return kc._jwks_cache


def _fetch_jwks_sync(kc: KeycloakSettings) -> dict:
    """Variante synchrone pour les codes qui ne sont pas async (ex: routers Oria SQLAlchemy)."""
    now = time.monotonic()
    if kc._jwks_cache and (now - kc._jwks_cached_at) < kc.jwks_ttl:
        return kc._jwks_cache
    import httpx  # lazy import
    resp = httpx.get(kc.jwks_url, timeout=10)
    resp.raise_for_status()
    kc._jwks_cache = resp.json()
    kc._jwks_cached_at = time.monotonic()
    return kc._jwks_cache


async def verify_token(token: str, kc: KeycloakSettings) -> dict:
    """Valide un JWT Keycloak et renvoie le payload décodé.

    Lève une exception `JWTError` (python-jose) si le token est invalide.
    """
    from jose import jwt  # lazy import
    jwks = await _fetch_jwks(kc)
    return jwt.decode(
        token, jwks,
        algorithms=list(kc.algorithms),
        audience=kc.audience or None,
        options=kc.decode_options(),
    )


def verify_token_sync(token: str, kc: KeycloakSettings) -> dict:
    """Variante synchrone (cf. _fetch_jwks_sync)."""
    from jose import jwt  # lazy import
    jwks = _fetch_jwks_sync(kc)
    return jwt.decode(
        token, jwks,
        algorithms=list(kc.algorithms),
        audience=kc.audience or None,
        options=kc.decode_options(),
    )


def has_role(payload: dict, role: str) -> bool:
    """True si le payload Keycloak porte le rôle `role` (realm role)."""
    return role in payload.get("realm_access", {}).get("roles", [])


def require_role(role: str, kc: KeycloakSettings) -> Callable[..., Any]:
    """Factory de dependency FastAPI exigeant un rôle realm Keycloak donné.

    Usage :
        require_admin = require_role("admin", KC)

        @app.get("/admin", dependencies=[Depends(require_admin)])
        ...
    """
    from fastapi import Depends, HTTPException, status  # lazy import
    from fastapi.security import OAuth2PasswordBearer
    from jose import JWTError  # lazy import

    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

    async def _dep(token: str | None = Depends(oauth2_scheme)) -> dict:
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        try:
            payload = await verify_token(token, kc)
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
        if not has_role(payload, role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{role} role required")
        return payload

    return _dep
