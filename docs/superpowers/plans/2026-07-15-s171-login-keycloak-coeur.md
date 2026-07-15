# S171 — Login Keycloak réel pour le dashboard du Cœur — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner au Cœur (`core/`) une vraie authentification utilisateur (login Keycloak OIDC PKCE) pour son dashboard, aujourd'hui en accès direct sans aucune notion de « qui regarde ».

**Architecture:** Flux Authorization Code + PKCE standard contre le realm Keycloak `forge` (client `assistant-app`, déjà déclaré, jamais câblé). Nouveau module `core/auth.py` (crypto de session + échanges Keycloak) et `core/routers/auth.py` (3 routes). Session portée par un cookie chiffré AES-GCM (pas de table en base) ; seul `dashboard.router` est protégé, tout le reste du Cœur (Telegram, proactif, outils LLM S2S) reste inchangé.

**Tech Stack:** FastAPI, `httpx` (déjà présent), `python-jose` + `cryptography` (à ajouter, versions alignées sur `briques/agenda/backend/requirements.txt`), `shared/workplace_auth.py` (lib JWT Keycloak partagée, réutilisée telle quelle).

## Global Constraints

- Réutiliser `shared/workplace_auth.py` (`KeycloakSettings`, `verify_token`) sans le modifier — ne pas réimplémenter la vérification JWT.
- Realm `forge`, client `assistant-app` (déjà déclaré dans `oria-stack/infra/keycloak/realms/forge-realm.json:128-222`) — ne pas créer de nouveau client Keycloak.
- Portée strictement limitée à `dashboard.router` : `usine`/`assistant`/`agenda`/`profil` gardent `lire_contexte_tenant` inchangé, aucune régression sur ces chemins.
- Style du monorepo dans `core/` : noms de fonctions en français, constantes de config en `os.environ.get(...)` au niveau module (pas de `config.py` — ce fichier n'existe pas dans `core/`, contrairement à l'agenda), docstrings expliquant le « pourquoi ».
- `AUTH_ENABLED` défaut `false` : comportement historique (mono-user, `/dashboard` accessible sans session) inchangé pour les tests et le dev local existants — non-régression obligatoire sur `core/test_dashboard.py`.
- Mocking HTTP dans les tests du Cœur : motif `module.httpx.AsyncClient = _FakeClient` (déjà restauré automatiquement entre tests par `core/conftest.py::_isoler_globaux_partages`, `"httpx": ("AsyncClient",)` déjà présent — ne pas ajouter d'entrée, elle couvre tout module import du `httpx` global).

---

## File Structure

- **Create `core/auth.py`** : constantes de config, crypto de session (PKCE, chiffrement AES-GCM du cookie), échanges Keycloak (code→tokens, refresh), dépendance FastAPI `exiger_session`.
- **Create `core/routers/auth.py`** : 3 routes (`/auth/login`, `/auth/callback`, `/auth/logout`), consomme `core/auth.py`.
- **Create `core/test_auth.py`** : tests des fonctions pures et de la dépendance (crypto, PKCE, échanges Keycloak mockés, `exiger_session`).
- **Create `core/test_auth_routes.py`** : tests des 3 routes via `TestClient` + non-régression de `/dashboard`.
- **Modify `core/conftest.py`** : shim `sys.path` vers la racine du monorepo (pour `shared.workplace_auth`), même motif que `briques/agenda/backend/conftest.py` — actuellement absent, `shared/` n'est importable ni en test ni en run natif.
- **Modify `core/main.py`** : monte `routers.auth`, protège `dashboard.router` avec `Depends(exiger_session)`.
- **Modify `core/requirements.txt`** : ajoute `python-jose==3.3.0` + `cryptography==43.0.3` (mêmes pins que l'agenda).
- **Modify `core/docker-compose.yml`** + **`core/Dockerfile`** : build-context → racine du monorepo (comme l'agenda), pour embarquer `shared/` dans l'image.
- **Modify `oria-stack/infra/keycloak/realms/forge-realm.json`** : `redirectUris`/`webOrigins` du client `assistant-app`, obsolètes (`localhost:8300`) → port réel du Cœur (`localhost:5100`).

---

### Task 1: Crypto de session + PKCE (fonctions pures, `core/auth.py`)

**Files:**
- Create: `core/auth.py`
- Test: `core/test_auth.py`

**Interfaces:**
- Produces: `jeton_aleatoire(taille: int = 32) -> str`, `generer_pkce() -> tuple[str, str]` (verifier, challenge), `chiffrer_cookie(payload: dict) -> str`, `dechiffrer_cookie(valeur: str | None) -> dict | None`. Constantes : `AUTH_SESSION_SECRET: str`, `AUTH_ENABLED: bool`, `AUTH_COOKIE_SECURE: bool`, `COOKIE_SESSION = "wp_session"`, `COOKIE_PENDING = "wp_auth_pending"`, `SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30`, `PENDING_COOKIE_MAX_AGE = 600`.

- [ ] **Step 1: Write the failing tests**

Create `core/test_auth.py` :

```python
"""Tests du login Keycloak du Cœur (S171).

$ cd core && python3 -m pytest test_auth.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import auth  # noqa: E402


def test_generer_pkce_format():
    verifier, challenge = auth.generer_pkce()
    assert 43 <= len(verifier) <= 128
    assert verifier != challenge
    # Base64url sans padding : ni '+', '/', ni '='.
    for c in verifier + challenge:
        assert c not in "+/="


def test_generer_pkce_est_aleatoire():
    v1, _ = auth.generer_pkce()
    v2, _ = auth.generer_pkce()
    assert v1 != v2


def test_chiffrer_dechiffrer_cookie_roundtrip():
    payload = {"sub": "marina", "refresh_token": "rt-123"}
    cookie = auth.chiffrer_cookie(payload)
    assert isinstance(cookie, str)
    assert auth.dechiffrer_cookie(cookie) == payload


def test_dechiffrer_cookie_vide_renvoie_none():
    assert auth.dechiffrer_cookie(None) is None
    assert auth.dechiffrer_cookie("") is None


def test_dechiffrer_cookie_corrompu_renvoie_none():
    assert auth.dechiffrer_cookie("pas-du-tout-un-cookie-valide") is None


def test_dechiffrer_cookie_mauvaise_cle_renvoie_none():
    cookie = auth.chiffrer_cookie({"sub": "marina"})
    ancienne_cle = auth.AUTH_SESSION_SECRET
    auth.AUTH_SESSION_SECRET = "une-autre-cle-totalement-differente"
    try:
        assert auth.dechiffrer_cookie(cookie) is None
    finally:
        auth.AUTH_SESSION_SECRET = ancienne_cle
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'` (le fichier n'existe pas encore).

- [ ] **Step 3: Write minimal implementation**

Create `core/auth.py` :

```python
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

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ── Configuration (motif `os.environ.get` au niveau module — core/ n'a pas de config.py,
# contrairement à l'agenda ; cf. core/urls_ui.py pour le même motif). ──────────────────
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "forge")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "assistant-app")
KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "assistant-app")
# Désactivable en dev local (même motif que l'agenda) : sans Keycloak qui tourne, le
# dashboard reste accessible en accès direct — comportement historique inchangé.
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
AUTH_SESSION_SECRET = os.environ.get("AUTH_SESSION_SECRET", "")
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() == "true"

COOKIE_SESSION = "wp_session"
COOKIE_PENDING = "wp_auth_pending"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours ; la vraie limite est le refresh Keycloak
PENDING_COOKIE_MAX_AGE = 600  # 10 min pour boucler le callback OIDC


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_auth.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add core/auth.py core/test_auth.py
git commit -m "feat(coeur): crypto de session + PKCE pour le login Keycloak (S171)"
```

---

### Task 2: `shared/` importable côté Cœur + échanges Keycloak (code→tokens, refresh)

**Files:**
- Modify: `core/conftest.py`
- Modify: `core/auth.py`
- Modify: `core/test_auth.py`
- Modify: `core/docker-compose.yml`
- Modify: `core/Dockerfile`

**Interfaces:**
- Consumes: `shared.workplace_auth.KeycloakSettings`, `shared.workplace_auth.verify_token` (existants, non modifiés).
- Produces: `auth.KC: KeycloakSettings`, `async auth.echanger_code(code: str, code_verifier: str, redirect_uri: str) -> dict`, `async auth.rafraichir_access_token(refresh_token: str) -> dict`.

- [ ] **Step 1: Corriger l'import de `shared/` (sys.path pour les tests natifs)**

`shared/` est à la racine du monorepo ; `core/` n'a pas de `__init__.py`, donc pytest insère
`core/` (pas la racine) sur `sys.path` — `from shared.workplace_auth import ...` échouerait
sinon. Même correctif que `briques/agenda/backend/conftest.py`.

Modify `core/conftest.py`, ajouter en tête de fichier (avant les imports existants) :

```python
import sys
from pathlib import Path

# core/conftest.py → racine du monorepo = 1 niveau au-dessus. Rend `shared.*` importable
# quand les tests tournent nativement (make test-core exécute `pytest core` depuis la
# racine, mais core/ n'a pas de __init__.py : pytest insère core/ sur sys.path, pas la
# racine — même piège et même correctif que briques/agenda/backend/conftest.py).
_RACINE = Path(__file__).resolve().parents[1]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))
```

- [ ] **Step 2: Write the failing test (échange de code, refresh, mockés via httpx)**

Append to `core/test_auth.py` :

```python
class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None):
        APPELS.append((url, data))
        if data.get("grant_type") == "authorization_code":
            return _Resp({"access_token": "at-123", "refresh_token": "rt-123", "expires_in": 300})
        if data.get("grant_type") == "refresh_token":
            return _Resp({"access_token": "at-456", "refresh_token": "rt-456", "expires_in": 300})
        return _Resp({}, status=400)


APPELS = []


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_echanger_code_appelle_le_bon_endpoint():
    APPELS.clear()
    auth.httpx.AsyncClient = _FakeClient
    r = _run(auth.echanger_code("code-abc", "verifier-xyz", "http://localhost:5100/auth/callback"))
    assert r == {"access_token": "at-123", "refresh_token": "rt-123", "expires_in": 300}
    url, data = APPELS[0]
    assert url == f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/token"
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "code-abc"
    assert data["code_verifier"] == "verifier-xyz"
    assert data["client_id"] == auth.KEYCLOAK_CLIENT_ID


def test_rafraichir_access_token_appelle_le_bon_endpoint():
    APPELS.clear()
    auth.httpx.AsyncClient = _FakeClient
    r = _run(auth.rafraichir_access_token("rt-123"))
    assert r["access_token"] == "at-456"
    url, data = APPELS[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "rt-123"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_auth.py -v -k echanger_code or refresh`
Expected: FAIL — `AttributeError: module 'auth' has no attribute 'httpx'` (pas encore importé).

- [ ] **Step 4: Write minimal implementation**

Modify `core/auth.py`, ajouter après les imports existants :

```python
import httpx

from shared.workplace_auth import KeycloakSettings, verify_token

KC = KeycloakSettings(url=KEYCLOAK_URL, realm=KEYCLOAK_REALM, audience=KEYCLOAK_AUDIENCE, jwks_ttl=600)
```

Et à la fin du fichier :

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_auth.py -v`
Expected: 8 passed.

- [ ] **Step 6: Corriger le build Docker pour embarquer `shared/`**

`core/docker-compose.yml` construit aujourd'hui avec `build: .` (contexte = `core/` seul)
— `shared/` (racine du monorepo) n'est PAS copiée dans l'image, contrairement à l'agenda
(`briques/agenda/docker-compose.yml`, `context: ../..`). `import shared.workplace_auth`
casserait le conteneur en prod sans ce correctif.

Modify `core/docker-compose.yml:4`, remplacer :

```yaml
    build: .
```

par :

```yaml
    build:
      context: ..
      dockerfile: core/Dockerfile
```

Modify `core/Dockerfile`, remplacer :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
```

par :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Lib partagée du monorepo (S120 : shared.workplace_auth), importable en `shared` — même
# motif que briques/agenda/backend/Dockerfile.
COPY shared/ /app/shared/

COPY core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ .
```

(Le reste du Dockerfile — `EXPOSE`, `CMD uvicorn` — est inchangé.)

Pas de test automatisé pour ce correctif (build Docker, pas de suite `pytest` dessus) —
vérifié au prochain rebuild LIVE, comme le reste des preuves de déploiement de ce dépôt.
Vérification minimale immédiate (pas de rebuild complet) :

Run: `grep -n "COPY shared" core/Dockerfile`
Expected: `COPY shared/ /app/shared/`

- [ ] **Step 7: Commit**

```bash
git add core/auth.py core/test_auth.py core/conftest.py core/docker-compose.yml core/Dockerfile
git commit -m "feat(coeur): échanges Keycloak (code/refresh) + shared/ importable et embarquée (S171)"
```

---

### Task 3: Dépendance `exiger_session`

**Files:**
- Modify: `core/auth.py`
- Modify: `core/test_auth.py`

**Interfaces:**
- Consumes: `auth.dechiffrer_cookie`, `auth.rafraichir_access_token`, `auth.verify_token`, `auth.KC`, `auth.AUTH_ENABLED`, `auth.COOKIE_SESSION`.
- Produces: `async auth.exiger_session(request: fastapi.Request) -> dict` (retourne `{"sub", "nom", "avatarEmoji"}`), module-level `auth._cache_access_token: dict[str, tuple[str, float]]`.

- [ ] **Step 1: Write the failing tests**

Append to `core/test_auth.py` :

```python
from fastapi import HTTPException
from starlette.requests import Request


def _fake_request(cookies: dict) -> Request:
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    scope = {
        "type": "http",
        "headers": [(b"cookie", cookie_header.encode())] if cookies else [],
    }
    return Request(scope)


def test_exiger_session_auth_desactivee_renvoie_anonyme():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = False
    try:
        r = _run(auth.exiger_session(_fake_request({})))
        assert r == {"sub": "anonymous", "nom": None, "avatarEmoji": None}
    finally:
        auth.AUTH_ENABLED = ancien


def test_exiger_session_sans_cookie_redirige_vers_login():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        try:
            _run(auth.exiger_session(_fake_request({})))
            assert False, "devait lever HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 303
            assert exc.headers["Location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien


def test_exiger_session_cookie_valide_rafraichit_et_verifie():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth.httpx.AsyncClient = _FakeClient
    auth._cache_access_token.clear()

    async def _verify_fake(token, kc):
        return {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}

    ancien_verify = auth.verify_token
    auth.verify_token = _verify_fake
    try:
        cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-123"})
        r = _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
        assert r == {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}
        assert "marina" in auth._cache_access_token
    finally:
        auth.AUTH_ENABLED = ancien
        auth.verify_token = ancien_verify
        auth._cache_access_token.clear()


def test_exiger_session_cache_chaud_ne_rafraichit_pas():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()
    import time
    auth._cache_access_token["marina"] = ("at-cache", time.time() + 60)
    try:
        cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-123", "nom": "Marina", "avatarEmoji": "🌙"})

        class _ClientQuiEchoue:
            def __init__(self, *a, **k):
                raise AssertionError("ne doit pas être appelé : cache chaud")

        auth.httpx.AsyncClient = _ClientQuiEchoue
        r = _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
        assert r == {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()


def test_exiger_session_refresh_echoue_redirige_vers_login():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()

    class _ClientQuiEchoue:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            return _Resp({"error": "invalid_grant"}, status=400)

    auth.httpx.AsyncClient = _ClientQuiEchoue
    try:
        cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-revoque"})
        try:
            _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
            assert False, "devait lever HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 303
            assert exc.headers["Location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_auth.py -v -k exiger_session`
Expected: FAIL — `AttributeError: module 'auth' has no attribute 'exiger_session'`.

- [ ] **Step 3: Write minimal implementation**

Modify `core/auth.py`, ajouter à l'import FastAPI (nouveau) et à la fin du fichier :

```python
import time

from fastapi import HTTPException, Request

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
            tokens = await rafraichir_access_token(refresh_token)
            payload = await verify_token(tokens["access_token"], KC)
        except Exception:
            raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
        expire_a = maintenant + tokens.get("expires_in", 60) - 10
        _cache_access_token[sub] = (tokens["access_token"], expire_a)
        session["nom"] = payload.get("nom", session.get("nom"))
        session["avatarEmoji"] = payload.get("avatarEmoji", session.get("avatarEmoji"))

    return {"sub": sub, "nom": session.get("nom"), "avatarEmoji": session.get("avatarEmoji")}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_auth.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add core/auth.py core/test_auth.py
git commit -m "feat(coeur): dependance exiger_session (refresh transparent + cache) (S171)"
```

---

### Task 4: Routes `/auth/login`, `/auth/callback`, `/auth/logout`

**Files:**
- Create: `core/routers/auth.py`
- Create: `core/test_auth_routes.py`

**Interfaces:**
- Consumes: `auth.jeton_aleatoire`, `auth.generer_pkce`, `auth.chiffrer_cookie`, `auth.dechiffrer_cookie`, `auth.echanger_code`, `auth.verify_token`, `auth.KC`, `auth.KEYCLOAK_URL`, `auth.KEYCLOAK_REALM`, `auth.KEYCLOAK_CLIENT_ID`, `auth.COOKIE_SESSION`, `auth.COOKIE_PENDING`, `auth.SESSION_COOKIE_MAX_AGE`, `auth.PENDING_COOKIE_MAX_AGE`, `auth.AUTH_COOKIE_SECURE`.
- Produces: `router = APIRouter(...)` avec 3 routes ; la route callback est nommée `"auth_callback"` (pour `request.url_for("auth_callback")`).

- [ ] **Step 1: Write the failing tests**

Create `core/test_auth_routes.py` :

```python
"""Tests des routes /auth/* du Cœur (S171).

$ cd core && python3 -m pytest test_auth_routes.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import main  # noqa: E402
import auth  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_login_redirige_vers_keycloak_avec_pkce():
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith(f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth?")
    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
    assert f"client_id={auth.KEYCLOAK_CLIENT_ID}" in location
    assert auth.COOKIE_PENDING in r.cookies


def test_callback_state_invalide_renvoie_400():
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": "state-different"},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 400


def test_callback_ok_pose_session_et_redirige_dashboard(monkeypatch):
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    pending = auth.dechiffrer_cookie(pending_cookie)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        assert code == "code-abc"
        assert code_verifier == pending["code_verifier"]
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": pending["state"]},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 307
    assert r2.headers["location"] == "/dashboard"
    session = auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])
    assert session["sub"] == "marina"
    assert session["refresh_token"] == "rt-1"


def test_logout_supprime_le_cookie_de_session():
    r = client.post("/auth/logout", follow_redirects=False)
    assert r.status_code == 303
    # httpx TestClient expose la suppression via un cookie expiré (Max-Age=0) dans les headers.
    set_cookie = r.headers.get("set-cookie", "")
    assert auth.COOKIE_SESSION in set_cookie
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_auth_routes.py -v`
Expected: FAIL — `AttributeError: module 'routers' has no attribute 'auth'` ou 404 sur `/auth/login` (le router n'existe pas / n'est pas monté).

- [ ] **Step 3: Write minimal implementation**

Create `core/routers/auth.py` :

```python
"""Routes d'authentification du Cœur (S171) — login/callback/logout OIDC PKCE contre le
realm Keycloak `forge`, client `assistant-app` (déjà déclaré, jamais câblé avant S171)."""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import auth

router = APIRouter(tags=["auth"])


@router.get("/auth/login")
async def auth_login(request: Request):
    verifier, challenge = auth.generer_pkce()
    state = auth.jeton_aleatoire()
    redirect_uri = str(request.url_for("auth_callback"))
    pending = auth.chiffrer_cookie({
        "code_verifier": verifier,
        "state": state,
        "redirect_uri": redirect_uri,
    })

    params = {
        "client_id": auth.KEYCLOAK_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = (
        f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth"
        f"?{urllib.parse.urlencode(params)}"
    )
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(
        auth.COOKIE_PENDING, pending,
        httponly=True, secure=auth.AUTH_COOKIE_SECURE, samesite="lax",
        max_age=auth.PENDING_COOKIE_MAX_AGE,
    )
    return resp


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str, state: str):
    pending = auth.dechiffrer_cookie(request.cookies.get(auth.COOKIE_PENDING))
    if pending is None or pending.get("state") != state:
        raise HTTPException(status_code=400, detail="Requête d'authentification invalide ou expirée")

    tokens = await auth.echanger_code(code, pending["code_verifier"], pending["redirect_uri"])
    payload = await auth.verify_token(tokens["access_token"], auth.KC)

    session = {
        "sub": payload["sub"],
        "nom": payload.get("nom"),
        "avatarEmoji": payload.get("avatarEmoji"),
        "refresh_token": tokens["refresh_token"],
    }
    resp = RedirectResponse("/dashboard", status_code=307)
    resp.set_cookie(
        auth.COOKIE_SESSION, auth.chiffrer_cookie(session),
        httponly=True, secure=auth.AUTH_COOKIE_SECURE, samesite="lax",
        max_age=auth.SESSION_COOKIE_MAX_AGE,
    )
    resp.delete_cookie(auth.COOKIE_PENDING)
    return resp


@router.post("/auth/logout")
async def auth_logout():
    resp = RedirectResponse("/auth/login", status_code=303)
    resp.delete_cookie(auth.COOKIE_SESSION)
    return resp
```

- [ ] **Step 4: Monter le router (sans quoi les tests 404)**

Modify `core/main.py:23`, remplacer :

```python
from routers import agenda, assistant, dashboard, profil, systeme, usine
```

par :

```python
from routers import agenda, assistant, dashboard, profil, systeme, usine
from routers import auth as routeur_auth
```

Modify `core/main.py:81`, remplacer :

```python
app.include_router(systeme.router)
```

par :

```python
app.include_router(systeme.router)
app.include_router(routeur_auth.router)
```

(Cette route de montage n'a pas besoin de `Depends(exiger_session)` — ce sont les routes
de login elles-mêmes, protéger `dashboard.router` est le Task 5.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_auth_routes.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add core/routers/auth.py core/test_auth_routes.py core/main.py
git commit -m "feat(coeur): routes /auth/login /auth/callback /auth/logout (S171)"
```

---

### Task 5: Protéger `dashboard.router` + dépendances Python

**Files:**
- Modify: `core/main.py`
- Modify: `core/requirements.txt`
- Modify: `core/test_auth_routes.py`

**Interfaces:**
- Consumes: `auth.exiger_session` (Task 3), `routers.dashboard.router` (existant, inchangé).

- [ ] **Step 1: Write the failing test (non-régression + protection)**

Append to `core/test_auth_routes.py` :

```python
def test_dashboard_accessible_sans_session_quand_auth_desactivee():
    """Non-régression : AUTH_ENABLED=false (défaut) — comportement historique inchangé,
    /dashboard reste accessible en accès direct (core/test_dashboard.py doit continuer
    de passer sans modification)."""
    assert auth.AUTH_ENABLED is False
    r = client.get("/dashboard")
    assert r.status_code == 200


def test_dashboard_redirige_vers_login_quand_auth_activee():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        r = client.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien


def test_dashboard_accessible_avec_session_valide_quand_auth_activee():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()
    try:
        cookie = auth.chiffrer_cookie({
            "sub": "marina", "refresh_token": "rt-1", "nom": "Marina", "avatarEmoji": "🌙",
        })
        import time
        auth._cache_access_token["marina"] = ("at-cache", time.time() + 60)
        r = client.get("/dashboard", cookies={auth.COOKIE_SESSION: cookie})
        assert r.status_code == 200
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_auth_routes.py -v -k dashboard`
Expected: FAIL sur `test_dashboard_redirige_vers_login_quand_auth_activee` (`/dashboard`
renvoie 200 même avec `AUTH_ENABLED=True`, aucune dépendance posée).

- [ ] **Step 3: Write minimal implementation**

Modify `core/main.py`, ajouter l'import de `exiger_session` après les imports existants
(ligne 21, à côté de `from contexte_tenant import lire_contexte_tenant`) :

```python
from auth import exiger_session
```

Modify `core/main.py:83`, remplacer :

```python
app.include_router(dashboard.router)
```

par :

```python
app.include_router(dashboard.router, dependencies=[Depends(exiger_session)])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_auth_routes.py test_dashboard.py -v`
Expected: tous passent, y compris `core/test_dashboard.py` inchangé (non-régression).

- [ ] **Step 5: Ajouter les dépendances Python manquantes**

Modify `core/requirements.txt`, ajouter à la fin :

```
python-jose==3.3.0
cryptography==43.0.3
```

Run: `cd core && pip install -r requirements.txt`
Expected: installation sans erreur (versions déjà éprouvées côté agenda).

- [ ] **Step 6: Run the full core suite (non-régression globale)**

Run: `cd core && python3 -m pytest . -v 2>&1 | tail -30`
Expected: aucune régression sur les suites existantes (`test_dashboard.py`,
`test_agenda_etiquettes_proxys.py`, etc.) — seuls les nouveaux tests `test_auth*.py`
s'ajoutent au total.

- [ ] **Step 7: Commit**

```bash
git add core/main.py core/requirements.txt core/test_auth_routes.py
git commit -m "feat(coeur): dashboard.router protege par exiger_session (S171)"
```

---

### Task 6: Corriger le client Keycloak `assistant-app` (infra, hors TDD)

**Files:**
- Modify: `oria-stack/infra/keycloak/realms/forge-realm.json`

**Interfaces:**
- N/A (config Keycloak statique, pas de code Python).

- [ ] **Step 1: Corriger les redirect URIs obsolètes**

`oria-stack/infra/keycloak/realms/forge-realm.json:128-222` déclare le client
`assistant-app` avec `redirectUris: ["http://localhost:8300/*"]` — port obsolète, le Cœur
tourne réellement sur `5100:5000` (`core/docker-compose.yml:9-10`).

Modify `oria-stack/infra/keycloak/realms/forge-realm.json`, dans le client
`"clientId": "assistant-app"`, remplacer :

```json
      "redirectUris": [
        "http://localhost:8300/*"
      ],
      "webOrigins": [
        "http://localhost:8300"
      ],
      "attributes": {
        "pkce.code.challenge.method": "S256",
        "post.logout.redirect.uris": "http://localhost:8300/*"
      },
```

par :

```json
      "redirectUris": [
        "http://localhost:5100/*"
      ],
      "webOrigins": [
        "http://localhost:5100"
      ],
      "attributes": {
        "pkce.code.challenge.method": "S256",
        "post.logout.redirect.uris": "http://localhost:5100/*"
      },
```

- [ ] **Step 2: Vérifier la syntaxe JSON**

Run: `python3 -c "import json; json.load(open('oria-stack/infra/keycloak/realms/forge-realm.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Documenter le réimport Keycloak (pas de test automatisé — infra, preuve LIVE différée)**

`--import-realm` (déjà en place sur le conteneur Keycloak, cf. `oria-stack/infra/keycloak/docker-compose.yml`) ne réimporte PAS un realm déjà existant sur un volume déjà initialisé.
Comme `forge-realm.json` déclare `"users": null` (aucun compte réel encore créé, S172 s'en charge),
un realm déjà démarré localement peut être réinitialisé sans perte : `docker compose down -v keycloak && docker compose up -d keycloak` (recrée le volume, réimporte le JSON corrigé). Sur un environnement où de vrais comptes existeraient déjà, préférer une mise à jour via l'API admin Keycloak plutôt qu'un wipe — non applicable ici (pas encore de comptes avant S172).

Pas de step de test ici : la preuve que Keycloak accepte bien le callback sur
`localhost:5100/auth/callback` se fait au lancement LIVE du flux complet (Task 7), pas en
suite `pytest` (cohérent avec le régime de preuve Docker différé du projet).

- [ ] **Step 4: Commit**

```bash
git add oria-stack/infra/keycloak/realms/forge-realm.json
git commit -m "fix(oria-stack): redirectUris assistant-app obsoletes (8300) -> port reel du Coeur (5100)"
```

---

### Task 7: Vérification manuelle du flux complet (LIVE, hors suite automatisée)

**Files:** aucun (vérification, pas de code).

- [ ] **Step 1: Démarrer Keycloak + le Cœur en local**

Run: `docker compose -f oria-stack/infra/keycloak/docker-compose.yml up -d keycloak`
Run: `AUTH_ENABLED=true AUTH_SESSION_SECRET=$(openssl rand -hex 32) AUTH_COOKIE_SECURE=false KEYCLOAK_URL=http://localhost:8081 docker compose -f core/docker-compose.yml up -d --build core`

(`--build` obligatoire — cf. [[piege-launcher-sans-rebuild]], `up -d` seul réutiliserait
l'image périmée sans les fichiers de S171.)

- [ ] **Step 2: Ouvrir le navigateur sur `http://localhost:5100/dashboard`**

Expected: redirection vers l'écran de login Keycloak (realm `forge`).

- [ ] **Step 3: Se connecter avec le compte principal existant (créé via S23/provisioning ou compte admin Keycloak manuel — S172 automatisera un vrai provisioning pour Marina)**

Expected: retour sur `/dashboard`, accès normal, aucune régression visible sur les onglets existants.

- [ ] **Step 4: Vérifier la persistance de session après rechargement**

Expected: recharger `/dashboard` ne redemande pas de login (cookie de session valide).

- [ ] **Step 5: Vérifier le logout**

Run: ouvrir `http://localhost:5100/auth/logout` (ou bouton logout si ajouté à l'UI plus tard — hors périmètre S171, pas de bouton dans le dashboard pour ce sprint) via `curl -X POST http://localhost:5100/auth/logout -i`
Expected: cookie de session supprimé (`Set-Cookie: wp_session=; Max-Age=0`), accès suivant à `/dashboard` redemande le login.

Marquer S171 CODE-COMPLET + LIVE DIFFÉRÉ tant que cette vérification manuelle n'a pas été
rejouée sur le HP (cf. [[regime-preuve-docker-differe]]).

---

## Self-Review (fait pendant l'écriture de ce plan)

**1. Couverture de la spec** : flux OIDC PKCE (Tasks 2/4), session cookie AES-GCM (Task 1),
refresh transparent = vérification de révocation (Task 3), portée étroite dashboard-only
(Task 5), correctifs `assistant-app`/redirect URIs (Task 6). Le point « pas de table de
session, restart ne perd rien » de la spec est assuré par construction (état 100% dans le
cookie + cache mémoire reconstruit au premier accès) — aucun test dédié nécessaire, c'est
une propriété du design, pas un comportement à vérifier isolément.

**2. Placeholders** : aucun TBD ; le seul renvoi « hors périmètre » explicite (bouton
logout dans l'UI) est assumé et documenté comme tel dans la spec (S171 ne construit pas
d'UI de gestion de compte).

**3. Cohérence des types** : `exiger_session` renvoie toujours `{"sub", "nom",
"avatarEmoji"}` (Task 3, consommé identiquement dans les tests Task 5) ; `chiffrer_cookie`/
`dechiffrer_cookie` génériques (dict → str → dict|None) utilisés à l'identique pour le
cookie de session ET le cookie PKCE en attente (Tasks 1 et 4) ; `auth_callback` nommé
explicitement pour `request.url_for("auth_callback")` (Task 4, cohérent entre login et
callback).

---

## Execution Handoff

Plan complet et sauvegardé dans `docs/superpowers/plans/2026-07-15-s171-login-keycloak-coeur.md`. Deux options d'exécution :

**1. Subagent-Driven (recommandé)** — je dispatche un subagent frais par tâche, revue entre chaque tâche, itération rapide.

**2. Inline Execution** — exécution des tâches dans cette session via executing-plans, exécution par lot avec points de contrôle.

Laquelle préfères-tu ?
