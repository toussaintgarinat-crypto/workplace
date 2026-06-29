"""Validation JWT Keycloak pour la brique « donnees » — activable par env.

La logique Keycloak (cache JWKS + verify_aud conditionnel) vit désormais dans la lib
partagée du monorepo `shared/workplace_auth.py` (S120) : une seule source de vérité au
lieu d'une copie par brique. Ce module ne garde que l'adaptation propre à `donnees` —
config lue à l'import depuis l'environnement + la dependency FastAPI `garde_auth`.

Portabilité bundle : `shared/` est embarquée dans chaque bundle livré (le moteur de
bundle la copie + le Dockerfile la `COPY` — cf. bundle.py S120). La brique n'est donc
plus « self-contained » mais reste autonome au sein du monorepo et des bundles.

Comportement piloté par l'environnement, rétrocompatible par défaut :
- AUTH_ENABLED absent / "false"  → garde no-op : la brique reste ouverte (donnees
  central de dev inchangé, aucune régression).
- AUTH_ENABLED "true"            → tout appel CRUD exige un Bearer Keycloak valide,
  sinon 401. Le packager pose ce flag (+ KEYCLOAK_URL/REALM) sur le service du bundle.

Multi-tenant : audience vide ⇒ verify_aud désactivé (le realm du bundle suffit à isoler).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from shared.workplace_auth import KeycloakSettings, verify_token_sync

# Tenant de repli quand aucune organisation n'est résolue (instance ouverte / pré-S121).
ORG_DEFAUT = "defaut"

# ── Configuration (lue à l'import, depuis l'environnement) ──────────────────────

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "oui", "yes")
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "").rstrip("/")          # ex: http://identite:8080
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "")                  # ex: client-acme
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "").strip()    # vide ⇒ verify_aud off
JWKS_TTL = int(os.getenv("JWKS_TTL", "600"))                      # cache des clés (s)

# Réglages Keycloak partagés (porte le cache JWKS interne). Construit à l'import depuis
# l'environnement : le comportement reste figé pour la durée de vie du process.
_KC = KeycloakSettings(
    url=KEYCLOAK_URL,
    realm=KEYCLOAK_REALM,
    audience=KEYCLOAK_AUDIENCE,
    jwks_ttl=JWKS_TTL,
)

# auto_error=False : on gère nous-mêmes le 401 (message clair, et no-op si désactivé).
_bearer = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def config_valide() -> bool:
    """L'enforcement n'est réel que si l'URL et le realm sont renseignés."""
    return bool(AUTH_ENABLED and KEYCLOAK_URL and KEYCLOAK_REALM)


def verifier_jeton(token: str) -> dict:
    """Décode et valide un JWT Keycloak. Lève JWTError si invalide."""
    return verify_token_sync(token, _KC)


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


def tenant_actuel(
    claims: Optional[dict] = Depends(garde_auth),
    x_org_id: str | None = Header(None),
) -> str:
    """Organisation propriétaire des données pour la requête courante (S121).

    Scope par **organisation** (une app appartient à un client/org). Priorité :
    1. claim Keycloak ``org_id`` (sinon ``sub``) quand l'auth est réellement active —
       l'identité fait foi, on ne se fie pas à un en-tête falsifiable ;
    2. en-tête ``X-Org-ID`` (chemin S2S : le Cœur le pose depuis son contexte de tenant) ;
    3. ``"defaut"`` — instance ouverte / données pré-S121 (rétrocompatible).

    Renvoie toujours une chaîne non vide → toutes les requêtes SQL sont scopables.
    """
    if claims:  # auth active ET jeton valide → l'org vient du jeton (source de vérité)
        org = claims.get("org_id") or claims.get("organization") or claims.get("sub")
        if org:
            return str(org)
    if x_org_id and x_org_id.strip():
        return x_org_id.strip()
    return ORG_DEFAUT
