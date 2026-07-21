# Atelier Veille — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Créer la brique `atelier-veille` (port 6130) : un front unique qui donne enfin une
interface humaine à `veille-info` (aujourd'hui 100% API) et réutilise la carte de `geo` par
iframe, apparaissant comme une tuile du hub « Atelier » du dashboard du Cœur — sur le modèle
exact de Studio.

**Architecture:** Une brique FastAPI quasi uniquement front (`front.html` servi sous `/` et
`/atelier`), qui compose `geo` (6110, iframe directe navigateur→brique) et `veille-info`
(6120, proxy HTTP serveur→serveur) sans dupliquer une ligne de leur code ni stocker le
moindre état côté atelier. Câblée au dashboard du Cœur via `core/urls_ui.py` +
`core/routers/dashboard.py`, sur le motif déjà utilisé par Studio/Personnages/Synopsis/Voix/
Mémoire (`ouvrirCreation` / tuile de la grille Atelier).

**Tech Stack:** FastAPI, httpx (async), Docker, HTML/CSS/JS vanilla (`shared/static/workplace.css`
comme design system, motif Studio).

## Global Constraints

- Port de la brique : **6130** (prochain port libre après `veille-info` à 6120).
- `couche: "backend"` dans le manifest (service réel avec port + `/sante`, pas un frontend
  statique) — le smoke test `tests/test_briques_smoke.py` exige alors `port` et `url_sante`
  encodant ce port.
- Aucune modification du code de `briques/geo/` ni de `briques/veille-info/`.
- Aucune capacité (`capacites: []`) : cette brique est une surface humaine, pas un outil LLM
  — pas de câblage `BRIQUES_PAR_PERSONNE`/`outils_communs.py` (ce mécanisme sert uniquement
  les briques appelées PAR le Cœur au nom de l'assistant ; l'atelier n'est jamais appelé
  ainsi). L'identité (X-User-Id/X-API-Key) est relayée en **pass-through pur** : l'atelier
  transmet à `veille-info` les en-têtes que SON PROPRE appelant (le navigateur) lui a déjà
  envoyés, sans les fabriquer lui-même.
- `POST /digest/executer` sur `veille-info` est gardé par `Authorization: Bearer
  VEILLE_INFO_KEY` (jeton PARTAGÉ, motif horloge — PAS `tenant_actuel`) et traite TOUTES les
  personnes du foyer en un seul appel. L'atelier présente ce jeton depuis SA PROPRE variable
  d'env (`VEILLE_INFO_KEY`, héritée du `.env` racine), jamais depuis un en-tête du
  navigateur — c'est un secret de service, pas une identité de personne.
- Dépendances Python épinglées, alignées sur `briques/veille-info/requirements.txt` (déjà
  aligné sur `constraints-workplace.txt`) : `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`,
  `httpx==0.28.1`.
- `extra_hosts: host.docker.internal:host-gateway` dans le `docker-compose.yml` dès la
  version 1 (piège fleet-wide déjà documenté — ne pas le réintroduire).
- Motif de mock HTTP dans les tests : `monkeypatch.setattr(main.httpx, "AsyncClient",
  FauxClient)` avec une classe `FauxClient` exposant `__aenter__`/`__aexit__`/`get`/`post`/
  `delete` async (motif exact `briques/studio/test_composition.py`), **pas** de nouvelle
  dépendance de mock (pas de `respx`).

---

### Task 1: Squelette de la brique + manifest + smoke test vert

**Files:**
- Create: `briques/atelier-veille/manifest.json`
- Create: `briques/atelier-veille/Dockerfile`
- Create: `briques/atelier-veille/docker-compose.yml`
- Create: `briques/atelier-veille/requirements.txt`
- Create: `briques/atelier-veille/main.py`
- Test: `tests/test_briques_smoke.py` (déjà existant, auto-découvre `briques/*/manifest.json`)

**Interfaces:**
- Produces: `app = FastAPI(...)` dans `main.py`, endpoint `GET /sante` → `{"statut": "ok"}`
  (consommé par le healthcheck Docker et par tous les tasks suivants).

- [ ] **Step 1: Écrire le manifest**

```json
{
  "nom": "atelier-veille",
  "famille": "veille",
  "version": "0.1.0",
  "description": "Atelier Veille : front unique de la famille veille — réunit la carte de geo (iframe) et les sources RSS/digests/audio de veille-info (proxy HTTP), sans dupliquer leur code. Aucune capacité LLM : surface humaine, pas un outil de l'assistant.",
  "role": "atelier-veille",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/atelier-veille",
  "port": 6130,
  "url_sante": "http://host.docker.internal:6130/sante",
  "url_ui": "http://localhost:6130/atelier",
  "vue_dashboard": "atelier-veille",
  "depends_on": [],
  "offre": ["front_atelier_veille"],
  "capacites": []
}
```

- [ ] **Step 2: Écrire `requirements.txt`**

```
# Brique atelier-veille — front + composition HTTP. Dépendances minces et épinglées.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

- [ ] **Step 3: Écrire le `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6130"]
```

- [ ] **Step 4: Écrire `docker-compose.yml`**

```yaml
services:
  atelier-veille:
    build: .
    container_name: workplace_atelier_veille
    image: workplace/atelier-veille:0.1.0   # tag épinglé (pas de :latest flottant)
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6130:6130"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # joindre geo/veille-info sous Linux
    environment:
      - PORT=6130
      - CORS_ORIGINS=${CORS_ORIGINS:-*}
      - VEILLE_INFO_URL=http://host.docker.internal:6120
      - GEO_PUBLIC_URL=${GEO_PUBLIC_URL:-http://localhost:6110/}
      # VEILLE_INFO_KEY : ABSENTE du `environment` exprès — vient du .env racine via
      # env_file (piège « env shadow » : ne PAS la redéclarer en `=${VAR:-}`, cf.
      # fix-env-shadow-composes). VIDE aujourd'hui (mono-tenant, gate horloge no-op).
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6130/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

- [ ] **Step 5: Écrire `main.py` minimal (santé seulement)**

```python
"""Brique « atelier-veille » — front unique de la famille veille.

Quasi uniquement du front (front.html) : compose geo (carte, iframe navigateur direct) et
veille-info (sources RSS, digests, audio ; proxy HTTP serveur→serveur) sans dupliquer leur
code ni leur état. Motif de composition identique à briques/studio/main.py (appel HTTP +
repli honnête si la brique composée est injoignable). Aucune capacité LLM (`capacites: []`
dans le manifest) : cette brique est une SURFACE HUMAINE, pas un outil de l'assistant.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Atelier Veille", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}
```

- [ ] **Step 6: Vérifier le smoke test**

Run: `make smoke`
Expected: PASS (aucune collision de port, tous les champs requis présents, `url_sante`
encode bien `:6130`).

- [ ] **Step 7: Commit**

```bash
git add briques/atelier-veille/
git commit -m "feat(atelier-veille): squelette de la brique (manifest + santé)"
```

---

### Task 2: Endpoint `/config` (URL publique de la carte geo)

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Test: `briques/atelier-veille/test_main.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `GET /config` → `{"geo_url": str}` (consommé par le front en Task 6 pour
  positionner l'iframe de l'onglet Carte).

- [ ] **Step 1: Écrire le test**

```python
"""Tests API de la brique atelier-veille : config + composition (voir aussi
test_composition.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_config_renvoie_url_geo_par_defaut():
    r = client.get("/config")
    assert r.status_code == 200
    assert r.json()["geo_url"] == "http://localhost:6110/"


def test_config_respecte_la_surcharge_env(monkeypatch):
    monkeypatch.setenv("GEO_PUBLIC_URL", "https://mesh.example/geo/")
    import importlib
    importlib.reload(main)
    r = TestClient(main.app).get("/config")
    assert r.json()["geo_url"] == "https://mesh.example/geo/"
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd briques/atelier-veille && python3 -m pytest test_main.py -v`
Expected: FAIL — `404` sur `GET /config` (route inexistante).

- [ ] **Step 3: Implémenter**

Dans `briques/atelier-veille/main.py`, ajouter après le bloc CORS :

```python
GEO_PUBLIC_URL = os.getenv("GEO_PUBLIC_URL", "http://localhost:6110/")
```

Et après l'endpoint `/sante` :

```python
@app.get("/config", tags=["système"])
def config():
    """URL publique (navigateur) de la carte geo — injectée dans l'onglet Carte du front."""
    return {"geo_url": GEO_PUBLIC_URL}
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `cd briques/atelier-veille && python3 -m pytest test_main.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/test_main.py
git commit -m "feat(atelier-veille): endpoint /config (URL publique geo)"
```

---

### Task 3: Composition — sources RSS (GET/POST/DELETE proxy vers veille-info)

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Test: `briques/atelier-veille/test_composition.py`

**Interfaces:**
- Consumes: rien de nouveau (utilise `httpx` déjà dans les dépendances).
- Produces: `GET /veille/sources`, `POST /veille/sources`, `DELETE /veille/sources/{id}` —
  tous proxifient vers `veille-info`, tous renvoient `HTTPException(502, ...)` si injoignable
  (jamais un 500 nu). Consommé par le front en Task 6.

- [ ] **Step 1: Écrire le test**

```python
"""Tests — composition de veille-info (sources RSS) par l'atelier-veille.

L'atelier ne stocke rien : il relaie tel quel vers veille-info et relaie les en-têtes
d'identité reçus du navigateur (pass-through pur, jamais fabriqués)."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False):
    class FauxRep:
        status_code = status
        def json(self): return rep_json

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("GET", url, headers)
            return FauxRep()
        async def post(self, url, headers=None, json=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("POST", url, headers, json)
            return FauxRep()
        async def delete(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("DELETE", url, headers)
            return FauxRep()
    return FauxClient


def test_lister_sources_proxifie_vers_veille_info(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json([{"id": 1, "nom": "Flux A", "url": "https://a.example/rss"}]))
    r = client.get("/veille/sources", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "nom": "Flux A", "url": "https://a.example/rss"}]


def test_lister_sources_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/sources", headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/sources"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_lister_sources_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/sources")
    _, _, headers = Faux.dernier_appel
    assert headers == {}


def test_lister_sources_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/veille/sources")
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


def test_creer_source_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 2, "nom": "Flux B", "url": "https://b.example/rss"}, status=201)
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/veille/sources", json={"nom": "Flux B", "url": "https://b.example/rss"})
    assert r.status_code == 201
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"nom": "Flux B", "url": "https://b.example/rss"}


def test_supprimer_source_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({"ok": True}))
    r = client.delete("/veille/sources/2")
    assert r.status_code == 200


def test_supprimer_source_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Source introuvable."}, status=404))
    r = client.delete("/veille/sources/999")
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd briques/atelier-veille && python3 -m pytest test_composition.py -v`
Expected: FAIL — `404` sur toutes les routes `/veille/sources*` (routes inexistantes).

- [ ] **Step 3: Implémenter**

Dans `briques/atelier-veille/main.py`, ajouter les imports en tête de fichier :

```python
from typing import Optional

import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
```

Puis, après `GEO_PUBLIC_URL` :

```python
VEILLE_INFO_URL = os.getenv("VEILLE_INFO_URL", "http://host.docker.internal:6120")


def _entetes_aval(x_user_id: Optional[str], x_api_key: Optional[str]) -> dict:
    """Relaie tels quels les en-têtes d'identité reçus du navigateur vers veille-info —
    l'atelier ne fabrique jamais lui-même une identité (pass-through pur)."""
    entetes: dict = {}
    if x_user_id:
        entetes["X-User-Id"] = x_user_id
    if x_api_key:
        entetes["X-API-Key"] = x_api_key
    return entetes


class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)


@app.get("/veille/sources", tags=["veille"])
async def lister_sources(x_user_id: Optional[str] = Header(None),
                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/sources", headers=entetes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    return r.json()


@app.post("/veille/sources", tags=["veille"], status_code=201)
async def creer_source(body: CreerSource, x_user_id: Optional[str] = Header(None),
                       x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/sources", headers=entetes,
                             json=body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    return r.json()


@app.delete("/veille/sources/{source_id}", tags=["veille"])
async def supprimer_source(source_id: int, x_user_id: Optional[str] = Header(None),
                           x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{VEILLE_INFO_URL}/sources/{source_id}", headers=entetes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Source introuvable.")
    return r.json()
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `cd briques/atelier-veille && python3 -m pytest test_composition.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/test_composition.py
git commit -m "feat(atelier-veille): compose les sources RSS de veille-info (proxy)"
```

---

### Task 4: Composition — digests + génération manuelle (proxy vers veille-info)

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Modify: `briques/atelier-veille/test_composition.py`

**Interfaces:**
- Consumes: `_entetes_aval` (Task 3).
- Produces: `GET /veille/digests` (pass-through identité, comme Task 3) et
  `POST /veille/digest/executer` (secret de service `VEILLE_INFO_KEY`, PAS l'identité du
  navigateur — voir Global Constraints). Consommé par le front en Task 6.

- [ ] **Step 1: Écrire le test (ajout à `test_composition.py`)**

```python
def test_lister_digests_proxifie_vers_veille_info(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json([{"id": 1, "date": "2026-07-21", "texte_resume": "…",
                                       "nb_articles": 3, "audio_url": None, "audio_duree": None}]))
    r = client.get("/veille/digests", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json()[0]["nb_articles"] == 3


def test_executer_digest_utilise_le_jeton_de_service_pas_lidentite_navigateur(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "jeton-horloge")
    import importlib
    importlib.reload(M)
    Faux = _client_json({"utilisateurs_traites": 2, "digests_crees": 2})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = TestClient(M.app).post("/veille/digest/executer", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {"Authorization": "Bearer jeton-horloge"}


def test_executer_digest_sans_cle_configuree_envoie_bearer_vide(monkeypatch):
    monkeypatch.delenv("VEILLE_INFO_KEY", raising=False)
    import importlib
    importlib.reload(M)
    Faux = _client_json({"utilisateurs_traites": 0, "digests_crees": 0})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = TestClient(M.app).post("/veille/digest/executer")
    assert r.status_code == 200
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {"Authorization": "Bearer "}


def test_executer_digest_refuse_relaie_lerreur(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Jeton horloge invalide."}, status=401))
    r = client.post("/veille/digest/executer")
    assert r.status_code == 401
```

`_client_json` doit accepter un corps `POST` sans JSON (le proxy `/digest/executer` ne
transmet pas de body) — ajuster la signature `async def post(self, url, headers=None,
json=None, **k)` déjà écrite en Task 3 pour enregistrer `(headers, json)` même quand `json`
est `None` : elle le fait déjà (`FauxClient.dernier_appel = ("POST", url, headers, json)`),
aucun changement nécessaire au faux client.

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd briques/atelier-veille && python3 -m pytest test_composition.py -v`
Expected: FAIL — `404` sur `/veille/digests` et `/veille/digest/executer`.

- [ ] **Step 3: Implémenter**

Dans `briques/atelier-veille/main.py`, ajouter à la fin :

```python
@app.get("/veille/digests", tags=["veille"])
async def lister_digests(x_user_id: Optional[str] = Header(None),
                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/digests", headers=entetes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    return r.json()


@app.post("/veille/digest/executer", tags=["veille"])
async def executer_digest():
    """Déclenche le digest quotidien pour TOUT le foyer (motif horloge, pas un compte
    personnel) — gardé côté veille-info par un jeton de SERVICE, jamais l'identité du
    navigateur."""
    jeton = os.environ.get("VEILLE_INFO_KEY", "")
    entetes = {"Authorization": f"Bearer {jeton}"}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/digest/executer", headers=entetes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, "veille-info a refusé la génération du digest.")
    return r.json()
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `cd briques/atelier-veille && python3 -m pytest test_composition.py -v`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/test_composition.py
git commit -m "feat(atelier-veille): compose les digests + génération manuelle"
```

---

### Task 5: Servir le front (`/`, `/atelier`, `workplace.css`)

**Files:**
- Create: `briques/atelier-veille/front.html` (squelette minimal à ce stade — le contenu
  complet arrive en Task 6)
- Modify: `briques/atelier-veille/main.py`
- Modify: `outils/sync_socle.sh`
- Test: `briques/atelier-veille/test_front.py`

**Interfaces:**
- Produces: `GET /` et `GET /atelier` renvoient le même HTML ; `GET /workplace.css` sert le
  design system partagé. Consommé par Task 6 (contenu du front) et par le dashboard du Cœur
  (Task 7, iframe).

- [ ] **Step 1: Écrire le squelette `front.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atelier Veille</title>
<link rel="stylesheet" href="/workplace.css">
<style>
  :root{
    --bg:var(--wp-bg); --panel:var(--wp-surface); --panel2:var(--wp-surface-2); --line:var(--wp-border);
    --ink:var(--wp-text); --mut:var(--wp-muted); --accent:#4FA3D1; --ok:var(--wp-ok); --bad:var(--wp-err);
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:'Segoe UI',-apple-system,system-ui,sans-serif;min-height:100vh}
  .wrap{max-width:1180px;margin:0 auto;padding:26px 22px 90px}
  header h1{margin:0;font-size:1.5rem}
  header h1 .dot{color:var(--accent)}
  header p{color:var(--mut);margin:5px 0 0;font-size:.9rem}
  nav.onglets{display:flex;gap:8px;margin:18px 0}
  nav.onglets button{cursor:pointer;border:1px solid var(--line);background:var(--panel2);
    color:var(--mut);border-radius:20px;padding:7px 16px;font-size:.85rem}
  nav.onglets button.actif{background:var(--accent);color:#0b1622;border-color:var(--accent);font-weight:600}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:16px}
  .vue{display:none}
  .vue.actif{display:block}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="dot">🔭</span> Atelier Veille</h1>
    <p>Carte des créations d'entreprises, sources RSS et digests quotidiens — en un seul endroit.</p>
  </header>
  <nav class="onglets">
    <button id="btn-carte" class="actif" onclick="ouvrirOnglet('carte')">Carte</button>
    <button id="btn-sources" onclick="ouvrirOnglet('sources')">Sources RSS</button>
    <button id="btn-digests" onclick="ouvrirOnglet('digests')">Digests</button>
  </nav>

  <div id="vue-carte" class="vue actif panel" style="padding:0;overflow:hidden">
    <iframe id="geo-iframe" title="Carte de veille"
      style="width:100%;height:70vh;border:0;display:block"></iframe>
  </div>

  <div id="vue-sources" class="vue panel"></div>
  <div id="vue-digests" class="vue panel"></div>
</div>
<script>
function ouvrirOnglet(nom) {
  for (const n of ['carte', 'sources', 'digests']) {
    document.getElementById('vue-' + n).classList.toggle('actif', n === nom);
    document.getElementById('btn-' + n).classList.toggle('actif', n === nom);
  }
}
</script>
</body>
</html>
```

- [ ] **Step 2: Écrire le test**

```python
"""Tests — front de l'atelier-veille servi PAR la brique (motif studio/test_front.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_racine_sert_le_front_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Atelier Veille</title>" in r.text


def test_alias_atelier_sert_le_meme_front():
    assert client.get("/atelier").text == client.get("/").text


def test_workplace_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
```

- [ ] **Step 3: Lancer les tests, vérifier l'échec**

Run: `cd briques/atelier-veille && python3 -m pytest test_front.py -v`
Expected: FAIL — `404` sur `/`, `/atelier`, `/workplace.css`.

- [ ] **Step 4: Implémenter dans `main.py`**

Ajouter aux imports :

```python
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse
```

Ajouter après `VEILLE_INFO_URL` :

```python
_FRONT = Path(__file__).parent / "front.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def racine():
    return FileResponse(_FRONT, media_type="text/html")


@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def alias_atelier():
    return FileResponse(_FRONT, media_type="text/html")


@app.get("/workplace.css", include_in_schema=False)
def css():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")
```

- [ ] **Step 5: Enregistrer `atelier-veille` comme consommateur du CSS partagé**

Dans `outils/sync_socle.sh`, modifier la ligne :

```bash
CSS_BRIQUES=(synopsis voix personnages studio transcription)
```

en :

```bash
CSS_BRIQUES=(synopsis voix personnages studio transcription atelier-veille)
```

- [ ] **Step 6: Lancer le script de synchro**

Run: `bash outils/sync_socle.sh`
Expected: la ligne `→ briques/atelier-veille/workplace.css` apparaît dans la sortie, et le
fichier `briques/atelier-veille/workplace.css` existe.

- [ ] **Step 7: Lancer les tests, vérifier le succès**

Run: `cd briques/atelier-veille && python3 -m pytest test_front.py -v`
Expected: 3 PASS

- [ ] **Step 8: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/front.html \
        briques/atelier-veille/workplace.css briques/atelier-veille/test_front.py \
        outils/sync_socle.sh
git commit -m "feat(atelier-veille): sert son front (squelette 3 onglets) + design system"
```

---

### Task 6: Contenu du front — Sources, Digests, branchement Carte

**Files:**
- Modify: `briques/atelier-veille/front.html`
- Modify: `briques/atelier-veille/test_front.py`

**Interfaces:**
- Consumes: `GET /config`, `GET /veille/sources`, `POST /veille/sources`,
  `DELETE /veille/sources/{id}`, `GET /veille/digests`, `POST /veille/digest/executer`
  (tous définis Tasks 2-4).
- Produces: page fonctionnelle complète (rien de consommé par une tâche ultérieure — c'est
  la dernière pièce de la brique elle-même).

- [ ] **Step 1: Écrire les assertions de contenu (ajout à `test_front.py`)**

```python
def test_front_branche_la_carte_sur_config():
    html = client.get("/").text
    assert "fetch('/config'" in html or 'fetch("/config"' in html
    assert "geo-iframe" in html


def test_front_couvre_la_gestion_des_sources():
    html = client.get("/").text
    for marqueur in ("chargerSources", "ajouterSource", "supprimerSource",
                     "/veille/sources"):
        assert marqueur in html


def test_front_couvre_les_digests_et_laudio():
    html = client.get("/").text
    for marqueur in ("chargerDigests", "genererDigest", "/veille/digests",
                     "/veille/digest/executer", "<audio"):
        assert marqueur in html


def test_front_avertit_que_la_generation_est_pour_tout_le_foyer():
    html = client.get("/").text
    assert "foyer" in html.lower()
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd briques/atelier-veille && python3 -m pytest test_front.py -v`
Expected: FAIL — 4 nouveaux tests échouent (marqueurs absents du squelette Task 5).

- [ ] **Step 3: Compléter `front.html`**

Remplacer le contenu de `<div id="vue-sources" class="vue panel"></div>` par :

```html
<div id="vue-sources" class="vue panel">
  <h3>Sources RSS suivies</h3>
  <div id="liste-sources"></div>
  <h3 style="margin-top:20px">Ajouter une source</h3>
  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <input id="nouvelle-source-nom" placeholder="Nom (ex. Le Monde Tech)" style="flex:1;min-width:180px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
    <input id="nouvelle-source-url" placeholder="URL du flux RSS" style="flex:2;min-width:220px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
    <button onclick="ajouterSource()" style="padding:8px 16px;border-radius:8px;border:none;background:var(--accent);color:#0b1622;font-weight:600;cursor:pointer">Ajouter</button>
  </div>
  <div id="erreur-sources" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>
</div>
```

Remplacer le contenu de `<div id="vue-digests" class="vue panel"></div>` par :

```html
<div id="vue-digests" class="vue panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
    <h3 style="margin:0">Digests quotidiens</h3>
    <button id="btn-generer-digest" onclick="genererDigest()" style="padding:8px 16px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:600;cursor:pointer">
      Générer le digest maintenant (pour tout le foyer)
    </button>
  </div>
  <p style="color:var(--mut);font-size:.82rem">Ce bouton déclenche le digest pour TOUT le
    foyer d'un coup (comme l'horloge quotidienne), pas seulement pour toi.</p>
  <div id="liste-digests"></div>
  <div id="erreur-digests" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>
</div>
```

Remplacer le `<script>` final par :

```html
<script>
function ouvrirOnglet(nom) {
  for (const n of ['carte', 'sources', 'digests']) {
    document.getElementById('vue-' + n).classList.toggle('actif', n === nom);
    document.getElementById('btn-' + n).classList.toggle('actif', n === nom);
  }
  if (nom === 'sources') chargerSources();
  if (nom === 'digests') chargerDigests();
}

async function chargerConfig() {
  const r = await fetch('/config');
  const cfg = await r.json();
  document.getElementById('geo-iframe').src = cfg.geo_url;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function chargerSources() {
  const cible = document.getElementById('liste-sources');
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  try {
    const r = await fetch('/veille/sources');
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const sources = await r.json();
    cible.innerHTML = sources.length ? sources.map(s => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>${esc(s.nom)}</b><br><span style="color:var(--mut);font-size:.8rem">${esc(s.url)}</span></div>
        <button onclick="supprimerSource(${s.id})" style="border:1px solid var(--bad);background:transparent;color:var(--bad);border-radius:8px;padding:5px 10px;cursor:pointer">Retirer</button>
      </div>`).join('') : '<p style="color:var(--mut)">Aucune source suivie pour l\\'instant.</p>';
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function ajouterSource() {
  const nom = document.getElementById('nouvelle-source-nom').value.trim();
  const url = document.getElementById('nouvelle-source-url').value.trim();
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  if (!nom || !url) { erreur.textContent = 'Nom et URL requis.'; return; }
  try {
    const r = await fetch('/veille/sources', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nom, url})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    document.getElementById('nouvelle-source-nom').value = '';
    document.getElementById('nouvelle-source-url').value = '';
    chargerSources();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function supprimerSource(id) {
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  try {
    const r = await fetch(`/veille/sources/${id}`, {method: 'DELETE'});
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    chargerSources();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function chargerDigests() {
  const cible = document.getElementById('liste-digests');
  const erreur = document.getElementById('erreur-digests');
  erreur.textContent = '';
  try {
    const r = await fetch('/veille/digests');
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const digests = await r.json();
    cible.innerHTML = digests.length ? digests.map(d => `
      <div style="padding:12px 0;border-bottom:1px solid var(--line)">
        <b>${esc(d.date)}</b> <span style="color:var(--mut);font-size:.8rem">(${d.nb_articles} article${d.nb_articles > 1 ? 's' : ''})</span>
        <p style="margin:6px 0">${esc(d.texte_resume)}</p>
        ${d.audio_url ? `<audio controls src="${esc(d.audio_url)}"></audio>` : '<span style="color:var(--mut);font-size:.8rem">Pas encore de version audio.</span>'}
      </div>`).join('') : '<p style="color:var(--mut)">Aucun digest généré pour l\\'instant.</p>';
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function genererDigest() {
  const bouton = document.getElementById('btn-generer-digest');
  const erreur = document.getElementById('erreur-digests');
  erreur.textContent = '';
  bouton.disabled = true;
  try {
    const r = await fetch('/veille/digest/executer', {method: 'POST'});
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    await chargerDigests();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  } finally {
    bouton.disabled = false;
  }
}

chargerConfig();
chargerSources();
</script>
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `cd briques/atelier-veille && python3 -m pytest test_front.py -v`
Expected: 7 PASS

- [ ] **Step 5: Lancer TOUTE la suite de la brique**

Run: `cd briques/atelier-veille && python3 -m pytest -v`
Expected: tous les tests PASS (Tasks 2-6 cumulés, ~21 tests).

- [ ] **Step 6: Commit**

```bash
git add briques/atelier-veille/front.html briques/atelier-veille/test_front.py
git commit -m "feat(atelier-veille): front complet — sources RSS, digests, audio, carte"
```

---

### Task 7: Câblage au dashboard du Cœur + launcher + `.env.example`

**Files:**
- Modify: `core/urls_ui.py`
- Modify: `core/routers/dashboard.py`
- Modify: `.env.example`
- Modify: `Lancer Workplace.command`

**Interfaces:**
- Consumes: `url_brique("ATELIER_VEILLE", scheme, host)` (motif déjà présent dans
  `urls_ui.py`).
- Produces: tuile « Veille » dans le hub Atelier du dashboard, ouvrant
  `http://localhost:6130/atelier` (ou l'équivalent mesh) dans `#creation-iframe`.

- [ ] **Step 1: Ajouter l'entrée dans `core/urls_ui.py`**

Dans la table `BRIQUES_UI` (`core/urls_ui.py`), ajouter après la ligne `"GEO"` :

```python
    "GEO":           (6110, "/"),          # GeoHub : carte de veille (Leaflet autoporté)
    "ATELIER_VEILLE": (6130, "/atelier"),  # front unique famille veille (S190)
    "AGENDA":        (8400, "/app"),       # appli agenda autonome (calendar-app, S172)
```

- [ ] **Step 2: Écrire le test de non-régression pour `urls_ui.py`**

Vérifier s'il existe déjà un fichier `core/test_urls_ui.py` :

Run: `ls core/test_urls_ui.py 2>/dev/null || echo "absent"`

Si absent, créer `core/test_urls_ui.py` :

```python
"""Test — table BRIQUES_UI (S190) : atelier-veille doit être résolvable comme les autres
briques embarquées en iframe du dashboard."""
import urls_ui


def test_atelier_veille_resoluble():
    url = urls_ui.url_brique("ATELIER_VEILLE", "http", "localhost:5100")
    assert url == "http://localhost:6130/atelier"
```

Si le fichier existe déjà, ajouter cette fonction de test à la fin du fichier existant à la
place (ne pas créer de doublon).

- [ ] **Step 3: Lancer le test, vérifier le succès**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_urls_ui.py -v`
Expected: 1 PASS

- [ ] **Step 4: Ajouter la tuile dans `core/routers/dashboard.py`**

Dans la grille du hub Atelier (`core/routers/dashboard.py`), juste après le bouton Mémoire
(`onclick="ouvrirCreation('__MEMOIRE_UI_URL__', ...)`) et avant la tuile désactivée
« Images & Vidéo », insérer :

```html
        <button class="creation-tuile" onclick="ouvrirCreation('__ATELIER_VEILLE_UI_URL__', 'Veille — carte, RSS, digests')">
          <span class="creation-emoji">🔭</span>
          <span class="creation-titre">Veille</span>
          <span class="creation-desc">Carte des créations d'entreprises, sources RSS suivies et digests quotidiens (texte + audio) — en un seul endroit.</span>
          <span class="creation-badge">Brique · port 6130</span>
        </button>
```

- [ ] **Step 5: Brancher le placeholder dans le rendu HTML**

Dans la même fonction (`core/routers/dashboard.py`, bloc `return HTMLResponse(...)`),
ajouter une ligne juste après `.replace("__GEO_UI_URL__", geo_ui)` :

```python
        .replace("__GEO_UI_URL__", geo_ui)
        .replace("__ATELIER_VEILLE_UI_URL__", u("ATELIER_VEILLE")))
```

(en retirant la parenthèse fermante `))` de la ligne précédente qui portait la fin de la
chaîne d'appels, pour la reporter sur cette nouvelle dernière ligne — vérifier après édition
que la fonction se termine bien par un seul `))`.)

- [ ] **Step 6: Vérifier que le Cœur démarre et sert le dashboard**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_dashboard.py -v`
Expected: tous les tests existants PASS (aucune régression du gabarit HTML).

- [ ] **Step 7: Documenter la brique dans `.env.example`**

Dans `.env.example`, juste après le bloc `# ── Brique « geo » ...` (avant `GEO_UI_URL=`),
ajouter à la suite de ce bloc :

```
# ── Brique « atelier-veille » (front unique de la famille veille, port 6130) ──────
# Compose geo (carte, iframe) et veille-info (sources RSS, digests, audio) par HTTP, sans
# dupliquer leur code. Aucune capacité LLM : surface humaine uniquement (tuile « Veille »
# du hub Atelier du dashboard). GEO_PUBLIC_URL : URL de la carte geo VUE DU NAVIGATEUR
# (pas host.docker.internal) — sert à positionner l'iframe de l'onglet Carte.
GEO_PUBLIC_URL=http://localhost:6110/
```

- [ ] **Step 8: Câbler au launcher `Lancer Workplace.command`**

Dans la liste `briques` de `Lancer Workplace.command`, ajouter juste après la ligne
`"geo|$RACINE/briques/geo|http://localhost:6110/sante"` :

```
  "geo|$RACINE/briques/geo|http://localhost:6110/sante"
  "atelier-veille|$RACINE/briques/atelier-veille|http://localhost:6130/sante"
```

Note pour la vérification manuelle (Step 9) : `veille-info` n'est aujourd'hui **pas**
présente dans ce launcher (gap préexistant, hors périmètre de ce plan) — pour un test bout-
en-bout local, démarrer `veille-info` à la main :
`docker compose -f briques/veille-info/docker-compose.yml up -d --build`.

- [ ] **Step 9: Vérification manuelle bout-en-bout**

```bash
docker compose -f briques/geo/docker-compose.yml up -d --build
docker compose -f briques/veille-info/docker-compose.yml up -d --build
docker compose -f briques/atelier-veille/docker-compose.yml up -d --build
curl http://localhost:6130/sante
curl http://localhost:6130/config
curl http://localhost:6130/veille/sources
```

Expected : les trois `curl` répondent 200 ; `/config` renvoie
`{"geo_url":"http://localhost:6110/"}` ; `/veille/sources` renvoie `[]`. Puis ouvrir
`http://localhost:6130/atelier` dans un navigateur : les trois onglets s'affichent, l'onglet
Carte charge la carte de `geo`, ajouter une source RSS dans l'onglet Sources fonctionne.

- [ ] **Step 10: Suite complète**

Run: `make smoke && make test-core`
Expected: tous PASS (aucune régression sur le reste du Cœur).

- [ ] **Step 11: Commit**

```bash
git add core/urls_ui.py core/routers/dashboard.py core/test_urls_ui.py \
        .env.example "Lancer Workplace.command"
git commit -m "feat(atelier-veille): câble la tuile au dashboard du Cœur + launcher"
```

---

## Self-Review

**Couverture du spec** : carte réutilisée en iframe (Task 5/6) ✓, gestion complète des
sources RSS (Task 3/6) ✓, lecture digests + audio + génération manuelle (Task 4/6) ✓, backend
de composition plutôt qu'appels navigateur directs (Task 3/4) ✓, page unique à onglets
(Task 5/6) ✓, zéro modification de `geo`/`veille-info` (aucune tâche n'y touche) ✓, tuile du
hub Atelier (Task 7) ✓. Écart assumé et documenté vis-à-vis du texte littéral du spec :
pas de câblage `BRIQUES_PAR_PERSONNE`/`outils_communs.py` — inapplicable, ce mécanisme ne
sert que les briques appelées PAR le Cœur comme outil LLM, ce que l'atelier n'est pas
(`capacites: []`) ; le pass-through d'identité décrit au spec est réalisé directement dans
les endpoints de composition (Task 3/4).

**Types/signatures** : `VEILLE_INFO_URL`, `GEO_PUBLIC_URL`, `_entetes_aval()` introduits
Task 2/3, réutilisés identiques Task 4 (pas de renommage entre tâches). Champs des réponses
JSON de `veille-info` (`nom`, `url`, `id`, `date`, `texte_resume`, `nb_articles`,
`audio_url`, `audio_duree`) vérifiés dans le code réel de `briques/veille-info/stockage.py`
avant écriture des tests — pas d'invention de champ.
