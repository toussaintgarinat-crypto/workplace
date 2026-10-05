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
import urllib.parse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import httpx
from fastapi import HTTPException, Request

from shared.workplace_auth import KeycloakSettings, verify_token

import session_registre

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


def _session_perimee(session: dict, sub: str) -> bool:
    """Vrai si `session` porte une génération ou un identifiant de registre périmés pour
    `sub` — factorise la vérification partagée par `exiger_session` et
    `sub_session_optionnel` (Critical 1 + Important 6, revue finale whole-branch) pour que
    les deux chemins d'identité restent verrouillés au même comportement.

    Vérifie deux choses :
    - la génération du cookie contre `session_registre.generation_actuelle(sub)` (une
      connexion plus récente a évincé celle-ci) ;
    - l'identifiant d'instance du registre (`session_registre.identifiant_registre()`)
      contre celui porté par le cookie — nécessaire car une perte du volume `core_data`
      ferait repartir toutes les générations à 1, et un cookie évincé portant justement
      `generation=1` (cas majoritaire) redeviendrait valide par coïncidence numérique sans
      cette vérification supplémentaire (Important 6).

    Best-effort (Important 7) : un hoquet SQLite (registre indisponible, fichier verrouillé…)
    ne doit jamais faire planter l'appelant — `exiger_session` a une discipline explicite de
    ce fichier de ne jamais laisser fuiter un 500 nu sur ce chemin. Un échec du registre est
    donc traité comme « pas périmée » (dégradation côté disponibilité, pas de faux positif
    d'éviction pour une panne qui n'en est pas une).

    Symétrie côté cookie (trouvé à la re-vérification du correctif 500 nu) : si LE REGISTRE
    a une entrée pour `sub` mais que CE cookie n'a pas de `generation` (son propre login a eu
    lieu pendant un hoquet du registre, cf. `auth_callback`), le traiter aussi comme « pas
    périmée » — sinon la connexion réussit sans 500 au login, puis la toute prochaine requête
    protégée rejette l'appareil comme évincé alors qu'aucune éviction n'a réellement eu lieu."""
    try:
        generation_registre = session_registre.generation_actuelle(sub)
        registre_id_actuel = session_registre.identifiant_registre()
    except Exception:
        return False
    if generation_registre is None or session.get("generation") is None:
        # Pas encore d'entrée pour ce compte dans CE registre (cookie antérieur à ce
        # chantier, ou compte pas encore reconnecté depuis une perte de volume), OU ce
        # cookie lui-même n'a jamais reçu de génération (son login a coïncidé avec un hoquet
        # du registre) : on laisse passer dans les deux cas, comportement historique préservé.
        return False
    return (
        session.get("generation") != generation_registre
        or session.get("registre_id") != registre_id_actuel
    )


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

    if _session_perimee(session, sub):
        # Une connexion plus récente a évincé celle-ci (relai propre entre appareils, cf.
        # core/routers/auth.py::auth_callback), ou le registre a été recréé depuis
        # l'émission de ce cookie (perte du volume core_data, Important 6) — voir le
        # détail des deux cas dans la docstring de `_session_perimee`.
        destination = urllib.parse.quote("/dashboard?motif=reprise_ailleurs", safe="")
        raise HTTPException(status_code=303, headers={"Location": f"/auth/login?next={destination}"})

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
    Cookie absent ou corrompu ⇒ `None`, jamais d'exception ni de blocage (S173).

    Depuis le chantier de relai de session (Critical 1, revue finale whole-branch) : si le
    cookie porte une génération périmée (session évincée par une reconnexion ailleurs sur ce
    même compte), renvoie `None` plutôt que le `sub` — l'appelant retombe alors sur son repli
    non bloquant existant (`X-User-Id` / "perso"), sans jamais lever d'exception ici. Avant ce
    correctif, `exiger_session` était le SEUL chemin d'identité à vérifier la génération ;
    `assistant.router`/`agenda.router`/`profil.router` (montés avec `lire_contexte_tenant`,
    qui appelle cette fonction) ne la vérifiaient jamais — un appareil évincé continuait donc
    d'écrire dans le chat et l'agenda sans aucun signal."""
    session = dechiffrer_cookie(request.cookies.get(COOKIE_SESSION))
    if session is None:
        return None
    sub = session.get("sub")
    if not sub:
        return None
    if _session_perimee(session, sub):
        return None
    return sub


def _admins_cerveau() -> set[str]:
    """Subs Keycloak autorisés à modifier le cerveau (`CERVEAU_ADMINS`, séparés par des
    virgules). Relu à chaque appel : se règle dans l'env sans toucher au code, et les tests
    le font varier sans recharger le module."""
    return {s.strip() for s in os.environ.get("CERVEAU_ADMINS", "").split(",") if s.strip()}


_HOTES_LOCAUX = {"localhost", "127.0.0.1", "[::1]"}


def _netloc(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def _origine_autorisee(origine: str, request: Request) -> bool:
    """L'en-tête `Origin` désigne-t-il le Cœur lui-même ?

    Le Cœur n'a pas d'URL publique fixe : il est servi en LAN (IP:5100), sur le mesh (IP
    NetBird via Caddy en HTTPS) et par domaine. On compare donc l'hôte[:port] de l'origine à
    celui de la REQUÊTE (`Host`, ou `X-Forwarded-Host` posé par un proxy), sans le schéma :
    Caddy termine le TLS, le Cœur voit du http alors que le navigateur annonce https.
    S'y ajoute localhost (dev). Pas de liste d'origines tierces (`CORS_ORIGINS` n'est PAS
    consulté, revue S240 M1) : un front servi ailleurs que par le Cœur ne doit pas écrire
    dans le cerveau, et la politique CORS actuelle (sans `allow_credentials`) l'en
    empêcherait de toute façon."""
    hote = _netloc(origine)
    if not hote:
        return False  # « null » (iframe sandbox, fichier local…) ou valeur illisible
    if hote.rsplit(":", 1)[0] in _HOTES_LOCAUX or hote in _HOTES_LOCAUX:
        return True
    hotes_requete = {(request.headers.get("host") or "").lower(),
                     (request.headers.get("x-forwarded-host") or "").split(",")[0].strip().lower()}
    return hote in hotes_requete - {""}


def verifier_anti_csrf(request: Request, corps_json: bool = True) -> None:
    """Refuse une écriture déclenchée depuis une autre origine (revue S240, I1).

    Le cookie de session part avec toute requête vers le Cœur, y compris celle qu'une page
    tierce ouverte dans le navigateur de l'admin forgerait. Trois verrous, du plus fiable au
    plus large :
    - `Sec-Fetch-Site` (posé par le navigateur, non falsifiable par une page) présent et
      différent de `same-origin` → 403 ;
    - `Origin` présent et étranger au Cœur → 403 ;
    - corps non JSON sur POST/PUT/PATCH → 415 : un <form> tiers ne sait envoyer que
      text/plain, urlencoded ou multipart, et un `fetch` JSON cross-origin exige un preflight
      CORS. Une requête SANS corps (DELETE, route sans paramètre) n'est pas concernée.
    Les clients hors navigateur (curl, scripts) n'envoient aucun de ces en-têtes : ils passent
    cette garde et restent soumis à la session.

    ⚠ Garde fondée sur l'ORIGINE (revue S240, I-A) : tout ce qui est servi par le Cœur
    lui-même est « same-origin » — y compris les fronts de briques proxifiés sous son
    origine (`/studio-app/`, `/mail-app/`, `/atelier-images-video-app/`,
    `/atelier-veille-app/`). Une XSS dans l'un d'eux contourne donc cette garde comme une
    XSS du dashboard : leur échappement fait partie du même périmètre de sécurité."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site != "same-origin":
        raise HTTPException(status_code=403, detail=f"Requête d'une autre origine refusée ({site}).")
    origine = request.headers.get("origin")
    if origine is not None and not _origine_autorisee(origine, request):
        raise HTTPException(status_code=403, detail="Origine non autorisée.")
    if corps_json and request.method in ("POST", "PUT", "PATCH"):
        a_un_corps = (request.headers.get("content-length", "0") not in ("", "0")
                      or "transfer-encoding" in request.headers)
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if a_un_corps and ctype != "application/json":
            raise HTTPException(status_code=415, detail="Corps attendu en application/json.")


async def exiger_admin_cerveau(request: Request) -> dict:
    """Dépendance des routes qui MODIFIENT le cerveau (S240) : clés fournisseur, modèle,
    cascade, persona, langue, voix, modèles servis, modèle de la Forge.

    Avant S240, ces routes n'avaient que `lire_contexte_tenant` (non bloquant) : n'importe
    quel appareil du LAN/mesh pouvait poser une clé et la faire servir. Règles :
    - session Cœur exigée (`exiger_session`) ; son 303 vers /auth/login devient ici un 401,
      car ces routes sont appelées en `fetch` (une redirection vers Keycloak y serait suivie
      en silence et finirait en erreur CORS illisible) ;
    - `CERVEAU_ADMINS` vide = toute session valide suffit (foyer mono-compte) ; non vide =
      seuls ces subs passent (403 sinon) ;
    - `AUTH_ENABLED=false` + `CERVEAU_ADMINS` vide : identité factice, comportement historique
      (dev/tests). `AUTH_ENABLED=false` + `CERVEAU_ADMINS` posé : 403 — sans auth, il n'y a
      aucune identité vérifiable, et laisser passer « anonymous » ferait croire à une
      protection qui n'existe pas.

    Les lectures (`GET /assistant/config`…) et le chat (`/assistant/chat`, utilisé par
    Telegram/Mini App/S2S sans session) ne portent PAS cette garde.

    Anti-CSRF d'abord (`verifier_anti_csrf`) : refusée avant même de lire la session."""
    verifier_anti_csrf(request)
    try:
        identite = await exiger_session(request)
    except HTTPException as e:
        if e.status_code == 303:
            quoi = ("lire cette donnée sensible" if request.method in ("GET", "HEAD")
                    else "modifier le cerveau")
            raise HTTPException(status_code=401, detail=f"Session requise pour {quoi}.") from None
        raise
    admins = _admins_cerveau()
    if not admins:
        return identite
    if not AUTH_ENABLED:
        raise HTTPException(status_code=403, detail=(
            "CERVEAU_ADMINS est défini mais AUTH_ENABLED=false : aucune identité "
            "vérifiable, modification du cerveau refusée."))
    if identite.get("sub") not in admins:
        raise HTTPException(status_code=403,
                            detail="Ce compte n'est pas autorisé à modifier le cerveau.")
    return identite


async def admin_cerveau_ou_none(request: Request) -> dict | None:
    """Même règle qu'`exiger_admin_cerveau` (anti-CSRF compris), sans lever : l'identité
    admin, ou None. Sert au chat (route ouverte) pour savoir si le TOUR peut utiliser les
    outils réservés (droits.py, revue S240 C-B)."""
    try:
        return await exiger_admin_cerveau(request)
    except HTTPException:
        return None


async def _session_api(request: Request) -> dict:
    try:
        return await exiger_session(request)
    except HTTPException as e:
        if e.status_code == 303:
            raise HTTPException(status_code=401, detail="Session requise.") from None
        raise


async def exiger_session_api(request: Request) -> dict:
    """Session + anti-CSRF (origine et corps JSON), SANS exiger l'admin du cerveau.

    Routes qui nourrissent le prompt système ou le RAG sans être « le cerveau » : projets
    (`instructions`), profil d'amorçage, identité (revue S240, I-B). 401 plutôt que 303 :
    appelées en `fetch`."""
    verifier_anti_csrf(request)
    return await _session_api(request)


async def exiger_session_api_fichier(request: Request) -> dict:
    """Comme `exiger_session_api`, pour un envoi de fichier (multipart) : contrôle d'origine
    seulement — un <form> tiers sans en-tête Origin ni Sec-Fetch-Site n'existe plus dans les
    navigateurs actuels, et la session reste exigée (`/assistant/document`)."""
    verifier_anti_csrf(request, corps_json=False)
    return await _session_api(request)
