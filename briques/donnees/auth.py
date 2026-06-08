"""Validation JWT Keycloak pour la brique « donnees » — autonome, activable par env.

Pourquoi ici (et pas via agent_personnel_shared) : le bundle livré au client ne copie
que les fichiers de cette brique. Ce module doit donc être self-contained — il reprend
la même logique éprouvée que keycloak_auth.py (cache JWKS + verify_aud conditionnel),
sans dépendance externe au workspace.

Comportement piloté par l'environnement, rétrocompatible par défaut :
- AUTH_ENABLED absent / "false"  → garde no-op : la brique reste ouverte (donnees
  central de dev inchangé, aucune régression).
- AUTH_ENABLED "true"            → tout appel CRUD exige un Bearer Keycloak valide,
  sinon 401. Le packager pose ce flag (+ KEYCLOAK_URL/REALM) sur le service du bundle.

Multi-tenant : audience vide ⇒ verify_aud désactivé (le realm du bundle suffit à isoler).
"""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# ── Configuration (lue à l'import, depuis l'environnement) ──────────────────────

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "oui", "yes")
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "").rstrip("/")          # ex: http://identite:8080
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "")                  # ex: client-acme
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "").strip()    # vide ⇒ verify_aud off
JWKS_TTL = int(os.getenv("JWKS_TTL", "600"))                      # cache des clés (s)
_ALGORITHMS = ["RS256"]

# Cache JWKS interne (absorbe la rotation des clés Keycloak sans refrapper le réseau).
_jwks_cache: Optional[dict] = None
_jwks_cached_at: float = 0.0

# auto_error=False : on gère nous-mêmes le 401 (message clair, et no-op si désactivé).
_bearer = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def config_valide() -> bool:
    """L'enforcement n'est réel que si l'URL et le realm sont renseignés."""
    return bool(AUTH_ENABLED and KEYCLOAK_URL and KEYCLOAK_REALM)


def _jwks_url() -> str:
    return f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"


def _charger_jwks() -> dict:
    global _jwks_cache, _jwks_cached_at
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_cached_at) < JWKS_TTL:
        return _jwks_cache
    import httpx  # import paresseux : inutile si AUTH_ENABLED=false
    resp = httpx.get(_jwks_url(), timeout=10)
    resp.raise_for_status()
    _jwks_cache = resp.json()
    _jwks_cached_at = time.monotonic()
    return _jwks_cache


def _decode_options() -> dict:
    return {} if KEYCLOAK_AUDIENCE else {"verify_aud": False}


def verifier_jeton(token: str) -> dict:
    """Décode et valide un JWT Keycloak. Lève JWTError si invalide."""
    from jose import jwt  # import paresseux
    jwks = _charger_jwks()
    return jwt.decode(
        token, jwks,
        algorithms=_ALGORITHMS,
        audience=KEYCLOAK_AUDIENCE or None,
        options=_decode_options(),
    )


def garde_auth(token: str | None = Depends(_bearer)) -> Optional[dict]:
    """Dependency FastAPI posée sur les routes de données.

    - Auth désactivée → laisse passer (renvoie None), brique ouverte comme avant.
    - Auth activée    → exige un Bearer valide, sinon 401.
    """
    if not config_valide():
        return None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from jose import JWTError  # import paresseux
    try:
        return verifier_jeton(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Jeton invalide : {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:  # JWKS injoignable, realm inconnu… → 401, jamais 500 silencieux
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Validation impossible : {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
