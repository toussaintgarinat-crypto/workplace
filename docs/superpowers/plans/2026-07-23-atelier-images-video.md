# Atelier Images & Vidéo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer `briques/atelier-images-video/` (port 6160), un front unique qui compose
génération libre image/vidéo, synergies Studio (portrait/couverture/teaser/animer) et une
galerie (brique mémoire), proxié en toute sécurité par un nouveau routeur du Cœur.

**Architecture:** Brique FastAPI proxy sans état (mirror de `briques/atelier-veille`), qui
relaie vers `images` (5950)/`video` (5970) sans auth (stateless), et vers `studio` (6060)/
`memoire` (5600) avec un secret de service + `X-User-Id` relayé. Un nouveau routeur Cœur
(`core/routers/atelier_images_video_proxy.py`, mirror de `studio_proxy.py`) sert le front
sous `/atelier-images-video-app/*` et est la SEULE source d'identité de confiance (cookie
de session), pour ne pas rouvrir le trou corrigé en S183.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest (`TestClient` + `monkeypatch`), HTML/JS
vanilla (pas de framework front), Docker/docker-compose.

## Global Constraints

- Design de référence : `docs/superpowers/specs/2026-07-23-atelier-images-video-design.md`
  (validé par l'utilisateur le 2026-07-23) — toute divergence de ce plan par rapport au
  design doit rester une PRÉCISION d'implémentation, jamais un changement de périmètre.
- Port de la nouvelle brique : **6160** (libre, vérifié — aucune autre brique ne l'utilise).
- Aucune capacité LLM : `capacites: []` dans le manifest — surface humaine, pas un outil
  de l'assistant (motif `atelier-veille`).
- Génération libre (images/video) : proxy SANS auth, ces briques ne stockent rien par
  utilisateur (motif déjà en place : `briques/studio/studio.py::_appeler_images/_video`
  n'envoie aucun en-tête).
- Synergies (Studio) et galerie (mémoire) : proxy AVEC un secret de service
  (`STUDIO_KEY`, `MEMOIRE_KEY`, déjà existants — réutilisés, pas recréés) + `X-User-Id`
  relayé tel quel, jamais fabriqué (motif `atelier-veille/main.py::_entetes_aval`).
- **Précision de sécurité par rapport au design** (correcte application du principe déjà
  validé « même garde-fou que S183 ») : la brique `atelier-images-video` elle-même DOIT
  vérifier un secret de service (`ATELIER_IMAGES_VIDEO_KEY`, nouveau) sur ses routes
  `/studio/*` et `/galerie/*`, sinon un appel direct sur le port 6160 (hors du Cœur)
  pourrait forger `X-User-Id` et emprunter `STUDIO_KEY`/`MEMOIRE_KEY` (que la brique
  détient) pour usurper une autre personne — reproduisant le trou S183 un cran plus loin.
  Le nouveau routeur du Cœur est le SEUL détenteur de `ATELIER_IMAGES_VIDEO_KEY`.
- `env_file` (pas `environment: VAR=${VAR:-}`) pour tout secret dans le nouveau
  `docker-compose.yml` — piège « env shadow » déjà rencontré (cf. mémoire
  `fix-env-shadow-composes`) : ne JAMAIS redéclarer `STUDIO_KEY`/`MEMOIRE_KEY`/
  `ATELIER_IMAGES_VIDEO_KEY` dans `environment:`.
- Tests 100% offline : `httpx.AsyncClient` toujours mocké, aucun appel réseau réel.
- Suivre le style du code existant : français dans les identifiants de domaine
  (`serie_id`, `identite`, `souvenir_id`), commentaires uniquement quand le POURQUOI n'est
  pas évident (pas de commentaires qui décrivent le QUOI).

---

## File Structure

```
briques/atelier-images-video/
├── manifest.json
├── Dockerfile
├── requirements.txt
├── docker-compose.yml
├── conftest.py
├── main.py                       # toutes les routes (motif atelier-veille : un seul fichier)
├── front.html
├── workplace.css                 # copie du socle partagé (outils/sync_socle.sh)
├── test_main.py                  # /sante
├── test_images_video.py          # génération libre (images + video)
├── test_synergies_studio.py      # /studio/* + _identite_service
├── test_galerie.py               # /galerie (mémoire)
└── test_front.py                 # marqueurs HTML/JS du front

core/
├── routers/atelier_images_video_proxy.py     # nouveau (mirror studio_proxy.py)
├── main.py                                    # modifié : montage du nouveau routeur
├── outils_communs.py                          # modifié : BRIQUES_PAR_PERSONNE + 1
└── test_atelier_images_video_proxy.py         # nouveau (mirror test_studio_proxy.py)

.env.example                       # modifié : section ATELIER_IMAGES_VIDEO_KEY
outils/sync_socle.sh                # modifié : CSS_BRIQUES + atelier-images-video
```

---

### Task 1: Scaffold de la brique + `/sante`

**Files:**
- Create: `briques/atelier-images-video/manifest.json`
- Create: `briques/atelier-images-video/Dockerfile`
- Create: `briques/atelier-images-video/requirements.txt`
- Create: `briques/atelier-images-video/docker-compose.yml`
- Create: `briques/atelier-images-video/conftest.py`
- Create: `briques/atelier-images-video/main.py`
- Create: `briques/atelier-images-video/test_main.py`

**Interfaces:**
- Produces: `main.app` (instance FastAPI) — toutes les tâches suivantes AJOUTENT des
  routes à ce même `app`, ne le recréent pas. Constantes de module `IMAGES_URL`,
  `VIDEO_URL`, `STUDIO_URL`, `MEMOIRE_URL` (str, base URL sans slash final).

- [ ] **Step 1: Créer le manifest**

`briques/atelier-images-video/manifest.json` :

```json
{
  "nom": "atelier-images-video",
  "famille": "media",
  "version": "0.1.0",
  "description": "Atelier Images & Vidéo : front unique qui réunit génération libre (images/video) et synergies Studio (portrait, couverture, teaser, animer) + galerie de créations sauvegardées (brique mémoire), sans dupliquer leur code. Aucune capacité LLM : surface humaine, pas un outil de l'assistant.",
  "role": "atelier-images-video",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/atelier-images-video",
  "port": 6160,
  "url_sante": "http://host.docker.internal:6160/sante",
  "url_ui": "http://localhost:6160/atelier",
  "depends_on": ["images", "video", "studio", "memoire"],
  "offre": ["front_atelier_images_video"],
  "capacites": []
}
```

- [ ] **Step 2: Créer `requirements.txt`**

```
# Brique atelier-images-video — front + composition HTTP. Dépendances minces et épinglées.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

- [ ] **Step 3: Créer le `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6160"]
```

- [ ] **Step 4: Créer `docker-compose.yml`**

```yaml
services:
  atelier-images-video:
    build: .
    container_name: workplace_atelier_images_video
    image: workplace/atelier-images-video:0.1.0   # tag épinglé (pas de :latest flottant)
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6160:6160"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # joindre images/video/studio/memoire sous Linux
    environment:
      - PORT=6160
      - CORS_ORIGINS=${CORS_ORIGINS:-*}
      - IMAGES_URL=http://host.docker.internal:5950
      - VIDEO_URL=http://host.docker.internal:5970
      - STUDIO_URL=http://host.docker.internal:6060
      - MEMOIRE_URL=http://host.docker.internal:5600
      # STUDIO_KEY / MEMOIRE_KEY / ATELIER_IMAGES_VIDEO_KEY : ABSENTS du `environment`
      # exprès (piège « env shadow » : ne PAS les redéclarer en `=${VAR:-}`, cf. mémoire
      # fix-env-shadow-composes) — viennent du .env racine via env_file.
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6160/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

- [ ] **Step 5: Créer `conftest.py` (environnement de test neutre)**

```python
"""Config de test : environnement neutre (mode ouvert) pour des tests déterministes, quel
que soit le shell — sinon un vrai secret de service traînant dans l'env changerait le
comportement testé (même motif que briques/images/conftest.py)."""
import os

for _v in ("ATELIER_IMAGES_VIDEO_KEY", "STUDIO_KEY", "MEMOIRE_KEY"):
    os.environ.pop(_v, None)
```

- [ ] **Step 6: Créer `main.py` (squelette + `/sante`)**

```python
"""Brique « atelier-images-video » — front unique de la génération créative.

Quasi uniquement du front (front.html) : compose images (génération libre), video
(génération libre), studio (synergies portrait/couverture/teaser/animer) et memoire
(galerie des créations sauvegardées) sans dupliquer leur code ni leur état. Motif de
composition identique à briques/atelier-veille/main.py (appel HTTP + repli honnête si la
brique composée est injoignable). Aucune capacité LLM (`capacites: []` dans le manifest) :
cette brique est une SURFACE HUMAINE, pas un outil de l'assistant.

Sécurité : les routes /studio/* et /galerie/* portent un secret de service
(STUDIO_KEY / MEMOIRE_KEY, déjà existants) + X-User-Id — mais CETTE brique elle-même
exige un secret (ATELIER_IMAGES_VIDEO_KEY) avant de faire confiance à un X-User-Id reçu,
sinon un appel direct sur ce port pourrait forger l'identité et emprunter STUDIO_KEY/
MEMOIRE_KEY pour usurper quelqu'un d'autre (même trou que S183, un cran plus loin). Seul
core/routers/atelier_images_video_proxy.py détient ce secret.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Atelier Images & Vidéo", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

IMAGES_URL = os.getenv("IMAGES_URL", "http://host.docker.internal:5950")
VIDEO_URL = os.getenv("VIDEO_URL", "http://host.docker.internal:5970")
STUDIO_URL = os.getenv("STUDIO_URL", "http://host.docker.internal:6060")
MEMOIRE_URL = os.getenv("MEMOIRE_URL", "http://host.docker.internal:5600")

_FRONT = Path(__file__).parent / "front.html"
# no-cache (pas no-store) : le navigateur revalide sur l'ETag à chaque chargement au lieu
# de garder une copie en cache heuristique — sans ça, un correctif poussé sur front.html
# reste invisible tant que l'utilisateur ne force pas un rechargement complet.
_ENTETES_FRONT = {"Cache-Control": "no-cache"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def racine():
    return FileResponse(_FRONT, media_type="text/html", headers=_ENTETES_FRONT)


@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def alias_atelier():
    return FileResponse(_FRONT, media_type="text/html", headers=_ENTETES_FRONT)


@app.get("/workplace.css", include_in_schema=False)
def css():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


async def _relayer(methode: str, url: str, entetes: dict, marque: str,
                   json_body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    """Relaie un appel HTTP vers une brique composée (motif atelier-veille::
    _entetes_aval) ; 502 honnête si injoignable ou si la réponse n'est pas du JSON
    exploitable — jamais un 500 opaque."""
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.request(methode, url, headers=entetes, json=json_body, params=params)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{marque} injoignable ({url}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"{marque} a refusé la requête ({r.status_code}).")
    return corps
```

- [ ] **Step 7: Créer `test_main.py`**

```python
"""Tests API de la brique atelier-images-video : santé + front (voir aussi
test_front.py, test_images_video.py, test_synergies_studio.py, test_galerie.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"
```

- [ ] **Step 8: Écrire un `front.html` minimal (juste assez pour que `/` réponde)**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Atelier Images & Vidéo</title>
</head>
<body>
<p>Atelier Images & Vidéo — en construction (Task 7 complète le vrai front).</p>
</body>
</html>
```

- [ ] **Step 9: Écrire un `workplace.css` minimal temporaire**

```css
/* Remplacé à la Task 7 par la copie du socle partagé via outils/sync_socle.sh. */
```

- [ ] **Step 10: Lancer les tests**

Run: `cd briques/atelier-images-video && python -m pytest test_main.py -v`
Expected: `1 passed`

- [ ] **Step 11: Commit**

```bash
git add briques/atelier-images-video/
git commit -m "feat(atelier-images-video): scaffold de la brique (manifest, docker, /sante)"
```

---

### Task 2: Génération libre — images et vidéo

**Files:**
- Modify: `briques/atelier-images-video/main.py`
- Create: `briques/atelier-images-video/test_images_video.py`

**Interfaces:**
- Consumes: `_relayer(methode, url, entetes, marque, json_body=None, params=None) -> dict`
  (Task 1), `IMAGES_URL`, `VIDEO_URL`.
- Produces: routes `POST /images/generer`, `GET /images/fournisseurs`,
  `POST /video/generer`, `GET /video/fournisseurs` — utilisées par le front (Task 7).

- [ ] **Step 1: Ajouter les modèles et routes de génération libre à `main.py`**

Ajouter à la fin de `briques/atelier-images-video/main.py` :

```python
class GenererImage(BaseModel):
    prompt: str
    negatif: Optional[str] = None
    largeur: int = 1024
    hauteur: int = 1024
    seed: Optional[int] = None
    fournisseur: Optional[str] = None


@app.post("/images/generer", tags=["images"])
async def images_generer(body: GenererImage):
    return await _relayer("POST", f"{IMAGES_URL}/generer", {}, "images", body.model_dump())


@app.get("/images/fournisseurs", tags=["images"])
async def images_fournisseurs():
    return await _relayer("GET", f"{IMAGES_URL}/fournisseurs", {}, "images")


class GenererVideo(BaseModel):
    prompt: str
    image_url: Optional[str] = None
    secondes: int = 5
    seed: Optional[int] = None
    fournisseur: Optional[str] = None


@app.post("/video/generer", tags=["video"])
async def video_generer(body: GenererVideo):
    return await _relayer("POST", f"{VIDEO_URL}/generer", {}, "video", body.model_dump())


@app.get("/video/fournisseurs", tags=["video"])
async def video_fournisseurs():
    return await _relayer("GET", f"{VIDEO_URL}/fournisseurs", {}, "video")
```

- [ ] **Step 2: Écrire `test_images_video.py` (test en échec d'abord)**

```python
"""Tests — génération libre (images/video), proxy sans auth vers les briques 5950/5970."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False):
    class FauxReponse:
        status_code = status
        def json(self):
            return rep_json

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, methode, url, headers=None, json=None, params=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = (methode, url, headers, json, params)
            return FauxReponse()
    return FauxClient


def test_images_generer_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"url": "/fichiers/img-1.png", "prompt": "un chat",
                         "backend": "fal", "place_holder": False})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/images/generer", json={"prompt": "un chat"})
    assert r.status_code == 200
    assert r.json()["backend"] == "fal"
    methode, url, _, corps, _ = Faux.dernier_appel
    assert methode == "POST"
    assert url == f"{M.IMAGES_URL}/generer"
    assert corps["prompt"] == "un chat"


def test_images_generer_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.post("/images/generer", json={"prompt": "un chat"})
    assert r.status_code == 502
    assert "images" in r.json()["detail"]


def test_images_fournisseurs_relaie_le_catalogue(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"fournisseurs": [{"nom": "fal", "configure": True}],
                                     "ordre": ["comfyui", "gateway", "fal"]}))
    r = client.get("/images/fournisseurs")
    assert r.status_code == 200
    assert r.json()["fournisseurs"][0]["nom"] == "fal"


def test_video_generer_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"url": "/fichiers/vid-1.mp4", "backend": "luma", "place_holder": False})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/video/generer", json={"prompt": "un chat qui court", "secondes": 4})
    assert r.status_code == 200
    methode, url, _, corps, _ = Faux.dernier_appel
    assert url == f"{M.VIDEO_URL}/generer"
    assert corps["secondes"] == 4


def test_video_generer_prompt_vide_rejete_par_pydantic():
    r = client.post("/video/generer", json={"secondes": 4})
    assert r.status_code == 422


def test_video_fournisseurs_relaie_le_catalogue(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"fournisseurs": [{"nom": "luma", "configure": False}],
                                     "ordre": ["fal", "replicate", "luma"]}))
    r = client.get("/video/fournisseurs")
    assert r.status_code == 200
    assert r.json()["fournisseurs"][0]["nom"] == "luma"
```

- [ ] **Step 3: Lancer les tests et vérifier qu'ils passent**

Run: `cd briques/atelier-images-video && python -m pytest test_images_video.py -v`
Expected: `6 passed`

- [ ] **Step 4: Commit**

```bash
git add briques/atelier-images-video/main.py briques/atelier-images-video/test_images_video.py
git commit -m "feat(atelier-images-video): génération libre image/vidéo (proxy sans auth)"
```

---

### Task 3: Sécurité de service — `_identite_service`

**Files:**
- Modify: `briques/atelier-images-video/main.py`
- Create: `briques/atelier-images-video/test_synergies_studio.py` (démarré ici, complété
  en Task 4)

**Interfaces:**
- Produces: `UTILISATEUR_DEFAUT = "perso"` (str), `_identite_service(x_api_key,
  authorization, x_user_id) -> str` (dépendance FastAPI), `_entetes_studio(identite: str)
  -> dict`, `_entetes_memoire(identite: str) -> dict` — utilisés par les Tasks 4 et 5.

- [ ] **Step 1: Ajouter la dépendance d'identité à `main.py`**

Ajouter après les imports existants (avec les autres imports FastAPI) et avant les
routes de génération libre :

```python
UTILISATEUR_DEFAUT = "perso"


def _identite_service(x_api_key: Optional[str] = Header(None),
                      authorization: Optional[str] = Header(None),
                      x_user_id: Optional[str] = Header(None)) -> str:
    """Identité de l'appelant pour les routes /studio/* et /galerie/* (motif
    briques/memoire/main.py::_identite_service) : gagée par ATELIER_IMAGES_VIDEO_KEY si
    configurée — SEUL core/routers/atelier_images_video_proxy.py la détient. Sans ce
    garde-fou, un appel direct sur cette brique pourrait forger X-User-Id et emprunter
    STUDIO_KEY/MEMOIRE_KEY (que CETTE brique détient) pour usurper une autre personne —
    même trou que S183, un cran plus loin dans la chaîne de composition."""
    cle = os.environ.get("ATELIER_IMAGES_VIDEO_KEY")
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if cle and presentee != cle:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or UTILISATEUR_DEFAUT


def _entetes_studio(identite: str) -> dict:
    return {"X-API-Key": os.environ.get("STUDIO_KEY", ""), "X-User-Id": identite}


def _entetes_memoire(identite: str) -> dict:
    return {"X-API-Key": os.environ.get("MEMOIRE_KEY", ""), "X-User-Id": identite}
```

- [ ] **Step 2: Créer `test_synergies_studio.py` avec les tests de `_identite_service`
  (le reste du fichier est complété en Task 4)**

```python
"""Tests — synergies Studio (portrait/couverture/teaser/animer), proxy avec secret de
service (STUDIO_KEY) + identité relayée. Voir aussi test_galerie.py (même motif de
sécurité, dépendance _identite_service partagée)."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def test_identite_service_mode_ouvert_honore_x_user_id_recu():
    """Sans ATELIER_IMAGES_VIDEO_KEY configurée (mode dev), l'en-tête X-User-Id reçu est
    honoré tel quel — il vient du routeur Cœur de confiance, jamais du navigateur direct
    en déploiement réel."""
    identite = M._identite_service(x_api_key=None, authorization=None, x_user_id="claire")
    assert identite == "claire"


def test_identite_service_mode_ouvert_replie_sur_perso():
    identite = M._identite_service(x_api_key=None, authorization=None, x_user_id=None)
    assert identite == "perso"


def test_identite_service_refuse_sans_bonne_cle(monkeypatch):
    monkeypatch.setenv("ATELIER_IMAGES_VIDEO_KEY", "cle-coeur")
    try:
        M._identite_service(x_api_key="mauvaise-cle", authorization=None, x_user_id="claire")
        assert False, "devait lever 401"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401
    finally:
        monkeypatch.delenv("ATELIER_IMAGES_VIDEO_KEY", raising=False)


def test_identite_service_accepte_avec_la_bonne_cle(monkeypatch):
    monkeypatch.setenv("ATELIER_IMAGES_VIDEO_KEY", "cle-coeur")
    try:
        identite = M._identite_service(x_api_key="cle-coeur", authorization=None, x_user_id="claire")
        assert identite == "claire"
    finally:
        monkeypatch.delenv("ATELIER_IMAGES_VIDEO_KEY", raising=False)


def test_entetes_studio_porte_la_cle_et_lidentite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    assert M._entetes_studio("claire") == {"X-API-Key": "cle-studio", "X-User-Id": "claire"}


def test_entetes_memoire_porte_la_cle_et_lidentite(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    assert M._entetes_memoire("claire") == {"X-API-Key": "cle-memoire", "X-User-Id": "claire"}
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/atelier-images-video && python -m pytest test_synergies_studio.py -v`
Expected: `6 passed`

- [ ] **Step 4: Commit**

```bash
git add briques/atelier-images-video/main.py briques/atelier-images-video/test_synergies_studio.py
git commit -m "feat(atelier-images-video): identité de service (ATELIER_IMAGES_VIDEO_KEY)"
```

---

### Task 4: Synergies Studio (portrait, animer, couverture, teaser)

**Files:**
- Modify: `briques/atelier-images-video/main.py`
- Modify: `briques/atelier-images-video/test_synergies_studio.py`

**Interfaces:**
- Consumes: `_relayer` (Task 1), `_identite_service`, `_entetes_studio` (Task 3),
  `STUDIO_URL`.
- Produces: routes `GET /studio/series`, `GET /studio/series/{serie_id}`,
  `POST /studio/series/{serie_id}/personnages/{pid}/portrait`, `.../animer`,
  `POST /studio/series/{serie_id}/episode/{n}/couverture`, `.../teaser` — utilisées par
  le front (Task 7).

- [ ] **Step 1: Ajouter les routes de synergie Studio à `main.py`**

Ajouter à la fin du fichier :

```python
@app.get("/studio/series", tags=["synergie"])
async def studio_series(identite: str = Depends(_identite_service)):
    return await _relayer("GET", f"{STUDIO_URL}/series", _entetes_studio(identite), "studio")


@app.get("/studio/series/{serie_id}", tags=["synergie"])
async def studio_serie(serie_id: str, identite: str = Depends(_identite_service)):
    return await _relayer("GET", f"{STUDIO_URL}/series/{serie_id}",
                          _entetes_studio(identite), "studio")


@app.post("/studio/series/{serie_id}/personnages/{pid}/portrait", tags=["synergie"])
async def studio_portrait(serie_id: str, pid: str, identite: str = Depends(_identite_service)):
    url = f"{STUDIO_URL}/series/{serie_id}/personnages/{pid}/portrait"
    return await _relayer("POST", url, _entetes_studio(identite), "studio")


@app.post("/studio/series/{serie_id}/personnages/{pid}/animer", tags=["synergie"])
async def studio_animer(serie_id: str, pid: str, identite: str = Depends(_identite_service)):
    url = f"{STUDIO_URL}/series/{serie_id}/personnages/{pid}/animer"
    return await _relayer("POST", url, _entetes_studio(identite), "studio")


@app.post("/studio/series/{serie_id}/episode/{n}/couverture", tags=["synergie"])
async def studio_couverture(serie_id: str, n: int, identite: str = Depends(_identite_service)):
    url = f"{STUDIO_URL}/series/{serie_id}/episode/{n}/couverture"
    return await _relayer("POST", url, _entetes_studio(identite), "studio")


@app.post("/studio/series/{serie_id}/episode/{n}/teaser", tags=["synergie"])
async def studio_teaser(serie_id: str, n: int, identite: str = Depends(_identite_service)):
    url = f"{STUDIO_URL}/series/{serie_id}/episode/{n}/teaser"
    return await _relayer("POST", url, _entetes_studio(identite), "studio")
```

- [ ] **Step 2: Ajouter les tests de proxy à `test_synergies_studio.py`**

Ajouter à la fin du fichier (réutilise le style `_client_json` de `test_images_video.py`,
dupliqué ici volontairement — motif déjà en place dans `atelier-veille/test_composition.py`
vs `test_main.py`, chaque fichier de test reste autonome) :

```python
def _client_json(rep_json, status=200, boom=False):
    class FauxReponse:
        status_code = status
        def json(self):
            return rep_json

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, methode, url, headers=None, json=None, params=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = (methode, url, headers, json, params)
            return FauxReponse()
    return FauxClient


def test_studio_series_relaie_lidentite_recue(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    Faux = _client_json([{"id": "s1", "titre": "Ma série"}])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/studio/series", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    _, url, entetes, _, _ = Faux.dernier_appel
    assert url == f"{M.STUDIO_URL}/series"
    assert entetes == {"X-API-Key": "cle-studio", "X-User-Id": "claire"}


def test_studio_serie_relaie_lidentite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    Faux = _client_json({"id": "s1", "titre": "Ma série", "personnages": [], "episodes": []})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/studio/series/s1", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    _, url, _, _, _ = Faux.dernier_appel
    assert url == f"{M.STUDIO_URL}/series/s1"


def test_studio_portrait_proxifie_sans_corps(monkeypatch):
    Faux = _client_json({"portrait_url": "/fichiers/p1.png", "place_holder": True,
                         "prompt_visuel": "…", "perso": {"id": "p1"}})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/personnages/p1/portrait")
    assert r.status_code == 200
    methode, url, _, corps, _ = Faux.dernier_appel
    assert methode == "POST"
    assert url == f"{M.STUDIO_URL}/series/s1/personnages/p1/portrait"
    assert corps is None


def test_studio_animer_proxifie(monkeypatch):
    Faux = _client_json({"clip_url": "/fichiers/c1.mp4", "place_holder": False,
                         "prompt_visuel": "…", "perso": {"id": "p1"}})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/personnages/p1/animer")
    assert r.status_code == 200
    assert r.json()["clip_url"] == "/fichiers/c1.mp4"


def test_studio_couverture_proxifie(monkeypatch):
    Faux = _client_json({"cover_url": "/fichiers/cov1.png", "place_holder": False, "n": 1})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/episode/1/couverture")
    assert r.status_code == 200
    _, url, _, _, _ = Faux.dernier_appel
    assert url == f"{M.STUDIO_URL}/series/s1/episode/1/couverture"


def test_studio_teaser_proxifie(monkeypatch):
    Faux = _client_json({"teaser_url": "/fichiers/t1.mp4", "place_holder": False, "n": 1})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/episode/1/teaser")
    assert r.status_code == 200
    assert r.json()["teaser_url"] == "/fichiers/t1.mp4"


def test_studio_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/studio/series")
    assert r.status_code == 502
    assert "studio" in r.json()["detail"]


def test_studio_personnage_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Personnage introuvable"}, status=404))
    r = client.post("/studio/series/s1/personnages/px/portrait")
    assert r.status_code == 404
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/atelier-images-video && python -m pytest test_synergies_studio.py -v`
Expected: `14 passed`

- [ ] **Step 4: Commit**

```bash
git add briques/atelier-images-video/main.py briques/atelier-images-video/test_synergies_studio.py
git commit -m "feat(atelier-images-video): synergies Studio (portrait/animer/couverture/teaser)"
```

---

### Task 5: Galerie (brique mémoire)

**Files:**
- Modify: `briques/atelier-images-video/main.py`
- Create: `briques/atelier-images-video/test_galerie.py`

**Interfaces:**
- Consumes: `_relayer`, `_identite_service`, `_entetes_memoire` (Tasks 1, 3), `MEMOIRE_URL`.
- Produces: routes `POST /galerie`, `GET /galerie`, `DELETE /galerie/{souvenir_id}` —
  utilisées par le front (Task 7).

- [ ] **Step 1: Ajouter le modèle et les routes de galerie à `main.py`**

Ajouter à la fin du fichier :

```python
class AjouterGalerie(BaseModel):
    titre: str
    prompt: str
    medium: str                       # "image" | "video"
    url: str
    fournisseur: Optional[str] = None
    place_holder: bool = False


@app.post("/galerie", tags=["galerie"])
async def galerie_ajouter(body: AjouterGalerie, identite: str = Depends(_identite_service)):
    corps = {
        "type": "ressource", "titre": body.titre, "contenu": body.prompt,
        "wing": "atelier-images-video", "room": body.medium,
        "metadata": {"url": body.url, "fournisseur": body.fournisseur,
                    "place_holder": body.place_holder},
    }
    return await _relayer("POST", f"{MEMOIRE_URL}/retenir", _entetes_memoire(identite),
                          "mémoire", corps)


@app.get("/galerie", tags=["galerie"])
async def galerie_lister(medium: Optional[str] = None,
                         identite: str = Depends(_identite_service)):
    params = {"wing": "atelier-images-video"}
    if medium:
        params["room"] = medium
    return await _relayer("GET", f"{MEMOIRE_URL}/souvenirs", _entetes_memoire(identite),
                          "mémoire", params=params)


@app.delete("/galerie/{souvenir_id}", tags=["galerie"])
async def galerie_supprimer(souvenir_id: str, identite: str = Depends(_identite_service)):
    url = f"{MEMOIRE_URL}/souvenir/{souvenir_id}"
    return await _relayer("DELETE", url, _entetes_memoire(identite), "mémoire")
```

- [ ] **Step 2: Créer `test_galerie.py`**

```python
"""Tests — galerie (POST/GET/DELETE /galerie), proxy vers la brique mémoire (5600) avec
secret de service (MEMOIRE_KEY) + identité relayée."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False):
    class FauxReponse:
        status_code = status
        def json(self):
            return rep_json

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, methode, url, headers=None, json=None, params=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = (methode, url, headers, json, params)
            return FauxReponse()
    return FauxClient


def test_galerie_ajouter_construit_le_souvenir_ressource(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    Faux = _client_json({"retenu": True, "id": "n1", "titre": "un chat", "type": "ressource",
                         "wing": "atelier-images-video", "room": "image"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/galerie", json={
        "titre": "un chat", "prompt": "un chat qui dort au soleil",
        "medium": "image", "url": "/fichiers/img-1.png",
        "fournisseur": "fal", "place_holder": False,
    }, headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    methode, url, entetes, corps, _ = Faux.dernier_appel
    assert url == f"{M.MEMOIRE_URL}/retenir"
    assert entetes == {"X-API-Key": "cle-memoire", "X-User-Id": "claire"}
    assert corps == {
        "type": "ressource", "titre": "un chat", "contenu": "un chat qui dort au soleil",
        "wing": "atelier-images-video", "room": "image",
        "metadata": {"url": "/fichiers/img-1.png", "fournisseur": "fal", "place_holder": False},
    }


def test_galerie_lister_filtre_par_wing_et_medium(monkeypatch):
    Faux = _client_json({"total": 1, "souvenirs": [{"id": "n1", "titre": "un chat"}]})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/galerie", params={"medium": "image"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    _, url, _, _, params = Faux.dernier_appel
    assert url == f"{M.MEMOIRE_URL}/souvenirs"
    assert params == {"wing": "atelier-images-video", "room": "image"}


def test_galerie_lister_sans_filtre_medium(monkeypatch):
    Faux = _client_json({"total": 0, "souvenirs": []})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/galerie")
    _, _, _, _, params = Faux.dernier_appel
    assert params == {"wing": "atelier-images-video"}


def test_galerie_supprimer_proxifie(monkeypatch):
    Faux = _client_json({"supprime": True, "id": "n1"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.delete("/galerie/n1")
    assert r.status_code == 200
    methode, url, _, _, _ = Faux.dernier_appel
    assert methode == "DELETE"
    assert url == f"{M.MEMOIRE_URL}/souvenir/n1"


def test_galerie_memoire_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/galerie")
    assert r.status_code == 502
    assert "mémoire" in r.json()["detail"]
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/atelier-images-video && python -m pytest test_galerie.py -v`
Expected: `5 passed`

- [ ] **Step 4: Lancer toute la suite de la brique avant de continuer**

Run: `cd briques/atelier-images-video && python -m pytest -v`
Expected: `32 passed` (1 + 6 + 6 + 14 + 5 des Tasks 1-5)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-images-video/main.py briques/atelier-images-video/test_galerie.py
git commit -m "feat(atelier-images-video): galerie des créations (proxy vers mémoire)"
```

---

### Task 6: Copier le socle CSS partagé

**Files:**
- Modify: `outils/sync_socle.sh`
- Modify: `briques/atelier-images-video/workplace.css` (régénéré par le script)

**Interfaces:**
- Aucune (fichier statique).

- [ ] **Step 1: Ajouter la brique à la liste des consommateurs CSS**

Dans `outils/sync_socle.sh`, modifier la ligne :

```bash
CSS_BRIQUES=(synopsis voix personnages studio transcription atelier-veille)
```

en :

```bash
CSS_BRIQUES=(synopsis voix personnages studio transcription atelier-veille atelier-images-video)
```

- [ ] **Step 2: Lancer le script de synchro**

Run: `bash outils/sync_socle.sh`
Expected: la sortie liste `→ briques/atelier-images-video/workplace.css` parmi les
cibles copiées.

- [ ] **Step 3: Vérifier que le contenu copié correspond au socle source**

Run: `diff shared/static/workplace.css briques/atelier-images-video/workplace.css`
Expected: aucune sortie (fichiers identiques).

- [ ] **Step 4: Commit**

```bash
git add outils/sync_socle.sh briques/atelier-images-video/workplace.css
git commit -m "chore(atelier-images-video): synchronise le socle CSS partagé"
```

---

### Task 7: Front — `front.html` (4 onglets)

**Files:**
- Modify: `briques/atelier-images-video/front.html` (remplace le placeholder de la Task 1)
- Create: `briques/atelier-images-video/test_front.py`

**Interfaces:**
- Consumes (fetch JS) : toutes les routes des Tasks 2, 4, 5.
- Convention de préfixe : `const API_BASE = window.ATELIER_IV_API_BASE || '';` — motif
  identique à `briques/studio/front.html` (`STUDIO_API_BASE`), nécessaire pour que ce
  même front fonctionne AUTANT servi en direct (`API_BASE=''`) QUE proxié par le Cœur
  sous `/atelier-images-video-app/*` (Task 8, qui injecte cette variable).

- [ ] **Step 1: Écrire le `front.html` complet**

Remplacer entièrement `briques/atelier-images-video/front.html` par :

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atelier Images & Vidéo</title>
<link rel="stylesheet" href="/workplace.css">
<style>
  :root{
    --bg:var(--wp-bg); --panel:var(--wp-surface); --panel2:var(--wp-surface-2); --line:var(--wp-border);
    --ink:var(--wp-text); --mut:var(--wp-muted); --accent:#c77dff; --ok:var(--wp-ok);
    --warn:var(--wp-warn); --bad:var(--wp-err);
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:'Segoe UI',-apple-system,system-ui,sans-serif;min-height:100vh}
  .wrap{max-width:1180px;margin:0 auto;padding:26px 22px 90px}
  header h1{margin:0;font-size:1.5rem}
  header h1 .dot{color:var(--accent)}
  header p{color:var(--mut);margin:5px 0 0;font-size:.9rem}
  nav.onglets{display:flex;gap:8px;margin:18px 0;flex-wrap:wrap}
  nav.onglets button{cursor:pointer;border:1px solid var(--line);background:var(--panel2);
    color:var(--mut);border-radius:20px;padding:7px 16px;font-size:.85rem}
  nav.onglets button.actif{background:var(--accent);color:#1a0b26;border-color:var(--accent);font-weight:600}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:16px}
  .vue{display:none}
  .vue.actif{display:block}
  label{display:block;font-size:.8rem;color:var(--mut);margin:10px 0 4px}
  input,textarea,select{width:100%;padding:8px;border-radius:8px;border:1px solid var(--line);
    background:var(--panel2);color:var(--ink);font-family:inherit}
  textarea{min-height:70px;resize:vertical}
  .ligne{display:flex;gap:10px;flex-wrap:wrap}
  .ligne>div{flex:1;min-width:140px}
  button.action{margin-top:14px;padding:9px 18px;border-radius:8px;border:1px solid var(--accent);
    background:var(--accent);color:#1a0b26;font-weight:600;cursor:pointer}
  button.discret{padding:6px 12px;border-radius:8px;border:1px solid var(--line);
    background:transparent;color:var(--mut);cursor:pointer;font-size:.8rem}
  .resultat{margin-top:16px;padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}
  .resultat img,.resultat video{max-width:100%;border-radius:8px;display:block}
  .avert{color:var(--warn);font-size:.8rem;margin-top:6px}
  .erreur{color:var(--bad);font-size:.85rem;margin-top:8px}
  .carte{border:1px solid var(--line);border-radius:10px;padding:12px;margin-top:10px}
  .carte h4{margin:0 0 6px}
  .carte .meta{color:var(--mut);font-size:.8rem;margin-bottom:8px}
  .grille{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-top:14px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="dot">🎨</span> Atelier Images & Vidéo</h1>
    <p>Génération libre, synergies avec le Studio (portraits, couvertures, teasers) et galerie des créations.</p>
  </header>
  <nav class="onglets">
    <button id="btn-image" class="actif" onclick="ouvrirOnglet('image')">Image libre</button>
    <button id="btn-video" onclick="ouvrirOnglet('video')">Vidéo libre</button>
    <button id="btn-synergies" onclick="ouvrirOnglet('synergies')">Synergies</button>
    <button id="btn-galerie" onclick="ouvrirOnglet('galerie')">Galerie</button>
  </nav>

  <div id="vue-image" class="vue actif panel">
    <div class="ligne">
      <div style="flex:2">
        <label>Prompt</label>
        <textarea id="image-prompt" placeholder="Un chat qui dort au soleil, style aquarelle…"></textarea>
      </div>
      <div>
        <label>Mes prompts favoris</label>
        <select id="image-presets" onchange="chargerPreset('image')"><option value="">—</option></select>
        <button class="discret" style="margin-top:6px" onclick="sauverPreset('image')">💾 Sauver ce prompt</button>
      </div>
    </div>
    <label>Négatif (optionnel)</label>
    <input id="image-negatif" placeholder="flou, déformé…">
    <div class="ligne">
      <div><label>Largeur</label><input id="image-largeur" type="number" value="1024"></div>
      <div><label>Hauteur</label><input id="image-hauteur" type="number" value="1024"></div>
      <div><label>Fournisseur</label><select id="image-fournisseur"><option value="">auto (ordre par défaut)</option></select></div>
    </div>
    <button class="action" onclick="genererImage()">Générer l'image</button>
    <div id="image-erreur" class="erreur"></div>
    <div id="image-resultat"></div>
  </div>

  <div id="vue-video" class="vue panel">
    <div class="ligne">
      <div style="flex:2">
        <label>Prompt</label>
        <textarea id="video-prompt" placeholder="Un chat qui court dans un jardin…"></textarea>
      </div>
      <div>
        <label>Mes prompts favoris</label>
        <select id="video-presets" onchange="chargerPreset('video')"><option value="">—</option></select>
        <button class="discret" style="margin-top:6px" onclick="sauverPreset('video')">💾 Sauver ce prompt</button>
      </div>
    </div>
    <label>Image de départ (URL, optionnel — image→vidéo)</label>
    <input id="video-image-url" placeholder="/fichiers/img-1.png">
    <div class="ligne">
      <div><label>Durée (secondes)</label><input id="video-secondes" type="number" value="5"></div>
      <div><label>Fournisseur</label><select id="video-fournisseur"><option value="">auto (ordre par défaut)</option></select></div>
    </div>
    <button class="action" onclick="genererVideo()">Générer la vidéo</button>
    <div id="video-erreur" class="erreur"></div>
    <div id="video-resultat"></div>
  </div>

  <div id="vue-synergies" class="vue panel">
    <label>Série</label>
    <select id="synergie-serie" onchange="changerSerie()"><option value="">Choisis une série…</option></select>
    <div id="synergie-erreur" class="erreur"></div>
    <div id="synergie-personnages"></div>
    <div id="synergie-episodes"></div>
  </div>

  <div id="vue-galerie" class="vue panel">
    <div class="ligne">
      <button class="discret" onclick="chargerGalerie('')">Tout</button>
      <button class="discret" onclick="chargerGalerie('image')">Images</button>
      <button class="discret" onclick="chargerGalerie('video')">Vidéos</button>
    </div>
    <div id="galerie-erreur" class="erreur"></div>
    <div id="galerie-grille" class="grille"></div>
  </div>
</div>
<script>
function ouvrirOnglet(nom) {
  for (const n of ['image', 'video', 'synergies', 'galerie']) {
    document.getElementById('vue-' + n).classList.toggle('actif', n === nom);
    document.getElementById('btn-' + n).classList.toggle('actif', n === nom);
  }
  if (nom === 'synergies') chargerSeries();
  if (nom === 'galerie') chargerGalerie('');
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Préfixe posé par le proxy Cœur /atelier-images-video-app/* : vide en usage autoporté,
// donc ce changement est un NO-OP hors du proxy — mêmes chemins relatifs qu'avant.
const API_BASE = window.ATELIER_IV_API_BASE || '';
async function api(path, method = 'GET', body = null) {
  const r = await fetch(API_BASE + path, {
    method, headers: body ? {'Content-Type': 'application/json'} : {},
    body: body != null ? JSON.stringify(body) : null,
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || ('HTTP ' + r.status)); }
  return r.status === 204 ? null : r.json();
}

// ── Presets (localStorage, aucun backend) ─────────────────────────────────
function clePreset(type) { return 'atelier_iv_presets_' + type; }
function listerPresets(type) { return JSON.parse(localStorage.getItem(clePreset(type)) || '[]'); }
function rafraichirPresets(type) {
  const select = document.getElementById(type + '-presets');
  const presets = listerPresets(type);
  select.innerHTML = '<option value="">—</option>' +
    presets.map((p, i) => `<option value="${i}">${esc(p.nom)}</option>`).join('');
}
function sauverPreset(type) {
  const nom = prompt('Nom de ce prompt favori ?');
  if (!nom) return;
  const valeur = document.getElementById(type + '-prompt').value.trim();
  if (!valeur) return;
  const presets = listerPresets(type);
  presets.push({nom, prompt: valeur});
  localStorage.setItem(clePreset(type), JSON.stringify(presets));
  rafraichirPresets(type);
}
function chargerPreset(type) {
  const i = document.getElementById(type + '-presets').value;
  if (i === '') return;
  document.getElementById(type + '-prompt').value = listerPresets(type)[i].prompt;
}
rafraichirPresets('image');
rafraichirPresets('video');

// ── Génération libre ───────────────────────────────────────────────────────
async function chargerFournisseurs(type) {
  const select = document.getElementById(type + '-fournisseur');
  try {
    const data = await api('/' + type + '/fournisseurs');
    select.innerHTML = '<option value="">auto (ordre par défaut)</option>' +
      data.fournisseurs.map(f => `<option value="${esc(f.nom)}">${esc(f.nom)}${f.configure ? '' : ' (non configuré)'}</option>`).join('');
  } catch (e) { /* select reste sur le seul choix "auto" */ }
}
chargerFournisseurs('images');
chargerFournisseurs('video');

function afficherResultatMedia(cible, medium, data, titre, prompt) {
  const url = data.url;
  const avert = data.place_holder ? '<div class="avert">⚠️ Placeholder — aucun fournisseur réel n\'a produit ce média.</div>' : '';
  const media = medium === 'image' ? `<img src="${esc(url)}" alt="résultat">` : `<video controls src="${esc(url)}"></video>`;
  cible.innerHTML = `<div class="resultat">${media}${avert}
    <button class="discret" style="margin-top:8px" onclick='ajouterGalerie(${JSON.stringify(medium)}, ${JSON.stringify(titre)}, ${JSON.stringify(prompt)}, ${JSON.stringify(url)}, ${JSON.stringify(data.backend || null)}, ${!!data.place_holder})'>➕ Ajouter à la galerie</button>
  </div>`;
}

async function genererImage() {
  const prompt = document.getElementById('image-prompt').value.trim();
  const erreur = document.getElementById('image-erreur');
  const cible = document.getElementById('image-resultat');
  erreur.textContent = ''; cible.innerHTML = '';
  if (!prompt) { erreur.textContent = 'Le prompt est vide.'; return; }
  try {
    const data = await api('/images/generer', 'POST', {
      prompt,
      negatif: document.getElementById('image-negatif').value.trim() || null,
      largeur: parseInt(document.getElementById('image-largeur').value, 10) || 1024,
      hauteur: parseInt(document.getElementById('image-hauteur').value, 10) || 1024,
      fournisseur: document.getElementById('image-fournisseur').value || null,
    });
    afficherResultatMedia(cible, 'image', data, prompt.slice(0, 60), prompt);
  } catch (e) { erreur.textContent = String(e.message || e); }
}

async function genererVideo() {
  const prompt = document.getElementById('video-prompt').value.trim();
  const erreur = document.getElementById('video-erreur');
  const cible = document.getElementById('video-resultat');
  erreur.textContent = ''; cible.innerHTML = '';
  if (!prompt) { erreur.textContent = 'Le prompt est vide.'; return; }
  try {
    const data = await api('/video/generer', 'POST', {
      prompt,
      image_url: document.getElementById('video-image-url').value.trim() || null,
      secondes: parseInt(document.getElementById('video-secondes').value, 10) || 5,
      fournisseur: document.getElementById('video-fournisseur').value || null,
    });
    afficherResultatMedia(cible, 'video', data, prompt.slice(0, 60), prompt);
  } catch (e) { erreur.textContent = String(e.message || e); }
}

// ── Synergies Studio ───────────────────────────────────────────────────────
async function chargerSeries() {
  const select = document.getElementById('synergie-serie');
  const erreur = document.getElementById('synergie-erreur');
  erreur.textContent = '';
  try {
    const series = await api('/studio/series');
    select.innerHTML = '<option value="">Choisis une série…</option>' +
      series.map(s => `<option value="${esc(s.id)}">${esc(s.titre)}</option>`).join('');
  } catch (e) { erreur.textContent = String(e.message || e); }
}

async function changerSerie() {
  const id = document.getElementById('synergie-serie').value;
  const zonePersos = document.getElementById('synergie-personnages');
  const zoneEpisodes = document.getElementById('synergie-episodes');
  const erreur = document.getElementById('synergie-erreur');
  erreur.textContent = ''; zonePersos.innerHTML = ''; zoneEpisodes.innerHTML = '';
  if (!id) return;
  try {
    const serie = await api('/studio/series/' + id);
    zonePersos.innerHTML = '<h3>Personnages</h3>' + (serie.personnages || []).map(p => `
      <div class="carte" id="perso-${esc(p.id)}">
        <h4>${esc(p.nom)}</h4>
        <div class="meta">${esc(p.role || '')}</div>
        <button class="discret" onclick="genererPortrait('${esc(id)}','${esc(p.id)}')">🖼️ Portrait</button>
        <button class="discret" onclick="genererAnimation('${esc(id)}','${esc(p.id)}')">🎬 Animer</button>
        <div id="perso-resultat-${esc(p.id)}"></div>
      </div>`).join('') || '<p style="color:var(--mut)">Aucun personnage dans cette série.</p>';
    zoneEpisodes.innerHTML = '<h3>Chapitres</h3>' + (serie.episodes || []).map(e => `
      <div class="carte" id="episode-${e.n}">
        <h4>Chapitre ${e.n}</h4>
        <div class="meta">${esc((e.consigne || '').slice(0, 100))}</div>
        <button class="discret" onclick="genererCouverture('${esc(id)}',${e.n})">🖼️ Couverture</button>
        <button class="discret" onclick="genererTeaser('${esc(id)}',${e.n})">🎬 Teaser</button>
        <div id="episode-resultat-${e.n}"></div>
      </div>`).join('') || '<p style="color:var(--mut)">Aucun chapitre dans cette série.</p>';
  } catch (e) { erreur.textContent = String(e.message || e); }
}

async function genererPortrait(serieId, pid) {
  const cible = document.getElementById('perso-resultat-' + pid);
  try {
    const data = await api(`/studio/series/${serieId}/personnages/${pid}/portrait`, 'POST');
    afficherResultatMedia(cible, 'image', {url: data.portrait_url, place_holder: data.place_holder},
      'Portrait ' + (data.perso ? data.perso.nom : ''), data.prompt_visuel || '');
  } catch (e) { cible.innerHTML = `<div class="erreur">${esc(e.message || e)}</div>`; }
}

async function genererAnimation(serieId, pid) {
  const cible = document.getElementById('perso-resultat-' + pid);
  try {
    const data = await api(`/studio/series/${serieId}/personnages/${pid}/animer`, 'POST');
    afficherResultatMedia(cible, 'video', {url: data.clip_url, place_holder: data.place_holder},
      'Animation ' + (data.perso ? data.perso.nom : ''), data.prompt_visuel || '');
  } catch (e) { cible.innerHTML = `<div class="erreur">${esc(e.message || e)}</div>`; }
}

async function genererCouverture(serieId, n) {
  const cible = document.getElementById('episode-resultat-' + n);
  try {
    const data = await api(`/studio/series/${serieId}/episode/${n}/couverture`, 'POST');
    afficherResultatMedia(cible, 'image', {url: data.cover_url, place_holder: data.place_holder},
      'Couverture chapitre ' + n, data.prompt_visuel || '');
  } catch (e) { cible.innerHTML = `<div class="erreur">${esc(e.message || e)}</div>`; }
}

async function genererTeaser(serieId, n) {
  const cible = document.getElementById('episode-resultat-' + n);
  try {
    const data = await api(`/studio/series/${serieId}/episode/${n}/teaser`, 'POST');
    afficherResultatMedia(cible, 'video', {url: data.teaser_url, place_holder: data.place_holder},
      'Teaser chapitre ' + n, data.prompt_visuel || '');
  } catch (e) { cible.innerHTML = `<div class="erreur">${esc(e.message || e)}</div>`; }
}

// ── Galerie ─────────────────────────────────────────────────────────────
async function ajouterGalerie(medium, titre, prompt, url, fournisseur, place_holder) {
  try {
    await api('/galerie', 'POST', {titre, prompt, medium, url, fournisseur, place_holder});
  } catch (e) { alert('Ajout à la galerie impossible : ' + (e.message || e)); }
}

async function chargerGalerie(medium) {
  const cible = document.getElementById('galerie-grille');
  const erreur = document.getElementById('galerie-erreur');
  erreur.textContent = ''; cible.innerHTML = '';
  try {
    const data = await api('/galerie' + (medium ? '?medium=' + medium : ''));
    cible.innerHTML = (data.souvenirs || []).map(s => {
      const meta = s.metadata || {};
      const media = meta.url ? (s.room === 'video'
        ? `<video controls src="${esc(meta.url)}"></video>`
        : `<img src="${esc(meta.url)}" alt="${esc(s.titre)}">`) : '';
      return `<div class="carte">
        <h4>${esc(s.titre)}</h4>
        ${media}
        <div class="meta">${esc(meta.fournisseur || '')}</div>
        <button class="discret" onclick="supprimerGalerie('${esc(s.id)}')">🗑️ Supprimer</button>
      </div>`;
    }).join('') || '<p style="color:var(--mut)">Aucune création sauvegardée pour l\'instant.</p>';
  } catch (e) { erreur.textContent = String(e.message || e); }
}

async function supprimerGalerie(id) {
  try {
    await api('/galerie/' + id, 'DELETE');
    chargerGalerie('');
  } catch (e) { alert('Suppression impossible : ' + (e.message || e)); }
}
</script>
</body>
</html>
```

- [ ] **Step 2: Créer `test_front.py`**

```python
"""Tests — front de l'atelier-images-video servi PAR la brique (motif atelier-veille/
test_front.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_racine_sert_le_front_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Atelier Images & Vidéo</title>" in r.text


def test_alias_atelier_sert_le_meme_front():
    assert client.get("/atelier").text == client.get("/").text


def test_workplace_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_front_utilise_le_prefixe_api_base_du_proxy_coeur():
    html = client.get("/").text
    assert "window.ATELIER_IV_API_BASE" in html
    assert "const API_BASE = window.ATELIER_IV_API_BASE || '';" in html


def test_front_couvre_la_generation_libre():
    html = client.get("/").text
    for marqueur in ("genererImage", "genererVideo", "/images/generer", "/video/generer",
                     "chargerFournisseurs"):
        assert marqueur in html


def test_front_couvre_les_synergies_studio():
    html = client.get("/").text
    for marqueur in ("chargerSeries", "genererPortrait", "genererAnimation",
                     "genererCouverture", "genererTeaser", "/studio/series"):
        assert marqueur in html


def test_front_couvre_la_galerie():
    html = client.get("/").text
    for marqueur in ("chargerGalerie", "ajouterGalerie", "supprimerGalerie", "/galerie"):
        assert marqueur in html


def test_front_couvre_les_presets_localstorage():
    html = client.get("/").text
    for marqueur in ("sauverPreset", "chargerPreset", "localStorage", "atelier_iv_presets_"):
        assert marqueur in html
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/atelier-images-video && python -m pytest test_front.py -v`
Expected: `8 passed`

- [ ] **Step 4: Lancer toute la suite de la brique**

Run: `cd briques/atelier-images-video && python -m pytest -v`
Expected: `40 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-images-video/front.html briques/atelier-images-video/test_front.py
git commit -m "feat(atelier-images-video): front 4 onglets (image/video/synergies/galerie)"
```

---

### Task 8: Proxy Cœur — `/atelier-images-video-app/*`

**Files:**
- Create: `core/routers/atelier_images_video_proxy.py`
- Modify: `core/main.py:24` (import), `core/main.py` (montage du routeur, après
  `studio_proxy`)
- Modify: `core/outils_communs.py:51-52` (`BRIQUES_PAR_PERSONNE`)
- Create: `core/test_atelier_images_video_proxy.py`

**Interfaces:**
- Consumes: `orchestrateur._brique_base(registre, nom)`,
  `outils_communs._entetes_brique(brique)`, `contexte_tenant.lire_contexte_tenant`,
  `auth.exiger_session` (tous déjà existants, inchangés).
- Produces: `router` (APIRouter) monté sous `/atelier-images-video-app/*`.

- [ ] **Step 1: Ajouter `"atelier-images-video"` à `BRIQUES_PAR_PERSONNE`**

Dans `core/outils_communs.py`, remplacer :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire", "studio", "veille-info",
                        "veille-prospection"}
```

par :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire", "studio", "veille-info",
                        "veille-prospection", "atelier-images-video"}
```

- [ ] **Step 2: Créer `core/routers/atelier_images_video_proxy.py`**

```python
"""Proxy « atelier-images-video » du Cœur : vue native du front de l'atelier créatif.

Même motif que core/routers/studio_proxy.py : le frontend autoporté de la brique
`briques/atelier-images-video` (`front.html`) fait ses appels via `API_BASE + path`, où
`API_BASE` vaut `window.ATELIER_IV_API_BASE` (vide en usage autoporté). On sert cette MÊME
page sous `/atelier-images-video-app/*` avec `ATELIER_IV_API_BASE` posé à ce préfixe, et on
proxy chaque appel vers la vraie brique en y injectant l'identité de la SESSION Cœur
courante (`outils_communs._entetes_brique("atelier-images-video")` → X-User-Id +
X-API-Key: ATELIER_IMAGES_VIDEO_KEY).

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session`
+ `lire_contexte_tenant` posés sur ce router dans `main.py`) compte. Sans ce garde-fou, un
appel direct sur le port 6160 pourrait forger X-User-Id et emprunter STUDIO_KEY/MEMOIRE_KEY
(que la brique atelier-images-video détient) pour usurper une autre personne sur les
synergies Studio ou la galerie — même trou que S183, un cran plus loin dans la chaîne de
composition (cf. briques/atelier-images-video/main.py::_identite_service).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/atelier-images-video-app"
_TIMEOUT = 60.0


def _base() -> str:
    return orchestrateur._brique_base(registre, "atelier-images-video")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("atelier-images-video"))
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


async def _page(chemin_brique: str, request: Request) -> HTMLResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}{chemin_brique}", headers=_entetes(request))
    page = r.text.replace(
        "</head>", f"<script>window.ATELIER_IV_API_BASE='{_PREFIXE}';</script></head>")
    return HTMLResponse(page, status_code=r.status_code)


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def atelier_iv_racine(request: Request):
    return await _page("/", request)


@router.get(_PREFIXE + "/atelier", response_class=HTMLResponse)
async def atelier_iv_atelier(request: Request):
    return await _page("/atelier", request)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def atelier_iv_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes (API + `/workplace.css`)."""
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

- [ ] **Step 3: Monter le routeur dans `core/main.py`**

Modifier la ligne d'import (`core/main.py:24`) :

```python
from routers import agenda, assistant, dashboard, invite, mail_proxy, profil, studio_proxy, systeme, usine
```

en :

```python
from routers import (agenda, assistant, atelier_images_video_proxy, dashboard, invite,
                     mail_proxy, profil, studio_proxy, systeme, usine)
```

Puis, juste après le montage de `studio_proxy` (repérer le commentaire « Studio (S187) »
et la ligne `app.include_router(studio_proxy.router, ...)`), ajouter :

```python
# Atelier Images & Vidéo : même motif que Studio — session obligatoire + contexte de
# tenant, pour que les synergies (portrait/couverture/teaser/animer) et la galerie soient
# isolées par personne, cf. core/routers/atelier_images_video_proxy.py.
app.include_router(atelier_images_video_proxy.router,
                   dependencies=[Depends(exiger_session)] + _tenant)
```

- [ ] **Step 4: Créer `core/test_atelier_images_video_proxy.py`**

```python
"""Proxy atelier-images-video du Cœur : vue native /atelier-images-video-app/*, isolée
PAR PERSONNE. Motif copié de core/test_studio_proxy.py. Sans réseau : httpx.AsyncClient est
remplacé par un faux client qui enregistre les appels (méthode, url, en-têtes). Vérifie que
l'identité forwardée à la brique vient de LA SESSION (contexte de tenant), jamais de ce
que le navigateur a lui-même posé sur sa requête au Cœur."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ["ATELIER_IMAGES_VIDEO_KEY"] = "cle-coeur-atelier-iv"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import atelier_images_video_proxy  # noqa: E402

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
    monkeypatch.setattr(atelier_images_video_proxy, "_base", lambda: "http://atelier-iv")
    monkeypatch.setattr(atelier_images_video_proxy, "httpx",
                        type("_H", (), {"AsyncClient": _FakeClient}))


def test_racine_injecte_le_prefixe(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/atelier-images-video-app/", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert "window.ATELIER_IV_API_BASE='/atelier-images-video-app';" in r.text


def test_identite_de_session_forwardee_pas_celle_du_navigateur(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/atelier-images-video-app/studio/series", headers={
        "X-User-Id": "claire", "X-API-Key": "cle-volee-par-le-navigateur",
    })
    assert r.status_code == 200
    methode, url, entetes = APPELS[-1]
    assert url == "http://atelier-iv/studio/series"
    assert entetes["X-User-Id"] == "claire"
    assert entetes["X-API-Key"] == "cle-coeur-atelier-iv"


def test_deux_personnes_appels_distincts(monkeypatch):
    _setup(monkeypatch)
    client.get("/atelier-images-video-app/galerie", headers={"X-User-Id": "claire"})
    client.get("/atelier-images-video-app/galerie", headers={"X-User-Id": "marina"})
    identites = [e["X-User-Id"] for _, _, e in APPELS]
    assert identites == ["claire", "marina"]
```

- [ ] **Step 5: Lancer les tests du Cœur**

Run: `cd core && python -m pytest test_atelier_images_video_proxy.py -v`
Expected: `3 passed`

- [ ] **Step 6: Lancer toute la suite du Cœur pour vérifier l'absence de régression**

Run: `cd core && python -m pytest -q`
Expected: tous les tests passent (aucune régression sur `test_studio_proxy.py`,
`test_mail_proxy.py`, etc.)

- [ ] **Step 7: Commit**

```bash
git add core/routers/atelier_images_video_proxy.py core/main.py core/outils_communs.py \
       core/test_atelier_images_video_proxy.py
git commit -m "feat(coeur): proxy /atelier-images-video-app/* isolé par personne (motif S187)"
```

---

### Task 9: Câblage final — `.env.example` + vérification bout-en-bout

**Files:**
- Modify: `.env.example` (après la section « Brique video », avant « Muscle déporté »)

**Interfaces:** Aucune (documentation d'environnement + vérification manuelle).

- [ ] **Step 1: Ajouter la section `.env.example`**

Insérer, juste après la ligne `# RUNWAY_API_VERSION=2024-11-06` et avant la ligne
`# ── Muscle déporté / partage de puissance de calcul (brique calcul + mesh NetBird) ──` :

```
# ── Brique « atelier-images-video » (front unifié image+vidéo, port 6160) ────
# Compose images (5950), video (5970), studio (6060, synergies portrait/couverture/
# teaser/animer) et memoire (5600, galerie des créations sauvegardées) par HTTP, sans
# dupliquer leur code. Aucune capacité LLM : surface humaine uniquement (motif atelier-
# veille). Synergies Studio + galerie mémoire réutilisent STUDIO_KEY/MEMOIRE_KEY déjà
# définis plus haut (secrets de service partagés, cette brique ne stocke rien elle-même).
# Clé que LE CŒUR SEUL présente (X-API-Key) à cette brique pour les routes /studio/* et
# /galerie/* — sans elle, un appel direct sur le port 6160 pourrait forger X-User-Id et
# emprunter STUDIO_KEY/MEMOIRE_KEY pour usurper une autre personne. VIDE en mono-
# utilisateur (mode ouvert, dev). Génère une clé : `openssl rand -hex 32`.
ATELIER_IMAGES_VIDEO_KEY=
```

- [ ] **Step 2: Vérifier que le fichier reste syntaxiquement cohérent**

Run: `grep -c "^ATELIER_IMAGES_VIDEO_KEY=" .env.example`
Expected: `1`

- [ ] **Step 3: Build et démarrage local de la brique (vérification bout-en-bout)**

Run:
```bash
cd briques/atelier-images-video
docker compose up -d --build
sleep 3
curl -sf http://localhost:6160/sante
```
Expected: `{"statut":"ok"}` — et `docker ps` montre `workplace_atelier_images_video`
en état `healthy` après le `start_period`.

- [ ] **Step 4: Vérifier que le front est servi**

Run: `curl -sf http://localhost:6160/atelier | grep -o '<title>[^<]*</title>'`
Expected: `<title>Atelier Images & Vidéo</title>`

- [ ] **Step 5: Lancer toute la suite de tests du repo touché par ce plan**

Run:
```bash
(cd briques/atelier-images-video && python -m pytest -q) && \
(cd core && python -m pytest -q)
```
Expected: tous les tests passent, `0 failed`.

- [ ] **Step 6: Arrêter le conteneur de vérification**

Run: `cd briques/atelier-images-video && docker compose down`

- [ ] **Step 7: Commit**

```bash
git add .env.example
git commit -m "docs(env): section ATELIER_IMAGES_VIDEO_KEY pour la nouvelle brique"
```

---

## Self-Review

**Couverture du design** :
- Front unique 4 onglets (image libre, vidéo libre, synergies, galerie) → Task 7.
- Génération libre images/video sans auth → Task 2.
- Synergies Studio (portrait/couverture/teaser/animer) via proxy vers les endpoints déjà
  étatés du Studio → Task 4.
- Sélecteur de fournisseur listant tout, `gateway` inclus → Task 2 (`/fournisseurs` relayé
  tel quel) + Task 7 (front affiche `configure` sans filtrer).
- Galerie via la brique mémoire, sauvegarde explicite (pas d'auto-save) → Task 5 + Task 7
  (bouton « Ajouter à la galerie », jamais appelé automatiquement après génération).
- Presets `localStorage` → Task 7.
- Sécurité : proxy Cœur, seule la session fixe l'identité → Task 8 ; ET la brique
  elle-même exige un secret avant de faire confiance à X-User-Id → Task 3 (précision de
  sécurité par rapport au design, documentée dans les Global Constraints).
- Port 6160, `capacites: []`, `depends_on` → Task 1 (manifest).
- Pas de multi-variantes, pas d'auto-save, pas d'éditeur d'image → respecté (aucune tâche
  ne les introduit).

**Cohérence des types/noms** : `_relayer` (Task 1) utilisé identiquement dans les Tasks 2,
4, 5 avec la même signature `(methode, url, entetes, marque, json_body=None,
params=None)`. `_identite_service`/`_entetes_studio`/`_entetes_memoire` (Task 3) réutilisés
tels quels dans les Tasks 4 et 5, sans renommage. `IMAGES_URL`/`VIDEO_URL`/`STUDIO_URL`/
`MEMOIRE_URL` définis une seule fois (Task 1), jamais redéfinis. `ATELIER_IV_API_BASE`
utilisé de façon identique dans `front.html` (Task 7, lecture) et
`atelier_images_video_proxy.py` (Task 8, écriture) — même nom des deux côtés.

**Aucun `TBD`/placeholder** : chaque step contient du code complet, exécutable tel quel.
