# S127 — Brique PeerTube (hébergement vidéo souverain)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Déployer PeerTube comme brique Workplace (port 6100) — hébergement vidéo souverain avec upload, live RTMP et embed, auto-découvert par le Cœur via manifest.

**Architecture:** PeerTube tourne en Docker avec ses propres services (postgres + redis + nginx interne). Un wrapper FastAPI léger (port 6100) adapte l'API PeerTube en capacités Workplace (manifest → outils LLM). Le Cœur découvre la brique au démarrage et peut lister/uploader/rechercher des vidéos via l'assistant.

**Tech Stack:** PeerTube v7 (Docker officiel), FastAPI, httpx, pytest. Pas de dépendance aux autres briques pour S127 — standalone.

## Global Constraints

- Port brique wrapper: **6100** (PeerTube interne: 9000, RTMP: 1935)
- Pattern brique: FastAPI + `manifest.json` + `/sante` + CORS_ORIGINS + API_KEYS — identique à `briques/vision/`
- PeerTube hostname HP: `192.168.1.89` (LAN). Verrouillé à l'init — ne pas changer après.
- Tests offline uniquement : mocker l'API PeerTube avec `respx` (jamais appeler PeerTube réel en test)
- Commits fréquents, une tâche = un commit
- Nommer les images Docker : `workplace/peertube-wrapper:0.1.0`
- Langue code : français pour les noms de variables/commentaires (cohérence codebase)

---

## Fichiers créés / modifiés

```
briques/peertube/
├── docker-compose.yml          # PeerTube + postgres + redis (services internes)
├── docker-compose.override.yml # extra_hosts host.docker.internal sur HP Linux
├── .env.example                # PEERTUBE_SECRET, PEERTUBE_ADMIN_EMAIL, etc.
├── Dockerfile                  # wrapper Python (FROM python:3.11-slim)
├── requirements.txt            # fastapi uvicorn httpx
├── main.py                     # FastAPI wrapper (port 6100)
├── peertube_client.py          # client REST PeerTube (auth OAuth2 + upload + search)
├── manifest.json               # capacités auto-découvertes par le Cœur
├── test_peertube.py            # tests offline (respx mock)
├── conftest.py                 # fixtures pytest
└── config/
    └── production.yaml         # config PeerTube (hostname, email, secret…)

core/urls_ui.py                 # ajouter PEERTUBE_UI_URL
core/docker-compose.yml         # ajouter PEERTUBE_UI_URL env var
```

---

## Tâche 1 — Docker PeerTube + config

**Fichiers :**
- Créer : `briques/peertube/docker-compose.yml`
- Créer : `briques/peertube/docker-compose.override.yml`
- Créer : `briques/peertube/config/production.yaml`
- Créer : `briques/peertube/.env.example`

**Interfaces :**
- Produit : PeerTube accessible sur `http://host.docker.internal:9000` depuis les autres conteneurs Docker

- [ ] **Étape 1 : Créer la config PeerTube**

```yaml
# briques/peertube/config/production.yaml
listen:
  hostname: '0.0.0.0'
  port: 9000

webserver:
  https: false
  hostname: '192.168.1.89'
  port: 9000

database:
  hostname: 'peertube-db'
  port: 5432
  suffix: '_prod'
  username: 'peertube'
  password: '${POSTGRES_PASSWORD}'
  pool:
    max: 5

redis:
  hostname: 'peertube-redis'

smtp:
  hostname: null
  port: 465
  username: null
  password: null
  tls: true
  disable_starttls: false
  ca_file: null
  from_address: 'admin@peertube.example.com'

email:
  body:
    signature: 'Workplace PeerTube'
  subject:
    prefix: '[Workplace]'

storage:
  tmp: '/data/tmp/'
  tmp_persistent: '/data/tmp-persistent/'
  bin: '/data/bin/'
  avatars: '/data/avatars/'
  web_videos: '/data/web-videos/'
  streaming_playlists: '/data/streaming-playlists/'
  redundancy: '/data/redundancy/'
  logs: '/data/logs/'
  previews: '/data/previews/'
  thumbnails: '/data/thumbnails/'
  torrents: '/data/torrents/'
  captions: '/data/captions/'
  cache: '/data/cache/'
  plugins: '/data/plugins/'
  well_known: '/data/well-known/'
  client_overrides: '/data/client-overrides/'

log:
  level: 'info'

live:
  enabled: true
  rtmp:
    enabled: true
    use_proxy: false
    port: 1935
```

- [ ] **Étape 2 : Créer docker-compose.yml**

```yaml
# briques/peertube/docker-compose.yml
services:
  peertube:
    image: chocobozzz/peertube:production-bookworm
    container_name: workplace_peertube
    ports:
      - "9000:9000"
      - "1935:1935"
    volumes:
      - peertube_data:/data
      - ./config/production.yaml:/config/production.yaml:ro
    environment:
      - PEERTUBE_DB_USERNAME=peertube
      - PEERTUBE_DB_PASSWORD=${POSTGRES_PASSWORD:-peertube_secret}
      - PEERTUBE_DB_HOSTNAME=peertube-db
      - PEERTUBE_REDIS_HOSTNAME=peertube-redis
      - PEERTUBE_WEBSERVER_HOSTNAME=192.168.1.89
      - PEERTUBE_WEBSERVER_PORT=9000
      - PEERTUBE_WEBSERVER_HTTPS=false
      - PEERTUBE_SECRET=${PEERTUBE_SECRET:-changeme_en_production}
      - PEERTUBE_SMTP_HOSTNAME=
      - PT_INITIAL_ROOT_PASSWORD=${PEERTUBE_ADMIN_PASSWORD:-workplace2026}
    depends_on:
      peertube-db:
        condition: service_healthy
      peertube-redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fs", "http://localhost:9000/api/v1/ping"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

  peertube-wrapper:
    build: .
    image: workplace/peertube-wrapper:0.1.0
    container_name: workplace_peertube_wrapper
    ports:
      - "6100:6100"
    environment:
      - PORT=6100
      - PEERTUBE_URL=http://peertube:9000
      - PEERTUBE_ADMIN_USER=${PEERTUBE_ADMIN_USER:-root}
      - PEERTUBE_ADMIN_PASSWORD=${PEERTUBE_ADMIN_PASSWORD:-workplace2026}
      - CORS_ORIGINS=${CORS_ORIGINS:-*}
      - API_KEYS=${API_KEYS:-}
    depends_on:
      peertube:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6100/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  peertube-db:
    image: postgres:13-alpine
    container_name: peertube-db
    environment:
      - POSTGRES_USER=peertube
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-peertube_secret}
      - POSTGRES_DB=peertube_prod
    volumes:
      - peertube_db:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U peertube"]
      interval: 10s
      timeout: 5s
      retries: 5

  peertube-redis:
    image: redis:7-alpine
    container_name: peertube-redis
    volumes:
      - peertube_redis:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  peertube_data:
  peertube_db:
  peertube_redis:
```

- [ ] **Étape 3 : Créer docker-compose.override.yml (Linux HP)**

```yaml
# briques/peertube/docker-compose.override.yml
services:
  peertube-wrapper:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

- [ ] **Étape 4 : Créer .env.example**

```bash
# briques/peertube/.env.example
PEERTUBE_SECRET=changeme_en_production_32_chars_min
PEERTUBE_ADMIN_USER=root
PEERTUBE_ADMIN_PASSWORD=workplace2026
POSTGRES_PASSWORD=peertube_secret
```

- [ ] **Étape 5 : Commit**

```bash
git add briques/peertube/docker-compose.yml briques/peertube/docker-compose.override.yml \
        briques/peertube/config/production.yaml briques/peertube/.env.example
git commit -m "feat S127 : docker-compose PeerTube (instance + wrapper + db + redis)"
```

---

## Tâche 2 — Client REST PeerTube

**Fichiers :**
- Créer : `briques/peertube/peertube_client.py`
- Créer : `briques/peertube/requirements.txt`

**Interfaces :**
- Produit :
  - `PeerTubeClient(url, user, password)` → classe
  - `async client.token() -> str` → Bearer token OAuth2
  - `async client.lister_videos(search, count) -> list[dict]` → `[{uuid, name, description, thumbnailPath, duration, views}]`
  - `async client.uploader_video(nom, description, fichier_bytes, nom_fichier) -> dict` → `{uuid, name, url}`
  - `async client.info_video(uuid) -> dict` → `{uuid, name, description, embedPath}`
  - `async client.creer_live(nom, description) -> dict` → `{uuid, rtmpUrl, streamKey}`

- [ ] **Étape 1 : requirements.txt**

```
# briques/peertube/requirements.txt
fastapi==0.115.0
uvicorn==0.30.6
httpx==0.27.2
python-multipart==0.0.12
respx==0.21.1
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Étape 2 : Écrire les tests du client (offline)**

```python
# briques/peertube/test_peertube.py  (section client)
import pytest
import respx
import httpx
from peertube_client import PeerTubeClient

PEERTUBE_URL = "http://peertube-test:9000"

@pytest.fixture
def client():
    return PeerTubeClient(PEERTUBE_URL, "root", "motdepasse")

@respx.mock
@pytest.mark.asyncio
async def test_lister_videos(client):
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.get(f"{PEERTUBE_URL}/api/v1/videos").mock(return_value=httpx.Response(
        200, json={"total": 1, "data": [{"uuid": "abc-123", "name": "Test", "description": "desc",
                                          "thumbnailPath": "/thumb.jpg", "duration": 60, "views": 5}]}
    ))
    videos = await client.lister_videos()
    assert len(videos) == 1
    assert videos[0]["uuid"] == "abc-123"

@respx.mock
@pytest.mark.asyncio
async def test_info_video(client):
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.get(f"{PEERTUBE_URL}/api/v1/videos/abc-123").mock(return_value=httpx.Response(
        200, json={"uuid": "abc-123", "name": "Test", "description": "desc",
                   "embedPath": "/videos/embed/abc-123"}
    ))
    info = await client.info_video("abc-123")
    assert info["embedPath"] == "/videos/embed/abc-123"

@respx.mock
@pytest.mark.asyncio
async def test_uploader_video(client):
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/videos/upload").mock(return_value=httpx.Response(
        200, json={"video": {"uuid": "new-uuid", "name": "Ma vidéo",
                              "url": "http://192.168.1.89:9000/videos/watch/new-uuid"}}
    ))
    result = await client.uploader_video("Ma vidéo", "desc", b"bytes_video", "video.mp4")
    assert result["uuid"] == "new-uuid"

@respx.mock
@pytest.mark.asyncio
async def test_creer_live(client):
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/videos/live").mock(return_value=httpx.Response(
        200, json={"video": {"uuid": "live-uuid"}}
    ))
    respx.get(f"{PEERTUBE_URL}/api/v1/videos/live/live-uuid").mock(return_value=httpx.Response(
        200, json={"rtmpUrl": "rtmp://192.168.1.89:1935/live", "streamKey": "key123"}
    ))
    live = await client.creer_live("Mon live", "Session de travail")
    assert live["rtmpUrl"] == "rtmp://192.168.1.89:1935/live"
    assert live["streamKey"] == "key123"
```

- [ ] **Étape 3 : Vérifier que les tests échouent**

```bash
cd briques/peertube && python -m pytest test_peertube.py -k "client" -v
# Attendu : ImportError (peertube_client pas encore créé)
```

- [ ] **Étape 4 : Implémenter peertube_client.py**

```python
# briques/peertube/peertube_client.py
"""Client REST pour l'API PeerTube v1 — auth OAuth2 + cache de token."""
import httpx
from typing import Optional


class PeerTubeClient:
    def __init__(self, url: str, user: str, password: str):
        self._url = url.rstrip("/")
        self._user = user
        self._password = password
        self._token: Optional[str] = None

    async def token(self) -> str:
        if self._token:
            return self._token
        # Récupère le client_id/client_secret public de l'instance
        async with httpx.AsyncClient() as c:
            oauth = (await c.get(f"{self._url}/api/v1/oauth-clients/local")).json()
            resp = await c.post(f"{self._url}/api/v1/users/token", data={
                "client_id": oauth["client_id"],
                "client_secret": oauth["client_secret"],
                "grant_type": "password",
                "username": self._user,
                "password": self._password,
                "response_type": "code",
            })
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
        return self._token

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {await self.token()}"}

    async def lister_videos(self, search: str = "", count: int = 20) -> list[dict]:
        params = {"count": count, "sort": "-publishedAt"}
        if search:
            params["search"] = search
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._url}/api/v1/videos",
                               params=params, headers=await self._headers())
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def info_video(self, uuid: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._url}/api/v1/videos/{uuid}",
                               headers=await self._headers())
            resp.raise_for_status()
            return resp.json()

    async def uploader_video(self, nom: str, description: str,
                              fichier_bytes: bytes, nom_fichier: str) -> dict:
        async with httpx.AsyncClient(timeout=300) as c:
            resp = await c.post(
                f"{self._url}/api/v1/videos/upload",
                headers=await self._headers(),
                data={"name": nom, "description": description, "channelId": 1},
                files={"videofile": (nom_fichier, fichier_bytes, "video/mp4")},
            )
            resp.raise_for_status()
            return resp.json()["video"]

    async def creer_live(self, nom: str, description: str = "") -> dict:
        async with httpx.AsyncClient() as c:
            # Crée le live
            resp = await c.post(
                f"{self._url}/api/v1/videos/live",
                headers=await self._headers(),
                json={"name": nom, "description": description,
                      "channelId": 1, "saveReplay": True},
            )
            resp.raise_for_status()
            uuid = resp.json()["video"]["uuid"]
            # Récupère les infos RTMP
            live_resp = await c.get(f"{self._url}/api/v1/videos/live/{uuid}",
                                    headers=await self._headers())
            live_resp.raise_for_status()
            live_info = live_resp.json()
            return {"uuid": uuid, "rtmpUrl": live_info["rtmpUrl"],
                    "streamKey": live_info["streamKey"]}
```

- [ ] **Étape 5 : Vérifier que les tests passent**

```bash
cd briques/peertube && python -m pytest test_peertube.py -k "client" -v
# Attendu : 4 PASSED
```

- [ ] **Étape 6 : Commit**

```bash
git add briques/peertube/peertube_client.py briques/peertube/requirements.txt \
        briques/peertube/test_peertube.py
git commit -m "feat S127 : client REST PeerTube (OAuth2 + lister/upload/live) + tests"
```

---

## Tâche 3 — Wrapper FastAPI (brique port 6100)

**Fichiers :**
- Créer : `briques/peertube/main.py`
- Créer : `briques/peertube/Dockerfile`
- Créer : `briques/peertube/conftest.py`

**Interfaces :**
- Consomme : `PeerTubeClient` de `peertube_client.py`
- Produit :
  - `GET /sante` → `{"statut": "ok", "peertube": "joignable"|"injoignable"}`
  - `GET /videos` → `[{uuid, name, description, thumbnailUrl, duration, embedUrl}]`
  - `GET /videos/{uuid}` → `{uuid, name, description, embedUrl, watchUrl}`
  - `POST /videos/rechercher` → body `{query: str}` → liste vidéos filtrées
  - `POST /videos/upload` → multipart `{nom, description, fichier}` → `{uuid, watchUrl}`
  - `POST /live` → body `{nom, description}` → `{uuid, rtmpUrl, streamKey}`

- [ ] **Étape 1 : Ajouter les tests API dans test_peertube.py**

```python
# Ajouter à la suite de test_peertube.py (section API)
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import io

# Importer l'app après avoir créé main.py
# from main import app

def _mock_client(videos=None, video_info=None, upload_result=None, live_result=None):
    m = AsyncMock()
    m.lister_videos.return_value = videos or []
    m.info_video.return_value = video_info or {}
    m.uploader_video.return_value = upload_result or {"uuid": "u1", "url": "http://x/watch/u1"}
    m.creer_live.return_value = live_result or {"uuid": "l1", "rtmpUrl": "rtmp://x/live", "streamKey": "k"}
    return m

def test_sante_ok():
    from main import app, _peertube
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.get("/sante")
        assert resp.status_code == 200
        assert resp.json()["statut"] == "ok"

def test_lister_videos_vide():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.get("/videos")
        assert resp.status_code == 200
        assert resp.json() == []

def test_lister_videos_avec_resultats():
    from main import app
    video = {"uuid": "abc", "name": "Test", "description": "d",
             "thumbnailPath": "/thumb.jpg", "duration": 60, "views": 3,
             "embedPath": "/videos/embed/abc"}
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[video])
        client = TestClient(app)
        resp = client.get("/videos")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["uuid"] == "abc"
        assert "embedUrl" in data[0]

def test_rechercher_videos():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.post("/videos/rechercher", json={"query": "test"})
        assert resp.status_code == 200
        mock_pt.lister_videos.assert_called_once_with(search="test")

def test_upload_video():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.uploader_video = AsyncMock(
            return_value={"uuid": "new-u", "url": "http://x/watch/new-u"}
        )
        client = TestClient(app)
        fichier = io.BytesIO(b"fake_video_bytes")
        resp = client.post("/videos/upload", data={"nom": "Ma vidéo", "description": "test"},
                           files={"fichier": ("video.mp4", fichier, "video/mp4")})
        assert resp.status_code == 200
        assert resp.json()["uuid"] == "new-u"

def test_creer_live():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.creer_live = AsyncMock(
            return_value={"uuid": "live-1", "rtmpUrl": "rtmp://192.168.1.89:1935/live", "streamKey": "sk"}
        )
        client = TestClient(app)
        resp = client.post("/live", json={"nom": "Session", "description": "live"})
        assert resp.status_code == 200
        assert resp.json()["rtmpUrl"] == "rtmp://192.168.1.89:1935/live"
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd briques/peertube && python -m pytest test_peertube.py -k "api or sante or lister or upload or live or rechercher" -v
# Attendu : ImportError (main pas encore créé)
```

- [ ] **Étape 3 : Implémenter main.py**

```python
# briques/peertube/main.py
"""Brique « peertube » — hébergement vidéo souverain (wrapper PeerTube v7).

Expose PeerTube en capacités Workplace :
  GET  /videos           : liste les vidéos archivées
  GET  /videos/{uuid}    : détail + URL embed
  POST /videos/rechercher: recherche textuelle
  POST /videos/upload    : upload multipart (ACTION)
  POST /live             : créer un live RTMP (ACTION)
  GET  /sante            : santé de la brique + joignabilité PeerTube
"""
import os
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from peertube_client import PeerTubeClient

app = FastAPI(title="PeerTube — hébergement vidéo souverain", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
PEERTUBE_URL = os.getenv("PEERTUBE_URL", "http://localhost:9000")
_peertube = PeerTubeClient(
    PEERTUBE_URL,
    os.getenv("PEERTUBE_ADMIN_USER", "root"),
    os.getenv("PEERTUBE_ADMIN_PASSWORD", "workplace2026"),
)


def _cle_api(x_api_key: Optional[str] = Header(None)) -> str:
    if not API_KEYS:
        return ""
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Clé API invalide")
    return x_api_key


def _formater_video(v: dict) -> dict:
    return {
        "uuid": v.get("uuid"),
        "name": v.get("name"),
        "description": v.get("description", ""),
        "duration": v.get("duration", 0),
        "views": v.get("views", 0),
        "thumbnailUrl": f"{PEERTUBE_URL}{v.get('thumbnailPath', '')}",
        "embedUrl": f"{PEERTUBE_URL}{v.get('embedPath', '')}",
        "watchUrl": f"{PEERTUBE_URL}/videos/watch/{v.get('uuid')}",
    }


@app.get("/sante")
async def sante():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(f"{PEERTUBE_URL}/api/v1/ping")
            peertube_ok = resp.status_code == 200
    except Exception:
        peertube_ok = False
    return {"statut": "ok", "brique": "peertube", "version": "0.1.0",
            "peertube": "joignable" if peertube_ok else "injoignable"}


@app.get("/videos")
async def lister_videos(_: str = Depends(_cle_api)):
    videos = await _peertube.lister_videos()
    return [_formater_video(v) for v in videos]


@app.get("/videos/{uuid}")
async def detail_video(uuid: str, _: str = Depends(_cle_api)):
    try:
        v = await _peertube.info_video(uuid)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Vidéo introuvable")
        raise HTTPException(status_code=502, detail="Erreur PeerTube")
    return _formater_video(v)


class RechercheBody(BaseModel):
    query: str


@app.post("/videos/rechercher")
async def rechercher_videos(body: RechercheBody, _: str = Depends(_cle_api)):
    videos = await _peertube.lister_videos(search=body.query)
    return [_formater_video(v) for v in videos]


@app.post("/videos/upload")
async def upload_video(
    nom: str = Form(...),
    description: str = Form(""),
    fichier: UploadFile = File(...),
    _: str = Depends(_cle_api),
):
    contenu = await fichier.read()
    try:
        result = await _peertube.uploader_video(nom, description, contenu, fichier.filename or "video.mp4")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Échec upload PeerTube")
    return {
        "uuid": result["uuid"],
        "watchUrl": result.get("url") or f"{PEERTUBE_URL}/videos/watch/{result['uuid']}",
    }


class LiveBody(BaseModel):
    nom: str
    description: str = ""


@app.post("/live")
async def creer_live(body: LiveBody, _: str = Depends(_cle_api)):
    try:
        live = await _peertube.creer_live(body.nom, body.description)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Échec création live PeerTube")
    return live


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "6100")))
```

- [ ] **Étape 4 : conftest.py**

```python
# briques/peertube/conftest.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
```

- [ ] **Étape 5 : Dockerfile**

```dockerfile
# briques/peertube/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

- [ ] **Étape 6 : Vérifier que les tests passent**

```bash
cd briques/peertube && pip install -r requirements.txt
python -m pytest test_peertube.py -v
# Attendu : tous PASSED
```

- [ ] **Étape 7 : Commit**

```bash
git add briques/peertube/main.py briques/peertube/Dockerfile briques/peertube/conftest.py
git commit -m "feat S127 : wrapper FastAPI brique peertube (port 6100) + tests API"
```

---

## Tâche 4 — Manifest + intégration Cœur

**Fichiers :**
- Créer : `briques/peertube/manifest.json`
- Modifier : `core/urls_ui.py` (ligne ~14)
- Modifier : `core/docker-compose.yml` (section environment)

**Interfaces :**
- Consomme : endpoints `/videos`, `/videos/rechercher`, `/videos/upload`, `/live` de la brique
- Produit : capacités `peertube_lister`, `peertube_rechercher`, `peertube_uploader`, `peertube_live` auto-découvertes par le Cœur

- [ ] **Étape 1 : Créer manifest.json**

```json
{
  "nom": "peertube",
  "version": "0.1.0",
  "description": "Hébergement vidéo souverain (PeerTube) : archive, recherche, upload et live RTMP. Aucune dépendance cloud — tout reste sur le HP. Synergie avec le studio (upload post-session) et la mémoire (nœuds vidéo).",
  "role": "media",
  "couche": "backend",
  "statut": "actif",
  "chemin_source": "briques/peertube",
  "port": 6100,
  "url_sante": "http://host.docker.internal:6100/sante",
  "depends_on": [],
  "offre": ["hebergement_video", "live_rtmp", "recherche_video", "upload_video"],
  "besoin": [],
  "capacites": [
    {
      "nom": "peertube_lister",
      "description": "Liste les vidéos archivées sur la vidéothèque PeerTube interne (titre, durée, URL embed). Lecture seule. Utile pour retrouver une session enregistrée.",
      "methode": "GET",
      "chemin": "/videos",
      "params": {},
      "action": false,
      "niveau": 0
    },
    {
      "nom": "peertube_rechercher",
      "description": "Recherche des vidéos archivées par mot-clé dans la vidéothèque PeerTube. Lecture seule.",
      "methode": "POST",
      "chemin": "/videos/rechercher",
      "params": {
        "query": {"type": "string", "description": "Mots-clés de recherche.", "requis": true}
      },
      "action": false,
      "niveau": 0
    },
    {
      "nom": "peertube_uploader",
      "description": "Upload une vidéo (fichier MP4/MKV/WebM) dans la vidéothèque PeerTube. ACTION — ne pas déclencher sans confirmation. Retourne l'URL de visionnage.",
      "methode": "POST",
      "chemin": "/videos/upload",
      "params": {
        "nom": {"type": "string", "description": "Titre de la vidéo.", "requis": true},
        "description": {"type": "string", "description": "Description de la vidéo (optionnel)."},
        "fichier": {"type": "file", "description": "Fichier vidéo (multipart).", "requis": true}
      },
      "action": true,
      "niveau": 1
    },
    {
      "nom": "peertube_live",
      "description": "Crée un live RTMP dans PeerTube. Retourne l'URL RTMP et la clé de stream à configurer dans OBS ou le studio. ACTION.",
      "methode": "POST",
      "chemin": "/live",
      "params": {
        "nom": {"type": "string", "description": "Titre du live.", "requis": true},
        "description": {"type": "string", "description": "Description du live (optionnel)."}
      },
      "action": true,
      "niveau": 1
    }
  ],
  "taches": []
}
```

- [ ] **Étape 2 : Ajouter PEERTUBE_UI_URL dans core/urls_ui.py**

Ouvrir `core/urls_ui.py` et ajouter après la dernière ligne de variables :
```python
PEERTUBE_UI_URL = os.environ.get("PEERTUBE_UI_URL", "http://localhost:9000")
```

- [ ] **Étape 3 : Ajouter PEERTUBE_UI_URL dans core/docker-compose.yml**

Dans `core/docker-compose.yml`, section `environment`, ajouter après `GENERATEUR_URL_PUBLIQUE` :
```yaml
      - PEERTUBE_UI_URL=http://localhost:9000
```

Sur le HP, le `docker-compose.override.yml` du core (déjà existant) sera mis à jour à la main pour pointer vers `192.168.1.89:9000`.

- [ ] **Étape 4 : Test manifest parseable**

```bash
cd briques/peertube && python -c "
import json
m = json.load(open('manifest.json'))
assert m['port'] == 6100
assert len(m['capacites']) == 4
print('manifest OK — ', len(m['capacites']), 'capacités')
"
# Attendu : manifest OK — 4 capacités
```

- [ ] **Étape 5 : Commit**

```bash
git add briques/peertube/manifest.json core/urls_ui.py core/docker-compose.yml
git commit -m "feat S127 : manifest peertube (4 capacités) + PEERTUBE_UI_URL au Cœur"
```

---

## Tâche 5 — Déploiement HP + preuve LIVE

> Cette tâche s'exécute en SSH sur le HP. Pas de code à écrire — uniquement des commandes.

- [ ] **Étape 1 : git pull sur le HP**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'cd ~/workplace && git pull --ff-only'
```

- [ ] **Étape 2 : Créer le .env local PeerTube sur le HP**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'cat > ~/workplace/briques/peertube/.env << EOF
PEERTUBE_SECRET=$(openssl rand -hex 32)
PEERTUBE_ADMIN_USER=root
PEERTUBE_ADMIN_PASSWORD=workplace2026
POSTGRES_PASSWORD=peertube_secret
EOF'
```

- [ ] **Étape 3 : Mettre à jour le docker-compose.override.yml du core (HP)**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'grep -q PEERTUBE_UI_URL ~/workplace/core/docker-compose.override.yml || \
  sed -i "/GATEWAY_UI_URL/a\\      - PEERTUBE_UI_URL=http://192.168.1.89:9000" \
  ~/workplace/core/docker-compose.override.yml'
```

- [ ] **Étape 4 : Builder et démarrer la brique PeerTube**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
cd ~/workplace/briques/peertube
docker compose up -d --build
echo "=== attente PeerTube (60s) ==="
sleep 60
docker compose ps
'
```

- [ ] **Étape 5 : Preuves LIVE**

```bash
# Ping PeerTube
ssh -o BatchMode=yes debian@192.168.1.89 'curl -s http://localhost:9000/api/v1/ping'
# Attendu : {"express":"1","ping":"pong"}

# Sante wrapper
ssh -o BatchMode=yes debian@192.168.1.89 'curl -s http://localhost:6100/sante | python3 -m json.tool'
# Attendu : {"statut": "ok", "peertube": "joignable"}

# Liste vidéos (vide au départ)
ssh -o BatchMode=yes debian@192.168.1.89 'curl -s http://localhost:6100/videos'
# Attendu : []
```

- [ ] **Étape 6 : Recreate le Cœur pour découvrir la nouvelle brique**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
cd ~/workplace/core && docker compose up -d
sleep 5
curl -s localhost:5100/sante-globale | python3 -c "
import json,sys
d=json.load(sys.stdin)[\"briques\"]
print(\"peertube:\", d.get(\"peertube\", {}).get(\"statut\", \"ABSENT\"))
"'
# Attendu : peertube: ok
```

---

## Sprints suivants (hors périmètre S127)

**S128 — Upload studio → PeerTube**
- Endpoint `POST /archive` dans la brique studio 5920 qui pousse la vidéo vers `peertube:6100/videos/upload`
- Webhook PeerTube `video:published` → notif 🔔 Cœur

**S129 — Mémoire multimédia**
- Nœuds `type: video` dans le graphe mémoire 5600 (`uuid`, `watchUrl`, `embedUrl`)
- Lier les fiches personnages et événements agenda à leurs vidéos PeerTube
- `vision` 5960 extrait les sous-titres depuis MP4 archivé
