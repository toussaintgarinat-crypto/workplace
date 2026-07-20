# S181 — Accès distant du cercle privé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le login Keycloak du Cœur joignable depuis n'importe où via le domaine mesh, et permettre d'inviter un proche au mesh par un QR code généré depuis l'admin du Cœur.

**Architecture:** Partie A sépare l'URL Keycloak *navigateur* (domaine, via Caddy) de l'URL *serveur* (interne) dans le core, et fixe `KC_HOSTNAME` sur le domaine (issuer unique). Partie B ajoute un petit module client NetBird qui crée des setup keys usage-unique via l'API, exposé par un endpoint gardé par session et une section « Cercle » du dashboard qui affiche un QR SVG.

**Tech Stack:** Python/FastAPI (core), httpx (déjà dép), segno (nouveau, QR pur-Python), Caddy (DuckDNS/Let's Encrypt), Keycloak 26 (realm `forge`), NetBird Cloud API.

## Global Constraints

- **Domaine mesh** : `workplaceagenda.duckdns.org` (A record = IP mesh `100.124.248.226`, résolu uniquement par les pairs NetBird).
- **Keycloak port navigateur** : `:18080` (convention +10000, Caddy → `localhost:8080`).
- **Realm / client** : `forge` / `assistant-app` (Cœur).
- **Secrets JAMAIS commités** : `NETBIRD_API_TOKEN` (PAT `nbp_...`) et toute valeur d'env vont dans `core/docker-compose.override.yml` (HP-local, gitignoré) — comme `DUCKDNS_TOKEN`.
- **NetBird Cloud** : API `https://api.netbird.io`, groupe `auto_groups` par défaut = "All" (`d7p6raifadhs73fvql9g`).
- **Régime de preuve** : coder + tester + committer ICI ; les preuves LIVE (déploiement HP) sont groupées (tâches marquées **[LIVE]**).
- **Rollback Partie A** : ne pas définir `KEYCLOAK_PUBLIC_URL` (fallback interne) + rétablir `KC_HOSTNAME` + retirer le bloc Caddy `:18080`.

---

## PARTIE A — Login Keycloak distant

### Task 1 : Core — séparer URL navigateur / URL serveur Keycloak

**Files:**
- Modify: `core/auth.py` (bloc config ~ligne 38 ; ajout d'une constante)
- Modify: `core/routers/auth.py:37` (URL de redirection `/auth`)
- Test: `core/test_auth_public_url.py` (créer)

**Interfaces:**
- Produces: `auth.KEYCLOAK_PUBLIC_URL: str` — URL Keycloak vue par le NAVIGATEUR (défaut = `KEYCLOAK_URL`).
- Inchangé : `auth.KEYCLOAK_URL` (serveur/JWKS), `auth._token_endpoint()` (interne).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `core/test_auth_public_url.py` :

```python
"""S181 — la redirection navigateur /auth utilise KEYCLOAK_PUBLIC_URL ;
l'échange de code serveur reste sur KEYCLOAK_URL interne."""
import os

os.environ["KEYCLOAK_PUBLIC_URL"] = "https://public.example:18080"
os.environ["KEYCLOAK_URL"] = "http://interne:8080"
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
import auth  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_redirect_login_utilise_public_url():
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert loc.startswith("https://public.example:18080/realms/forge/protocol/openid-connect/auth")


def test_token_endpoint_reste_interne():
    assert auth._token_endpoint() == "http://interne:8080/realms/forge/protocol/openid-connect/token"
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `cd core && python -m pytest test_auth_public_url.py -v`
Expected: FAIL — `test_redirect_login_utilise_public_url` échoue (la Location commence par `http://interne:8080…` car `routers/auth.py` utilise encore `KEYCLOAK_URL`).

- [ ] **Step 3: Ajouter la constante dans `core/auth.py`**

Juste après la ligne `KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")` (~ligne 38), ajouter :

```python
# S181 — URL Keycloak vue par le NAVIGATEUR (accès distant via le domaine mesh, Caddy).
# Défaut = KEYCLOAK_URL → comportement inchangé si non défini (rollback = ne pas la définir).
# L'échange de code S2S (_token_endpoint) et la validation JWKS (KC) restent sur KEYCLOAK_URL
# interne : verify_token ne valide pas `iss`, les clés JWKS sont indépendantes du hostname.
KEYCLOAK_PUBLIC_URL = os.environ.get("KEYCLOAK_PUBLIC_URL", KEYCLOAK_URL)
```

- [ ] **Step 4: Utiliser l'URL publique dans `core/routers/auth.py`**

À la ligne 37, remplacer `auth.KEYCLOAK_URL` par `auth.KEYCLOAK_PUBLIC_URL` :

```python
    url = (
        f"{auth.KEYCLOAK_PUBLIC_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth"
        f"?{urllib.parse.urlencode(params)}"
    )
```

- [ ] **Step 5: Lancer le test — il doit passer**

Run: `cd core && python -m pytest test_auth_public_url.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Non-régression auth existante**

Run: `cd core && python -m pytest test_auth_public_url.py test_dashboard.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add core/auth.py core/routers/auth.py core/test_auth_public_url.py
git commit -m "feat(s181): KEYCLOAK_PUBLIC_URL — redirection login navigateur sur le domaine mesh

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : Caddy + Keycloak — exposer Keycloak sur le domaine **[LIVE]**

Cette tâche s'exécute **sur le HP** (SSH `debian@192.168.1.89`, repo `~/workplace`). Pas de test unitaire : vérification par requêtes réelles. Éditer AUSSI le repo pour réconcilier repo↔HP.

**Files:**
- Modify (repo + HP) : `outils/mesh-https/Caddyfile.duckdns` (variante live) — ajouter le bloc `:18080`.
- Config Keycloak (HP) : env `KC_HOSTNAME`, `KC_PROXY_HEADERS`.
- Config core (HP) : `core/docker-compose.override.yml` — env `KEYCLOAK_PUBLIC_URL` (non commité).
- Client Keycloak `assistant-app` (realm forge) : redirectUri domaine.

- [ ] **Step 1: Réconcilier le Caddyfile live et ajouter le bloc Keycloak**

Sur le HP, repérer le Caddyfile réellement monté par le conteneur Caddy DuckDNS (celui qui porte déjà le domaine + l'agenda `18400`) :

Run: `ssh debian@192.168.1.89 'cd ~/workplace/outils/mesh-https && grep -rl "workplaceagenda.duckdns.org" Caddyfile*'`
Expected: le fichier live (probablement `Caddyfile.duckdns` ou `Caddyfile.briques`).

Dans le bloc de site du domaine, **ajouter** un serveur sur le port 18080 (même TLS `acme_dns duckdns`) :

```caddy
# S181 — Keycloak joignable via le domaine pour le login distant (mesh).
https://workplaceagenda.duckdns.org:18080 {
	tls {
		dns duckdns {env.DUCKDNS_TOKEN}
	}
	reverse_proxy localhost:8080
}
```

Répercuter la **même** édition dans le fichier du repo (worktree) pour réconcilier.

- [ ] **Step 2: Fixer le hostname Keycloak sur le domaine**

Localiser le compose Keycloak :
Run: `ssh debian@192.168.1.89 'cd ~/workplace && grep -rl "KC_HOSTNAME\|keycloak:" --include=docker-compose*.yml . | head'`

Ajouter/mettre à jour dans l'environnement du service `keycloak` :

```yaml
      KC_HOSTNAME: https://workplaceagenda.duckdns.org:18080
      KC_PROXY_HEADERS: xforwarded
      KC_HTTP_ENABLED: "true"
```

- [ ] **Step 3: Ajouter l'env `KEYCLOAK_PUBLIC_URL` au core (HP, non commité)**

Dans `core/docker-compose.override.yml` (service `core`) sur le HP :

```yaml
      KEYCLOAK_PUBLIC_URL: https://workplaceagenda.duckdns.org:18080
```

Conserver `KEYCLOAK_URL=http://192.168.1.89:8080` (interne). Sauvegarder un backup `.bak-s181`.

- [ ] **Step 4: Vérifier/ajouter le redirectUri du client `assistant-app`**

```bash
ssh debian@192.168.1.89
# obtenir un token admin kcadm dans le conteneur keycloak, puis :
#   /opt/keycloak/bin/kcadm.sh get clients -r forge -q clientId=assistant-app --fields id,redirectUris,webOrigins
# S'il manque, l'ajouter :
#   .../kcadm.sh update clients/<id> -r forge \
#     -s 'redirectUris=["http://192.168.1.89:5100/auth/callback","https://workplaceagenda.duckdns.org/auth/callback"]' \
#     -s 'webOrigins=["http://192.168.1.89:5100","https://workplaceagenda.duckdns.org"]'
```

Expected: le client porte le callback `https://workplaceagenda.duckdns.org/auth/callback`.

- [ ] **Step 5: Recharger Caddy + recréer keycloak + core**

```bash
ssh debian@192.168.1.89 'cd ~/workplace/outils/mesh-https && docker compose -f docker-compose.duckdns.yml up -d --build'
ssh debian@192.168.1.89 'cd ~/workplace && docker compose up -d keycloak && docker compose up -d core'
```

- [ ] **Step 6: Vérifier l'issuer public (depuis un pair mesh, ex. le Mac)**

Run: `curl -s https://workplaceagenda.duckdns.org:18080/realms/forge/.well-known/openid-configuration | python3 -c "import sys,json;d=json.load(sys.stdin);print('issuer=',d['issuer']);print('auth=',d['authorization_endpoint'])"`
Expected: `issuer= https://workplaceagenda.duckdns.org:18080/realms/forge` et `authorization_endpoint` sur le même hôte, **cert valide** (aucune erreur TLS).

- [ ] **Step 7: Login e2e distant**

Depuis le Mac (pair mesh), navigateur : ouvrir `https://workplaceagenda.duckdns.org/dashboard` → doit rediriger vers `…:18080/realms/forge/...auth` → saisir `Toussaint` / mot de passe → retour `/dashboard` 200, onglet Agenda peuplé.
Expected: login complet ; l'agenda affiche ses events (preuve que la validation JWKS passe malgré l'issuer = domaine).

- [ ] **Step 8: Commit (réconciliation repo du Caddyfile)**

```bash
git add outils/mesh-https/
git commit -m "chore(s181): expose Keycloak sur le domaine mesh (Caddy :18080) — réconcilie repo/HP

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## PARTIE B — Onboarding mesh par QR

### Task 3 : Module client NetBird — création de setup key

**Files:**
- Create: `core/netbird.py`
- Test: `core/test_netbird.py`

**Interfaces:**
- Produces:
  - `netbird.creer_setup_key(nom: str, *, client: httpx.AsyncClient | None = None) -> dict` → `{"key": str, "expires": str | None, "name": str}`.
  - `netbird.NetbirdError(RuntimeError)`.
  - `netbird.NETBIRD_API_URL: str` (défaut `https://api.netbird.io`).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `core/test_netbird.py` :

```python
"""S181 — creer_setup_key POST /api/setup-keys (client NetBird), avec transport mocké."""
import asyncio
import json

import httpx
import pytest

import netbird


def test_creer_setup_key_ok(monkeypatch):
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "nbp_test")
    monkeypatch.setattr(netbird, "NETBIRD_INVITE_GROUP_ID", "grp1")
    monkeypatch.setattr(netbird, "NETBIRD_SETUP_KEY_EXPIRES", 3600)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"key": "AAAA-BBBB-CCCC", "expires": "2026-07-19T00:00:00Z", "name": "test"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(netbird.creer_setup_key("test", client=client))
    asyncio.run(client.aclose())

    assert res["key"] == "AAAA-BBBB-CCCC"
    assert captured["url"] == "https://api.netbird.io/api/setup-keys"
    assert captured["auth"] == "Token nbp_test"
    assert captured["body"] == {
        "name": "test", "type": "one-off", "expires_in": 3600,
        "usage_limit": 1, "auto_groups": ["grp1"], "ephemeral": False,
    }


def test_creer_setup_key_sans_token(monkeypatch):
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "")
    with pytest.raises(netbird.NetbirdError):
        asyncio.run(netbird.creer_setup_key("x"))


def test_creer_setup_key_erreur_api(monkeypatch):
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "nbp_test")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="token invalid")))
    with pytest.raises(netbird.NetbirdError):
        asyncio.run(netbird.creer_setup_key("x", client=client))
    asyncio.run(client.aclose())
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `cd core && python -m pytest test_netbird.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'netbird'`.

- [ ] **Step 3: Écrire `core/netbird.py`**

```python
"""S181 — client minimal de l'API NetBird Cloud pour générer des setup keys usage-unique
(onboarding d'un proche au mesh). Le PAT (NETBIRD_API_TOKEN) vient de l'env gitignoré ;
jamais commité, jamais renvoyé au front."""
from __future__ import annotations

import os

import httpx

NETBIRD_API_URL = os.environ.get("NETBIRD_API_URL", "https://api.netbird.io").rstrip("/")
NETBIRD_API_TOKEN = os.environ.get("NETBIRD_API_TOKEN", "")
NETBIRD_INVITE_GROUP_ID = os.environ.get("NETBIRD_INVITE_GROUP_ID", "")
NETBIRD_SETUP_KEY_EXPIRES = int(os.environ.get("NETBIRD_SETUP_KEY_EXPIRES", "86400"))


class NetbirdError(RuntimeError):
    """API NetBird injoignable, non authentifiée, ou réponse d'erreur."""


async def creer_setup_key(nom: str, *, client: httpx.AsyncClient | None = None) -> dict:
    """Crée une setup key one-off (usage unique) via POST /api/setup-keys.

    Renvoie {"key", "expires", "name"}. Lève NetbirdError sur toute anomalie."""
    if not NETBIRD_API_TOKEN:
        raise NetbirdError("NETBIRD_API_TOKEN manquant (PAT NetBird non configuré)")

    payload = {
        "name": nom,
        "type": "one-off",
        "expires_in": NETBIRD_SETUP_KEY_EXPIRES,
        "usage_limit": 1,
        "auto_groups": [NETBIRD_INVITE_GROUP_ID] if NETBIRD_INVITE_GROUP_ID else [],
        "ephemeral": False,
    }
    headers = {"Authorization": f"Token {NETBIRD_API_TOKEN}"}

    own = client is None
    c = client or httpx.AsyncClient()
    try:
        try:
            r = await c.post(f"{NETBIRD_API_URL}/api/setup-keys", json=payload, headers=headers, timeout=15)
        except httpx.HTTPError as e:
            raise NetbirdError(f"API NetBird injoignable : {e}") from e
        if r.status_code >= 400:
            raise NetbirdError(f"NetBird {r.status_code} : {r.text[:200]}")
        data = r.json()
    finally:
        if own:
            await c.aclose()

    return {"key": data["key"], "expires": data.get("expires"), "name": data.get("name", nom)}
```

- [ ] **Step 4: Lancer le test — il doit passer**

Run: `cd core && python -m pytest test_netbird.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/netbird.py core/test_netbird.py
git commit -m "feat(s181): client NetBird — creer_setup_key (setup key one-off via API)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4 : Endpoint admin `/admin/inviter-proche` + QR SVG

**Files:**
- Modify: `core/requirements.txt` (ajouter `segno`)
- Create: `core/routers/invite.py`
- Modify: `core/main.py:24-25` (import) et `core/main.py:~89` (include_router gardé)
- Test: `core/test_invite.py`

**Interfaces:**
- Consumes: `netbird.creer_setup_key`, `auth.exiger_session`.
- Produces: route `POST /admin/inviter-proche` (corps `{"nom": str}`) → `{"key", "expires", "qr_svg", "management_url"}` (200) ou `{"erreur": str}` (502).

- [ ] **Step 1: Ajouter la dépendance segno et l'installer**

Ajouter à `core/requirements.txt` :

```
segno==1.6.1
```

Run: `pip install segno==1.6.1`
Expected: installé (pur Python, aucune dép native).

- [ ] **Step 2: Écrire le test qui échoue**

Créer `core/test_invite.py` :

```python
"""S181 — endpoint /admin/inviter-proche : appelle NetBird (mocké) et renvoie un QR SVG."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
import netbird  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_inviter_proche_renvoie_qr(monkeypatch):
    async def faux(nom, **kw):
        return {"key": "KKKK-LLLL", "expires": "2026-07-19T00:00:00Z", "name": nom}
    monkeypatch.setattr(netbird, "creer_setup_key", faux)

    r = client.post("/admin/inviter-proche", json={"nom": "marina"})
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == "KKKK-LLLL"
    assert "<svg" in data["qr_svg"]


def test_inviter_proche_erreur_netbird(monkeypatch):
    async def faux(nom, **kw):
        raise netbird.NetbirdError("token invalid")
    monkeypatch.setattr(netbird, "creer_setup_key", faux)

    r = client.post("/admin/inviter-proche", json={"nom": "x"})
    assert r.status_code == 502
    assert "erreur" in r.json()
```

- [ ] **Step 3: Lancer le test — il doit échouer**

Run: `cd core && python -m pytest test_invite.py -v`
Expected: FAIL — 404 sur `/admin/inviter-proche` (route absente).

- [ ] **Step 4: Écrire `core/routers/invite.py`**

```python
"""S181 — invitation d'un proche au mesh : génère une setup key NetBird usage-unique
et l'encode en QR (SVG). Gardé par session (voir wiring dans main.py)."""
from __future__ import annotations

import io

import segno
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

import netbird

router = APIRouter(tags=["cercle"])


@router.post("/admin/inviter-proche")
async def inviter_proche(nom: str = Body("proche", embed=True)):
    try:
        infos = await netbird.creer_setup_key(nom)
    except netbird.NetbirdError as e:
        return JSONResponse({"erreur": str(e)}, status_code=502)

    qr = segno.make(infos["key"], error="m")
    buf = io.StringIO()
    qr.save(buf, kind="svg", scale=6, border=2, xmldecl=False)

    # URL de management pour l'app mobile du proche (api.netbird.io → app.netbird.io).
    management_url = netbird.NETBIRD_API_URL.replace("://api.", "://app.")
    return {
        "key": infos["key"],
        "expires": infos["expires"],
        "qr_svg": buf.getvalue(),
        "management_url": management_url,
    }
```

- [ ] **Step 5: Câbler le routeur dans `core/main.py` (gardé par session)**

À la ligne 24, ajouter `invite` à l'import des routers :

```python
from routers import agenda, assistant, dashboard, invite, profil, systeme, usine
```

Après la ligne `app.include_router(profil.router, dependencies=_tenant)` (~ligne 89), ajouter :

```python
    app.include_router(invite.router, dependencies=[Depends(exiger_session)])
```

- [ ] **Step 6: Lancer le test — il doit passer**

Run: `cd core && python -m pytest test_invite.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Non-régression**

Run: `cd core && python -m pytest test_invite.py test_netbird.py test_dashboard.py test_auth_public_url.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add core/requirements.txt core/routers/invite.py core/main.py core/test_invite.py
git commit -m "feat(s181): endpoint /admin/inviter-proche — setup key NetBird + QR SVG (segno)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5 : Dashboard — onglet « Cercle » avec bouton d'invitation + QR

**Files:**
- Modify: `core/routers/dashboard.py` (nav `data-vue`, panneau, JS)
- Test: `core/test_dashboard.py` (ajouter une assertion)

**Interfaces:**
- Consumes: `POST /admin/inviter-proche`.

- [ ] **Step 1: Ajouter l'assertion de test**

Dans `core/test_dashboard.py`, ajouter :

```python
def test_onglet_cercle_present():
    """S181 — l'onglet Cercle (inviter un proche au mesh) existe dans le dashboard."""
    html = client.get("/dashboard").text
    assert 'data-vue="cercle"' in html
    assert "/admin/inviter-proche" in html
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `cd core && python -m pytest test_dashboard.py::test_onglet_cercle_present -v`
Expected: FAIL (`data-vue="cercle"` absent).

- [ ] **Step 3: Ajouter le bouton d'onglet**

Dans `core/routers/dashboard.py`, repérer la ligne du bouton d'onglet `profil` (~ligne 425) :

Run: `grep -n 'data-vue="profil"' core/routers/dashboard.py`

Juste **après** ce bouton, ajouter :

```html
<button class="tab" data-vue="cercle" onclick="switchVue('cercle')" title="Inviter un proche au mesh privé">🔑 Cercle</button>
```

- [ ] **Step 4: Ajouter le panneau de la vue**

Repérer le panneau de la vue `profil` pour coller le même motif de conteneur :

Run: `grep -n 'data-vue-panel\|id="vue-profil"\|vue="profil"' core/routers/dashboard.py | head`

En suivant EXACTEMENT le motif de conteneur trouvé (même attribut/classe que les autres panneaux), ajouter un panneau `cercle` contenant :

```html
<div class="carte">
  <h2>🔑 Inviter un proche au cercle privé</h2>
  <p>Génère un QR à usage unique pour rattacher l'appareil d'un proche au mesh privé.
     Il installe l'app NetBird, scanne/saisit la clé, puis ouvre le tableau de bord.</p>
  <label>Nom de l'invité <input id="cercle-nom" placeholder="Marina"></label>
  <button onclick="inviterProche()">Générer l'invitation</button>
  <div id="cercle-resultat" style="margin-top:16px"></div>
</div>
```

- [ ] **Step 5: Ajouter la fonction JS**

Dans le bloc `<script>` du dashboard (repérer une fonction existante comme `switchVue` pour placer la nouvelle à côté), ajouter :

```javascript
async function inviterProche() {
  const nom = (document.getElementById('cercle-nom').value || 'proche').trim();
  const cible = document.getElementById('cercle-resultat');
  cible.textContent = 'Génération…';
  try {
    const r = await fetch('/admin/inviter-proche', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nom})
    });
    const d = await r.json();
    if (!r.ok) { cible.textContent = 'Erreur : ' + (d.erreur || r.status); return; }
    cible.innerHTML =
      '<div style="max-width:240px">' + d.qr_svg + '</div>' +
      '<p><strong>Clé :</strong> <code>' + d.key + '</code></p>' +
      '<p>Management : <code>' + d.management_url + '</code>' +
      (d.expires ? ' — expire le ' + d.expires : '') + '</p>' +
      '<ol><li>Installer l\'app <strong>NetBird</strong></li>' +
      '<li>Rejoindre avec la clé ci-dessus</li>' +
      '<li>Ouvrir le tableau de bord une fois connecté au mesh</li></ol>';
  } catch (e) {
    cible.textContent = 'Erreur réseau : ' + e;
  }
}
```

- [ ] **Step 6: Lancer les tests — ils doivent passer**

Run: `cd core && python -m pytest test_dashboard.py -v`
Expected: PASS (dont `test_onglet_cercle_present`).

- [ ] **Step 7: Commit**

```bash
git add core/routers/dashboard.py core/test_dashboard.py
git commit -m "feat(s181): onglet Cercle — inviter un proche au mesh (QR NetBird)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6 : Déploiement + preuves Partie B **[LIVE]**

Sur le HP. Nécessite le PAT NetBird (fourni, à ranger gitignoré).

- [ ] **Step 1: Configurer les env NetBird (HP, non commité)**

Dans `core/docker-compose.override.yml` (service `core`) sur le HP :

```yaml
      NETBIRD_API_URL: https://api.netbird.io
      NETBIRD_API_TOKEN: nbp_...        # PAT owner (JAMAIS commité)
      NETBIRD_INVITE_GROUP_ID: d7p6raifadhs73fvql9g
      NETBIRD_SETUP_KEY_EXPIRES: "86400"
```

- [ ] **Step 2: Rebuild + recréer core (segno = nouvelle dép)**

```bash
ssh debian@192.168.1.89 'cd ~/workplace && docker compose build core && docker compose up -d core'
```

- [ ] **Step 3: SPIKE ingestion setup key (app NetBird)**

Vérifier sur l'app mobile NetBird ce qu'elle sait ingérer (scan direct de la clé / saisie manuelle / lien profond). Ajuster ce que le QR encode si besoin (aujourd'hui : la chaîne clé). Documenter le constat.

- [ ] **Step 4: Preuve génération**

Depuis le Mac (pair mesh), loggé sur `https://workplaceagenda.duckdns.org/dashboard` → onglet **Cercle** → « Générer l'invitation » → un QR + une clé s'affichent.
Vérifier côté NetBird qu'une **nouvelle** clé one-off `used=0` est apparue :
Run: `curl -s https://api.netbird.io/api/setup-keys -H "Authorization: Token <PAT>" | python3 -c "import sys,json;[print(k['name'],k['type'],k['used_times']) for k in json.load(sys.stdin)]"`
Expected: la clé fraîchement créée figure, `type=one-off`, `used_times=0`.

- [ ] **Step 5: Preuve enrôlement (appareil test)**

Enrôler un appareil test avec la clé → `netbird status` sur le HP montre `Peers count` +1 ; la clé passe `used_times=1`.

---

## Self-Review

**Spec coverage :**
- Partie A séparation PUBLIC/interne → Task 1 ✅ ; Caddy :18080 + KC_HOSTNAME + client redirectUri → Task 2 ✅ ; dé-risquage issuer (JWKS interne) implémenté par le fait que KC/token_endpoint restent sur `KEYCLOAK_URL` → Task 1 ✅.
- Partie B client NetBird génération à la demande → Task 3 ✅ ; endpoint gardé session → Task 4 ✅ ; section admin + QR → Task 5 ✅ ; PAT gitignoré + preuves + spikes → Task 6 ✅.
- Réconciliation repo↔HP `outils/mesh-https` → Task 2 Step 1 & 8 ✅.
- Hors périmètre (client tenant, lier_compte_perso S182) → non planifié, correct.

**Placeholder scan :** les seuls éléments « à déterminer » sont les 2 SPIKE explicitement marqués LIVE (comportement de l'app mobile / champs API), volontairement différés au câblage réel — pas des trous de code. Tout le code core est fourni intégralement.

**Type consistency :** `creer_setup_key(nom, *, client=None) -> {"key","expires","name"}` cohérent entre Task 3 (def), Task 4 (test mocké `faux(nom, **kw)`) et l'endpoint. `NetbirdError` cohérent. `KEYCLOAK_PUBLIC_URL` cohérent Task 1↔2. Route `/admin/inviter-proche` cohérente Task 4↔5.
