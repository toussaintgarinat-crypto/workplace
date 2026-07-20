"""Authentification Keycloak du dashboard du Cœur (S171).

Le Cœur n'a aujourd'hui aucune authentification utilisateur : `core/routers/dashboard.py`
est monté sans dépendance de session (accès direct). Ce module ajoute un vrai login OIDC
contre le realm Keycloak `forge`, client `assistant-app` — déjà déclaré dans
`oria-stack/infra/keycloak/realms/forge-realm.json`, jamais câblé côté Cœur avant S171.

Portée volontairement étroite : seule la dépendance `exiger_session` protège
`dashboard.router`. Les chemins automatisés (Telegram, `proactif`, outils LLM S2S) ne
passent pas par un navigateur et n'ont pas de session Keycloak — ils continuent d'utiliser
l'identité de service actuelle (`contexte_tenant`, S121), inchangée par ce sprint. Faire
suivre l'identité de session jusqu'aux briques (agenda, restaurant…) est le travail de S173.

Session : cookie chiffré AES-GCM (même motif que le coffre OAuth de l'agenda,
`briques/agenda/backend/vault.py`) — pas de table de session en base. Le cookie porte le
refresh token (chiffré) ; l'access token (courte durée de vie) est mis en cache mémoire
process et rafraîchi silencieusement, ce qui sert aussi de vérification de révocation :
c'est la seule attache vers l'autorité Keycloak une fois le cookie posé.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import httpx
from fastapi import HTTPException, Request

from shared.workplace_auth import KeycloakSettings, verify_token

# ── Configuration (motif `os.environ.get` au niveau module — core/ n'a pas de config.py,
# contrairement à l'agenda ; cf. core/urls_ui.py pour le même motif). ──────────────────
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
# URL Keycloak vue par le NAVIGATEUR (redirection /auth/login, S181) — distincte de
# KEYCLOAK_URL (appels serveur-à-serveur : échange de code, JWKS ; verify_token ne valide
# pas `iss`, les clés JWKS sont indépendantes du hostname) quand Keycloak est joint
# autrement en interne qu'en façade (ex. IP LAN interne vs domaine mesh HTTPS, Caddy,
# KC_HOSTNAME figé). Vide OU absente = repli sur KEYCLOAK_URL (motif `KEY=` du reste du
# monorepo — une variable présente mais vide dans le .env doit se comporter comme absente).
KEYCLOAK_PUBLIC_URL = os.environ.get("KEYCLOAK_PUBLIC_URL", "") or KEYCLOAK_URL
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "forge")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "assistant-app")
KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "assistant-app")
# Désactivable en dev local (même motif que l'agenda) : sans Keycloak qui tourne, le
# dashboard reste accessible en accès direct — comportement historique inchangé.
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
AUTH_SESSION_SECRET = os.environ.get("AUTH_SESSION_SECRET", "")
# Défaut prudent (cookies Secure) — à mettre à `false` en dev local http://localhost,
# sinon le navigateur n'envoie jamais les cookies (Secure exige TLS) et le login boucle.
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() == "true"

COOKIE_SESSION = "wp_session"
COOKIE_PENDING = "wp_auth_pending"
# 30 jours : plafond du cookie, pas la vraie durée de session. La vraie limite est côté
# Keycloak (`ssoSessionMaxLifespan: 36000` = 10h dans forge-realm.json, + idle timeout du
# realm) — le refresh token meurt bien avant ces 30 jours en pratique, et `exiger_session`
# redirige alors normalement vers /auth/login à l'échec du rafraîchissement.
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
PENDING_COOKIE_MAX_AGE = 600  # 10 min pour boucler le callback OIDC

KC = KeycloakSettings(url=KEYCLOAK_URL, realm=KEYCLOAK_REALM, audience=KEYCLOAK_AUDIENCE, jwks_ttl=600)


def jeton_aleatoire(taille: int = 32) -> str:
    """Chaîne aléatoire base64url sans padding, source unique pour PKCE et `state`."""
    return base64.urlsafe_b64encode(os.urandom(taille)).rstrip(b"=").decode()


def generer_pkce() -> tuple[str, str]:
    """Génère (code_verifier, code_challenge) pour le flux PKCE S256 (RFC 7636)."""
    verifier = jeton_aleatoire(40)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _cle_session() -> bytes:
    if not AUTH_SESSION_SECRET:
        raise RuntimeError(
            "AUTH_SESSION_SECRET n'est pas configuré — impossible de chiffrer une session"
        )
    return hashlib.sha256(AUTH_SESSION_SECRET.encode()).digest()


def chiffrer_cookie(payload: dict) -> str:
    """Chiffre un dict JSON en valeur de cookie (AES-GCM, motif du coffre OAuth agenda).

    Générique : sert aussi bien au cookie de session qu'au cookie d'état PKCE en attente."""
    aesgcm = AESGCM(_cle_session())
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, json.dumps(payload).encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def dechiffrer_cookie(valeur: str | None) -> dict | None:
    """Déchiffre une valeur de cookie ; None si absente, corrompue ou mauvaise clé —
    jamais d'exception (un cookie invalide doit se traiter comme « pas de session »)."""
    if not valeur:
        return None
    try:
        blob = base64.urlsafe_b64decode(valeur.encode())
        aesgcm = AESGCM(_cle_session())
        brut = aesgcm.decrypt(blob[:12], blob[12:], None)
        return json.loads(brut)
    except Exception:
        return None


def _token_endpoint() -> str:
    return f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"


async def echanger_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Échange un code d'autorisation contre un couple access/refresh token."""
    async with httpx.AsyncClient() as client:
        r = await client.post(_token_endpoint(), data={
            "grant_type": "authorization_code",
            "client_id": KEYCLOAK_CLIENT_ID,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        })
    r.raise_for_status()
    return r.json()


async def rafraichir_access_token(refresh_token: str) -> dict:
    """Échange un refresh token contre un nouveau couple access/refresh token — c'est ce
    rafraîchissement, tenté contre Keycloak, qui sert de vérification de révocation."""
    async with httpx.AsyncClient() as client:
        r = await client.post(_token_endpoint(), data={
            "grant_type": "refresh_token",
            "client_id": KEYCLOAK_CLIENT_ID,
            "refresh_token": refresh_token,
        })
    r.raise_for_status()
    return r.json()


_cache_access_token: dict[str, tuple[str, float]] = {}


async def exiger_session(request: Request) -> dict:
    """Dépendance FastAPI : exige une session Cœur valide.

    AUTH_ENABLED=false (défaut dev/tests) : identité factice, comportement historique
    inchangé. AUTH_ENABLED=true : lit le cookie de session chiffré, rafraîchit l'access
    token si le cache mémoire est froid ou absent — ce rafraîchissement sert aussi de
    vérification de révocation (seule attache vers l'autorité Keycloak une fois le cookie
    posé). Absence de session ou échec ⇒ 303 vers /auth/login (une HTTPException avec un
    header Location fonctionne pour une navigation top-level : Starlette inclut les
    `headers` de l'exception dans la réponse renvoyée au navigateur)."""
    if not AUTH_ENABLED:
        return {"sub": "anonymous", "nom": None, "avatarEmoji": None}

    session = dechiffrer_cookie(request.cookies.get(COOKIE_SESSION))
    sub = session.get("sub") if session else None
    refresh_token = session.get("refresh_token") if session else None
    if not sub or not refresh_token:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})

    maintenant = time.time()
    cache = _cache_access_token.get(sub)
    if not cache or cache[1] <= maintenant:
        try:
            # `tokens["refresh_token"]` ci-dessous n'est PAS repersisté dans le cookie (la
            # dépendance n'a que `Request`, pas `Response`) : ça marche seulement parce que
            # le realm forge n'active pas la rotation des refresh tokens (l'ancien reste
            # valide). Si un opérateur active cette option de durcissement Keycloak un
            # jour, la session tombera toutes les ~5 min (durée de l'access token) — à
            # revoir alors (répercuter le nouveau refresh token via un cookie de réponse).
            tokens = await rafraichir_access_token(refresh_token)
            payload = await verify_token(tokens["access_token"], KC)
        except Exception:
            raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
        expire_a = maintenant + tokens.get("expires_in", 60) - 10
        _cache_access_token[sub] = (tokens["access_token"], expire_a)
        session["nom"] = payload.get("nom", session.get("nom"))
        session["avatarEmoji"] = payload.get("avatarEmoji", session.get("avatarEmoji"))

    return {"sub": sub, "nom": session.get("nom"), "avatarEmoji": session.get("avatarEmoji")}


def sub_session_optionnel(request: Request) -> str | None:
    """Sub Keycloak de la session S171 si le cookie est présent et valide, sinon `None`.

    Volontairement léger : pas de vérification de fraîcheur du token (pas un point de
    sécurité — sert seulement à attribuer « pour qui » dans le chat de l'assistant ; le
    vrai contrôle d'accès reste `require_calendar_access` côté agenda, inchangé).
    Cookie absent ou corrompu ⇒ `None`, jamais d'exception ni de blocage (S173)."""
    session = dechiffrer_cookie(request.cookies.get(COOKIE_SESSION))
    return session.get("sub") if session else None
