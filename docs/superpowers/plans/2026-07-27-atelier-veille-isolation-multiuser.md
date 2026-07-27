# Atelier Veille — isolation multi-utilisateur (proxy Cœur) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire en sorte que la session web du Cœur (dashboard, Keycloak) atterrisse sur les VRAIES sources/digests de la personne connectée côté `veille-info`, au lieu de retomber sur le tenant anonyme `public` — même motif déjà prouvé pour Studio (S187) et Atelier Images & Vidéo.

**Architecture:** Créer `core/routers/atelier_veille_proxy.py` (nouveau router du Cœur) qui sert le front `atelier-veille` sous `/atelier-veille-app/*` et proxy chaque appel vers le vrai conteneur `atelier-veille`, en injectant l'identité de LA SESSION Cœur (jamais celle envoyée par le navigateur). Comme `atelier-veille` lui-même relaie tel quel (`_entetes_aval`) les en-têtes qu'il reçoit vers `veille-info`, le proxy doit injecter les en-têtes calés sur la clé de `veille-info` (`VEILLE_INFO_KEY` + `X-User-Id` de session), pas une clé `ATELIER_VEILLE_KEY` qui n'existe pas. Un souci additionnel et propre à cette brique : son endpoint `/config` dérive l'URL publique de la carte geo depuis l'en-tête `Host` de la requête — une fois proxifié, ce `Host` devient celui du conteneur interne, pas celui vu par le navigateur ; il faut donc forwarder `X-Forwarded-Host`/`X-Forwarded-Proto` (motif déjà utilisé par `core/routers/dashboard.py` pour la même raison) et adapter `briques/atelier-veille/main.py::config` pour les préférer s'ils sont présents.

**Tech Stack:** Python 3.12, FastAPI, httpx (async), pytest + `fastapi.testclient.TestClient`.

## Global Constraints

- Sécurité : toute en-tête d'identité envoyée par le NAVIGATEUR (`X-User-Id`, `X-API-Key`, `Authorization`) doit être IGNORÉE par le proxy — seule l'identité de la session Cœur compte (même garde-fou que `studio_proxy.py`/`atelier_images_video_proxy.py`).
- Ne PAS toucher à `briques/veille-info/main.py::tenant_actuel` — déjà correct.
- Ne PAS toucher à `briques/atelier-veille/main.py::_entetes_aval` (pass-through déjà correct) sauf pour l'ajout du support `X-Forwarded-Host`/`X-Forwarded-Proto` sur `/config`.
- Rétrocompatibilité : l'accès DIRECT au conteneur `atelier-veille` (port 6130, LAN, sans passer par le Cœur) doit continuer à fonctionner pour `/config` (repli sur l'en-tête `Host` brut si `X-Forwarded-Host` absent).
- Suivre EXACTEMENT le motif de `core/routers/atelier_images_video_proxy.py` (fichier le plus proche : mêmes imports, mêmes noms de fonctions `_base`/`_entetes`/`_page`, même structure de routes).

---

## File Structure

- Create: `core/routers/atelier_veille_proxy.py` — nouveau proxy Cœur (motif studio/atelier-images-video).
- Create: `core/test_atelier_veille_proxy.py` — tests du proxy (motif `test_atelier_images_video_proxy.py`).
- Modify: `core/main.py` — import + montage du nouveau router.
- Modify: `core/routers/dashboard.py` — le lien `__ATELIER_VEILLE_UI_URL__` pointe vers le proxy au lieu de l'URL brute.
- Modify: `briques/atelier-veille/main.py` — `/config` préfère `X-Forwarded-Host`/`X-Forwarded-Proto` si présents.
- Modify: `briques/atelier-veille/front.html` — introduit `window.ATELIER_VEILLE_API_BASE` et préfixe tous les appels `fetch`/`src` absolus (`/config`, `/veille/*`, `/workplace.css`).
- Modify: `briques/atelier-veille/test_composition.py` — ajoute un test pour la nouvelle logique `X-Forwarded-Host` de `/config`.

---

### Task 1: Front `atelier-veille` — rendre les appels relatifs à un préfixe configurable

**Files:**
- Modify: `briques/atelier-veille/front.html`

**Interfaces:**
- Produces: variable JS globale `window.ATELIER_VEILLE_API_BASE` (optionnelle, vide par défaut = comportement autoporté inchangé) lue par le script inline de la page.

- [ ] **Step 1: Ajouter la constante `API_BASE` et préfixer tous les appels**

Dans `briques/atelier-veille/front.html`, juste après la balise `<script>` (ligne 88), ajouter :

```html
<script>
const API_BASE = window.ATELIER_VEILLE_API_BASE || '';

function ouvrirOnglet(nom) {
```

(c'est-à-dire : insérer `const API_BASE = window.ATELIER_VEILLE_API_BASE || '';` juste avant la définition existante de `ouvrirOnglet`, sans la dupliquer.)

Puis remplacer CHAQUE appel `fetch`/`src` à chemin absolu par sa version préfixée :

- Ligne 103 : `const r = await fetch('/config');` → `const r = await fetch(\`${API_BASE}/config\`);`
- Ligne 121 : `const r = await fetch('/veille/sources');` → `const r = await fetch(\`${API_BASE}/veille/sources\`);`
- Ligne 142 : `const r = await fetch('/veille/sources', {` → `const r = await fetch(\`${API_BASE}/veille/sources\`, {`
- Ligne 160 : `` const r = await fetch(`/veille/sources/${id}`, {method: 'DELETE'}); `` → `` const r = await fetch(`${API_BASE}/veille/sources/${id}`, {method: 'DELETE'}); ``
- Ligne 173 : `const r = await fetch('/veille/digests');` → `const r = await fetch(\`${API_BASE}/veille/digests\`);`
- Ligne 198 : `const r = await fetch('/veille/digest/executer', {method: 'POST'});` → `const r = await fetch(\`${API_BASE}/veille/digest/executer\`, {method: 'POST'});`
- Ligne 214 : `const r = await fetch('/veille/digests');` → `const r = await fetch(\`${API_BASE}/veille/digests\`);`
- Ligne 243 : `const r = await fetch('/veille/audio-global/generer', {` → `const r = await fetch(\`${API_BASE}/veille/audio-global/generer\`, {`
- Ligne 250 : `` <audio controls src="/veille/audio-global/${audio.jeton}.mp3" style="width:100%"></audio> `` → `` <audio controls src="${API_BASE}/veille/audio-global/${audio.jeton}.mp3" style="width:100%"></audio> ``
- Ligne 273 : `` const r = await fetch(`/veille/audio-global/${audioId}/envoyer`, { `` → `` const r = await fetch(`${API_BASE}/veille/audio-global/${audioId}/envoyer`, { ``
- Ligne 292 : `const r = await fetch('/veille/audio-global');` → `const r = await fetch(\`${API_BASE}/veille/audio-global\`);`
- Ligne 297 : `` <audio controls src="/veille/audio-global/${a.jeton}.mp3" style="display:block;margin-top:4px;width:100%"></audio> `` → `` <audio controls src="${API_BASE}/veille/audio-global/${a.jeton}.mp3" style="display:block;margin-top:4px;width:100%"></audio> ``

Ne PAS toucher à `<link rel="stylesheet" href="/workplace.css">` (ligne 7) ni au `<iframe id="geo-iframe">` (son `src` est déjà posé dynamiquement via `chargerConfig()` avec l'URL ABSOLUE renvoyée par `/config`, pas de préfixe nécessaire) — le CSS sera géré par réécriture texte côté proxy (Task 3).

- [ ] **Step 2: Vérifier visuellement qu'aucun appel absolu `/config` ou `/veille/` ne subsiste**

Run: `grep -n "fetch('/veille\|fetch('/config\|src=\"/veille" briques/atelier-veille/front.html`
Expected: aucune sortie (0 match) — tous les appels passent maintenant par `${API_BASE}`.

- [ ] **Step 3: Commit**

```bash
git add briques/atelier-veille/front.html
git commit -m "feat(atelier-veille): rend le front proxifiable via API_BASE configurable"
```

---

### Task 2: `veille-info` derrière proxy — support `/config` de `X-Forwarded-Host`/`X-Forwarded-Proto`

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Test: `briques/atelier-veille/test_composition.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `/config` accepte deux en-têtes optionnels `X-Forwarded-Host`, `X-Forwarded-Proto` ; s'ils sont présents, ils priment sur `request.headers.get("host")`/`request.url.scheme`.

- [ ] **Step 1: Lire le test existant de `/config` pour connaître le motif d'assertion**

Run: `grep -n "def test_config" -A 15 briques/atelier-veille/test_composition.py`

(Sert de référence pour écrire le nouveau test au même format — pas de modification à ce stade.)

- [ ] **Step 2: Écrire le test qui échoue**

Ajouter dans `briques/atelier-veille/test_composition.py` (à la suite des tests existants de `/config`) :

```python
def test_config_prefere_x_forwarded_host():
    """Derrière le proxy du Cœur, request.headers['host'] vaut l'hôte du conteneur
    atelier-veille lui-même (celui que httpx a appelé) — pas l'hôte vu par le navigateur.
    X-Forwarded-Host/X-Forwarded-Proto (posés par le proxy, motif dashboard.py) doivent
    primer pour que l'URL de la carte reste juste."""
    r = client.get("/config", headers={
        "Host": "atelier-veille:6130",
        "X-Forwarded-Host": "workplaceagenda.duckdns.org",
        "X-Forwarded-Proto": "https",
    })
    assert r.status_code == 200
    assert r.json()["geo_url"].startswith("https://workplaceagenda.duckdns.org:")


def test_config_repli_sur_host_sans_forwarded():
    """Accès direct (LAN, sans passer par le Cœur) : comportement historique inchangé,
    aucun en-tête X-Forwarded-* — on dérive toujours de Host."""
    r = client.get("/config", headers={"Host": "192.168.1.89:6130"})
    assert r.status_code == 200
    assert "192.168.1.89" in r.json()["geo_url"]
```

- [ ] **Step 3: Run pour vérifier l'échec**

Run: `cd briques/atelier-veille && python -m pytest test_composition.py -k "forwarded or repli_sur_host" -v`
Expected: `test_config_prefere_x_forwarded_host` FAIL (l'URL contient `atelier-veille` ou l'hôte de test par défaut, pas `workplaceagenda.duckdns.org`). `test_config_repli_sur_host_sans_forwarded` peut déjà passer (comportement inchangé) — normal.

- [ ] **Step 4: Implémenter dans `briques/atelier-veille/main.py`**

Remplacer la fonction `config` existante (repérée par `@app.get("/config", tags=["système"])`) :

```python
@app.get("/config", tags=["système"])
def config(request: Request, x_forwarded_host: Optional[str] = Header(None),
          x_forwarded_proto: Optional[str] = Header(None)):
    """URL publique (navigateur) de la carte geo — injectée dans l'onglet Carte du front.

    Dérivée par défaut du scheme + hôte de LA REQUÊTE COURANTE (celle que le navigateur
    vient d'utiliser pour joindre l'atelier), pour rester juste en LAN comme sur le mesh
    sans repointer une IP figée. `GEO_PUBLIC_URL` reste une surcharge possible.

    Derrière le proxy du Cœur (`core/routers/atelier_veille_proxy.py`), la requête HTTP
    reçue ICI vient du Cœur lui-même (httpx serveur→serveur) : son en-tête `Host` vaut
    l'hôte INTERNE du conteneur atelier-veille, jamais celui vu par le navigateur. Le
    proxy forwarde donc `X-Forwarded-Host`/`X-Forwarded-Proto` (motif déjà utilisé par
    `core/routers/dashboard.py::u()` pour la même raison) — on les préfère s'ils sont
    présents, sinon on retombe sur `Host` brut (accès direct, LAN, inchangé)."""
    if GEO_PUBLIC_URL:
        return {"geo_url": GEO_PUBLIC_URL}
    hote_brut = x_forwarded_host or request.headers.get("host", "localhost")
    scheme = x_forwarded_proto or request.url.scheme
    hote = _hote_sans_port(hote_brut)
    if MESH_HOST and hote == MESH_HOST:
        return {"geo_url": f"https://{hote}:{GEO_PORT + MESH_PORT_OFFSET}/"}
    return {"geo_url": f"{scheme}://{hote}:{GEO_PORT}/"}
```

`hote`/`scheme` incorporent déjà `x_forwarded_host`/`x_forwarded_proto` via `hote_brut`/`scheme` ci-dessus (repli sur `Host`/`request.url.scheme` seulement si les en-têtes forwarded sont absents) — un seul `return` couvre donc les deux cas (proxifié et accès direct), pas de branche séparée nécessaire.

- [ ] **Step 5: Run pour vérifier que les tests passent**

Run: `cd briques/atelier-veille && python -m pytest test_composition.py -k "forwarded or repli_sur_host" -v`
Expected: 2 passed.

- [ ] **Step 6: Run toute la suite de la brique pour vérifier l'absence de régression**

Run: `cd briques/atelier-veille && python -m pytest -v`
Expected: tous les tests passent (aucune régression sur les tests `/config` existants).

- [ ] **Step 7: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/test_composition.py
git commit -m "fix(atelier-veille): /config préfère X-Forwarded-Host/Proto derrière un proxy"
```

---

### Task 3: Proxy Cœur `atelier_veille_proxy.py`

**Files:**
- Create: `core/routers/atelier_veille_proxy.py`
- Test: `core/test_atelier_veille_proxy.py`

**Interfaces:**
- Consumes: `outils_communs._entetes_brique("veille-info")` (existant, `core/outils_communs.py`) → `dict` avec `X-Compte-Id`, `X-API-Key` (si `VEILLE_INFO_KEY` posée), `X-User-Id` (si `veille-info` est dans `BRIQUES_PAR_PERSONNE`, déjà le cas). `orchestrateur._brique_base(registre, "atelier-veille")` (existant) → `str` URL de base.
- Produces: routes montées sous `/atelier-veille-app/*` (`/`, `/atelier`, et un proxy générique `/atelier-veille-app/{chemin:path}` pour GET/POST/DELETE/PATCH/PUT).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `core/test_atelier_veille_proxy.py` :

```python
"""Proxy atelier-veille du Cœur : vue native /atelier-veille-app/*, isolée PAR PERSONNE.
Motif copié de core/test_atelier_images_video_proxy.py. Sans réseau : httpx.AsyncClient est
remplacé par un faux client qui enregistre les appels (méthode, url, en-têtes). Vérifie que
l'identité forwardée à atelier-veille (donc, via son pass-through, à veille-info) vient de
LA SESSION (contexte de tenant) et de la clé VEILLE_INFO_KEY — jamais de ce que le
navigateur a lui-même posé sur sa requête au Cœur."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ["VEILLE_INFO_KEY"] = "cle-coeur-veille-info"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import atelier_veille_proxy  # noqa: E402

client = TestClient(main.app)

APPELS = []


class _Resp:
    def __init__(self, texte="", status=200, content_type="application/json"):
        self._texte = texte
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = texte.encode() if texte else b"{}"

    @property
    def text(self):
        return self._texte


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, content=None):
        APPELS.append((method, url, headers))
        return _Resp()

    async def get(self, url, headers=None):
        APPELS.append(("GET", url, headers))
        if url.endswith("/") or url.endswith("/atelier"):
            return _Resp(texte="<html><head></head><body></body></html>")
        return _Resp()


def _setup(monkeypatch):
    APPELS.clear()
    monkeypatch.setattr(atelier_veille_proxy, "_base", lambda: "http://atelier-veille")
    monkeypatch.setattr(atelier_veille_proxy, "httpx",
                        type("_H", (), {"AsyncClient": _FakeClient}))


def test_racine_injecte_le_prefixe(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/atelier-veille-app/", headers={"X-User-Id": "toussaint"})
    assert r.status_code == 200
    assert "window.ATELIER_VEILLE_API_BASE='/atelier-veille-app';" in r.text


def test_identite_de_session_forwardee_pas_celle_du_navigateur(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/atelier-veille-app/veille/sources", headers={
        "X-User-Id": "toussaint", "X-API-Key": "cle-volee-par-le-navigateur",
    })
    assert r.status_code == 200
    methode, url, entetes = APPELS[-1]
    assert url == "http://atelier-veille/veille/sources"
    assert entetes["X-User-Id"] == "toussaint"
    assert entetes["X-API-Key"] == "cle-coeur-veille-info"


def test_deux_personnes_appels_distincts(monkeypatch):
    _setup(monkeypatch)
    client.get("/atelier-veille-app/veille/digests", headers={"X-User-Id": "claire"})
    client.get("/atelier-veille-app/veille/digests", headers={"X-User-Id": "marina"})
    identites = [e["X-User-Id"] for _, _, e in APPELS]
    assert identites == ["claire", "marina"]


def test_config_forwarde_host_et_proto(monkeypatch):
    _setup(monkeypatch)
    client.get("/atelier-veille-app/config", headers={
        "X-User-Id": "toussaint", "Host": "workplaceagenda.duckdns.org",
    })
    methode, url, entetes = APPELS[-1]
    assert entetes["X-Forwarded-Host"] == "workplaceagenda.duckdns.org"
    assert "X-Forwarded-Proto" in entetes
```

- [ ] **Step 2: Run pour vérifier l'échec**

Run: `cd core && python -m pytest test_atelier_veille_proxy.py -v`
Expected: `ModuleNotFoundError: No module named 'routers.atelier_veille_proxy'` (le fichier n'existe pas encore).

- [ ] **Step 3: Implémenter `core/routers/atelier_veille_proxy.py`**

```python
"""Proxy « atelier-veille » du Cœur : vue native de la tuile Atelier Veille, isolée PAR
PERSONNE.

Même motif que core/routers/studio_proxy.py et atelier_images_video_proxy.py, avec une
nuance : le frontend autoporté (`briques/atelier-veille/front.html`) proxifie lui-même vers
`veille-info` (pass-through pur, cf. `briques/atelier-veille/main.py::_entetes_aval`) — donc
l'identité qu'on injecte ICI doit être celle attendue par `veille-info` (X-User-Id +
VEILLE_INFO_KEY), PAS une clé « ATELIER_VEILLE_KEY » qui n'existe pas (atelier-veille est un
service ouvert, sans authentification propre). Sans ce détour, la session web retombait sur
le tenant anonyme `public` côté veille-info (aucune en-tête d'identité à relayer), trou
identique à S183/S190 jamais porté sur cette brique.

`/config` (URL publique de la carte geo) dérive normalement l'hôte de la requête COURANTE :
une fois proxifiée, cette requête vient du Cœur lui-même (httpx serveur→serveur), donc son
`Host` vaudrait l'hôte interne du conteneur — on forwarde `X-Forwarded-Host`/
`X-Forwarded-Proto` (motif déjà utilisé par `core/routers/dashboard.py::u()`) pour que
`briques/atelier-veille/main.py::config` reconstruise la bonne URL.

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session` +
`lire_contexte_tenant` posés sur ce router dans `main.py`) compte.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/atelier-veille-app"
_TIMEOUT = 60.0


def _base() -> str:
    return orchestrateur._brique_base(registre, "atelier-veille")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("veille-info"))
    entetes["X-Forwarded-Host"] = request.headers.get("host", "")
    entetes["X-Forwarded-Proto"] = request.headers.get("x-forwarded-proto") or request.url.scheme
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


async def _page(chemin_brique: str, request: Request) -> HTMLResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}{chemin_brique}", headers=_entetes(request))
    page = (r.text
            .replace('href="/workplace.css"', f'href="{_PREFIXE}/workplace.css"')
            .replace("</head>", f"<script>window.ATELIER_VEILLE_API_BASE='{_PREFIXE}';</script></head>"))
    return HTMLResponse(page, status_code=r.status_code)


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def atelier_veille_app_racine(request: Request):
    return await _page("/", request)


@router.get(_PREFIXE + "/atelier", response_class=HTMLResponse)
async def atelier_veille_app_atelier(request: Request):
    return await _page("/atelier", request)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def atelier_veille_app_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes (API `/veille/*`, `/config`, `/workplace.css`)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))
```

- [ ] **Step 4: Run pour vérifier que les tests passent**

Run: `cd core && python -m pytest test_atelier_veille_proxy.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/routers/atelier_veille_proxy.py core/test_atelier_veille_proxy.py
git commit -m "feat(core): proxy atelier-veille isolé par personne (motif S187/atelier-images-video)"
```

---

### Task 4: Montage du router + lien dashboard

**Files:**
- Modify: `core/main.py`
- Modify: `core/routers/dashboard.py`
- Test: `core/test_dashboard.py`

**Interfaces:**
- Consumes: `atelier_veille_proxy.router` (Task 3).
- Produces: `GET /dashboard` rend `__ATELIER_VEILLE_UI_URL__` = `/atelier-veille-app/atelier` au lieu de l'URL brute `http://<hôte>:6130/atelier`.

- [ ] **Step 1: Écrire le test qui échoue**

`core/test_dashboard.py` n'a PAS de fixture de session : c'est un `client = TestClient(main.app)` module-level, utilisé directement (`client.get("/dashboard")`), motif identique à tous les tests existants de ce fichier (ex. `test_dashboard_repond`, `test_onglet_cercle_present`). Ajouter à la suite :

```python
def test_dashboard_lien_atelier_veille_proxifie():
    html = client.get("/dashboard").text
    assert "/atelier-veille-app/atelier" in html
    assert ":6130/atelier" not in html
```

- [ ] **Step 2: Run pour vérifier l'échec**

Run: `cd core && python -m pytest test_dashboard.py -k atelier_veille -v`
Expected: FAIL (le texte contient encore `:6130/atelier`, pas `/atelier-veille-app/atelier`).

- [ ] **Step 3: Modifier `core/main.py`**

Repérer la ligne d'import (ligne 24-25) :

```python
from routers import (agenda, assistant, atelier_images_video_proxy, dashboard,
mail_proxy, media_proxy, profil, studio_proxy, systeme, usine)
```

Remplacer par :

```python
from routers import (agenda, assistant, atelier_images_video_proxy, atelier_veille_proxy,
dashboard, mail_proxy, media_proxy, profil, studio_proxy, systeme, usine)
```

Puis, juste après le bloc de montage de `atelier_images_video_proxy.router` (repéré par le commentaire `# Atelier Images & Vidéo :`), ajouter :

```python
# Atelier Veille : même motif que Studio/Atelier Images & Vidéo — session obligatoire +
# contexte de tenant, pour que les sources RSS/digests/audio-global soient isolés par
# personne, cf. core/routers/atelier_veille_proxy.py.
app.include_router(atelier_veille_proxy.router,
                   dependencies=[Depends(exiger_session)] + _tenant)
```

- [ ] **Step 4: Modifier `core/routers/dashboard.py`**

Repérer la ligne (~3521) :

```python
.replace("__ATELIER_VEILLE_UI_URL__", u("ATELIER_VEILLE"))
```

Remplacer par :

```python
.replace("__ATELIER_VEILLE_UI_URL__", "/atelier-veille-app/atelier")
```

- [ ] **Step 5: Run pour vérifier que le test passe**

Run: `cd core && python -m pytest test_dashboard.py -k atelier_veille -v`
Expected: 1 passed.

- [ ] **Step 6: Run toute la suite core pour vérifier l'absence de régression**

Run: `cd core && python -m pytest -x -q`
Expected: tous les tests passent.

- [ ] **Step 7: Commit**

```bash
git add core/main.py core/routers/dashboard.py core/test_dashboard.py
git commit -m "fix(core): dashboard pointe Atelier Veille vers le proxy isolé par personne"
```

---

## Déploiement (hors plan, à faire manuellement sur le HP après merge)

Ce plan ne couvre QUE le code (régime « coder+tester+pousser ici, prouver LIVE sur le HP »). Une fois les 4 tâches commitées et poussées, sur le HP (`debian@192.168.1.89`) :

```bash
cd ~/workplace && git pull --ff-only
( cd core && docker compose up -d --build )
( cd briques/atelier-veille && docker compose up -d --build )
```

Puis vérifier en se connectant sur `https://workplaceagenda.duckdns.org/dashboard` → Atelier Veille → Sources RSS, que les sources affichées sont bien celles du tenant `perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e` (après la migration du plan `2026-07-27-veille-info-migration-consolidation-toussaint.md`), pas celles de `public`.
