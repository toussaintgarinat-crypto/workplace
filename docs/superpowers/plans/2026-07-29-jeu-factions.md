# Brique `jeu-factions` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new `jeu-factions` brick (port 6210) — character creation via the existing `personnages` holistic engine, sign-based shared PvE zones, and personal archetype questlines with open "carry" groups — exactly per `docs/superpowers/specs/2026-07-29-jeu-factions-design.md`.

**Architecture:** A new FastAPI brick following the exact Workplace brick pattern (`manifest.json`, `Dockerfile`, `docker-compose.yml`, `API_KEYS` tenant auth, SQLite, HTML front without a build step). It performs **zero holistic computation itself** — every character creation call goes over HTTP to the existing `personnages` brick (`/holistique/portrait`, `/holistique/recherche-inverse`). All game state (characters, zones, progression, groups) lives in `jeu-factions`' own SQLite database. A single internal asyncio loop resolves zone/group PvE thresholds on a timer.

**Tech Stack:** Python 3.12, FastAPI, httpx (async client), SQLite (stdlib `sqlite3`), pytest + `TestClient` + `httpx.MockTransport`, Docker.

## Global Constraints

- Brick name: `jeu-factions`. Port: **6210** (6200 is already taken by `connecteurs` — verified against every `briques/*/manifest.json`).
- `jeu-factions` never recomputes holistic traditions/stats — all such data comes from `personnages` over HTTP and is stored as a frozen snapshot.
- Tenant isolation is **inverted from the Workplace norm** for this brick: `personnages_jeu` and `groupes`/`membres_groupe` are cloisonné by `cle_api` (owner-only read/write); `zones`, `scores_zone_guilde`, `zones_archetype`, `competences` are a **shared global world** — readable by any authenticated tenant, no per-tenant filtering.
- No real combat engine, no PvP, no real user accounts, no quest/lore system beyond the minimal ordered-stage structure, no skill *effects* — all explicitly out of scope per the spec's Non-objectifs.
- Dependencies pinned exactly like `briques/personnages/requirements.txt` (fastapi, uvicorn, httpx) — no new library beyond stdlib + those three.
- Every SQL table, therefore every piece of state, is created in `stockage.py::_conn()` — the single source of schema truth, mirroring `briques/personnages/stockage.py`.
- Mock `personnages` HTTP calls in tests via `httpx.MockTransport` (precedent: `briques/calcul/test_noeud.py`) — never hit the network in tests.

---

## File Structure

```
briques/jeu-factions/
  manifest.json
  Dockerfile
  docker-compose.yml
  requirements.txt
  conftest.py
  main.py                  — FastAPI app, all routes, auth dependency
  moteur_personnages.py    — HTTP client to the `personnages` brick
  stockage.py               — SQLite schema (ALL tables) + joueurs/personnages_jeu CRUD
  zones.py                  — 12 sign zones: seed, pure resolution calc, DB orchestration
  archetypes.py             — 10 archetype paths: seed, progression, competence unlocks
  groupes.py                — group creation/join/resolution
  tick.py                    — scheduled resolution loop (pure `executer_tick()` + asyncio wrapper)
  front.html                 — minimal no-build UI
  workplace.css              — copied from an existing brick (shared design system)
  README.md
  test_moteur_personnages.py
  test_stockage.py
  test_zones.py
  test_archetypes.py
  test_groupes.py
  test_tick.py
  test_api.py
  test_isolation.py
```

---

### Task 1: Scaffold the brick — health check + manifest contract

**Files:**
- Create: `briques/jeu-factions/requirements.txt`
- Create: `briques/jeu-factions/main.py`
- Create: `briques/jeu-factions/conftest.py`
- Create: `briques/jeu-factions/manifest.json`
- Create: `briques/jeu-factions/Dockerfile`
- Create: `briques/jeu-factions/docker-compose.yml`
- Test: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Produces: `main.app` (FastAPI instance), `GET /sante` → `{"statut": "ok"}`, env `API_KEYS` (auth mode).

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

- [ ] **Step 2: Create `conftest.py`** (sets test env vars before any brick module import — mirrors `briques/personnages/conftest.py`)

```python
"""Config de test : DB temporaire + mode auth ouvert AVANT tout import des modules."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "jeu_factions_test.db")
os.environ["JEU_FACTIONS_DB"] = _db
os.environ.setdefault("API_KEYS", "")               # mode ouvert → tenant "public"
os.environ.setdefault("PERSONNAGES_URL", "http://personnages-test.invalid")
os.environ["JEU_FACTIONS_TICK_AUTOSTART"] = "0"      # jamais de boucle asyncio réelle en test

if os.path.exists(_db):
    os.remove(_db)
```

- [ ] **Step 3: Write the failing test**

```python
# test_api.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'main'` (file doesn't exist yet).

- [ ] **Step 5: Write minimal `main.py`**

```python
"""Brique « jeu-factions » — création de personnage + factions/territoire (PvE).

Réutilise le moteur holistique de `personnages` en HTTP (aucun calcul dupliqué). Voir
docs/superpowers/specs/2026-07-29-jeu-factions-design.md pour le design complet.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Jeu-factions — factions & territoire (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API et sert de tenant. Vide = mode ouvert → tenant "public"."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS

- [ ] **Step 7: Create `manifest.json`**

```json
{
  "nom": "jeu-factions",
  "famille": "metier",
  "version": "0.1.0",
  "description": "Création de personnage (via la brique personnages) + factions à deux niveaux (nation=élément, guilde=signe, classe=archétype) + zones de signe en PvE partagé + voies d'archétype personnelles avec groupes ouverts. Premier sous-projet du jeu holistique.",
  "role": "jeu-factions",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/jeu-factions",
  "port": 6210,
  "url_sante": "http://host.docker.internal:6210/sante",
  "depends_on": ["personnages"],
  "offre": [
    "creation_personnage_holistique",
    "zones_signe_pve_partage",
    "voies_archetype_personnelles",
    "groupes_ouverts"
  ],
  "besoin": [],
  "taches": [],
  "capacites": []
}
```

- [ ] **Step 8: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6210"]
```

- [ ] **Step 9: Create `docker-compose.yml`**

```yaml
services:
  jeu-factions:
    build: .
    container_name: workplace_jeu_factions
    image: workplace/jeu-factions:0.1.0
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6210:6210"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - PORT=6210
      - PERSONNAGES_URL=http://host.docker.internal:5900
      - JEU_FACTIONS_DB=/data/jeu_factions.db
      - TICK_INTERVAL_HOURS=24
      - STATS_ZONE_SIGNE=Combativité,Énergie
    volumes:
      - jeu_factions_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6210/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  jeu_factions_data:
```

- [ ] **Step 10: Verify the manifest contract passes the repo-wide smoke test**

Run (from the repo root — the worktree root you're already working in, NOT the original checkout path): `python -m pytest tests/test_briques_smoke.py -k jeu-factions -v`
Expected: PASS (no missing fields, no port collision — 6210 is free).

- [ ] **Step 11: Commit**

```bash
git add briques/jeu-factions/
git commit -m "feat(jeu-factions): scaffold brick — health check + manifest contract"
```

---

### Task 2: HTTP client to `personnages` (`moteur_personnages.py`)

**Files:**
- Create: `briques/jeu-factions/moteur_personnages.py`
- Test: `briques/jeu-factions/test_moteur_personnages.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `async def portrait(fiche: dict, client: httpx.AsyncClient | None = None) -> dict`, `async def recherche_inverse(description: str, combien: int = 3, client: httpx.AsyncClient | None = None) -> dict`. Both raise `fastapi.HTTPException(503, ...)` on connection failure, and propagate `HTTPException(status_code, detail)` when `personnages` returns >= 400.

- [ ] **Step 1: Write the failing tests**

```python
# test_moteur_personnages.py
import httpx
import pytest
from fastapi import HTTPException

import moteur_personnages as MP


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_portrait_relaie_le_resultat():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/holistique/portrait"
        return httpx.Response(200, json={"traditions": {}, "portrait": {"archetype": "Le Sage Contemplatif"}, "empreinte": []})

    async with _client(handler) as c:
        r = await MP.portrait({"date_naissance": "1990-09-05"}, client=c)
    assert r["portrait"]["archetype"] == "Le Sage Contemplatif"


@pytest.mark.asyncio
async def test_portrait_leve_503_si_injoignable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _client(handler) as c:
        with pytest.raises(HTTPException) as exc:
            await MP.portrait({"date_naissance": "1990-09-05"}, client=c)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_portrait_propage_lerreur_amont():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Fiche insuffisante"})

    async with _client(handler) as c:
        with pytest.raises(HTTPException) as exc:
            await MP.portrait({}, client=c)
    assert exc.value.status_code == 422
    assert "Fiche insuffisante" in exc.value.detail


@pytest.mark.asyncio
async def test_recherche_inverse_relaie_le_resultat():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/holistique/recherche-inverse"
        return httpx.Response(200, json={"exemple_date": "1990-04-01", "signes": []})

    async with _client(handler) as c:
        r = await MP.recherche_inverse("guerrier colérique et solitaire", client=c)
    assert r["exemple_date"] == "1990-04-01"
```

- [ ] **Step 2: Add `pytest-asyncio` to test dependencies and run to verify failure**

```
# requirements-dev additions are handled at repo root (constraints-workplace.txt already
# pins httpx/fastapi); add pytest-asyncio locally for this brick's async tests:
```

Add to `briques/jeu-factions/requirements.txt`:
```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```
(pytest-asyncio is a dev-only tool; add a `briques/jeu-factions/requirements-dev.txt`):
```
pytest==8.3.4
pytest-asyncio==0.24.0
```

Run: `cd briques/jeu-factions && pip install -r requirements-dev.txt -r requirements.txt && python -m pytest test_moteur_personnages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moteur_personnages'`.

- [ ] **Step 3: Create `pytest.ini` for asyncio mode** (scoped to this brick)

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 4: Write `moteur_personnages.py`**

```python
"""Client HTTP vers la brique `personnages` — le SEUL point d'appel au moteur holistique.

`jeu-factions` ne recalcule jamais une tradition/stat : tout passe par ces deux fonctions,
qui relaient tel quel la réponse de `personnages` (ou lèvent une HTTPException lisible)."""
import os

import httpx
from fastapi import HTTPException

PERSONNAGES_URL = os.getenv("PERSONNAGES_URL", "http://host.docker.internal:5900")
PERSONNAGES_KEY = os.getenv("PERSONNAGES_KEY", "")


def _entetes() -> dict:
    return {"X-API-Key": PERSONNAGES_KEY} if PERSONNAGES_KEY else {}


async def _appeler(chemin: str, corps: dict, client: httpx.AsyncClient | None = None) -> dict:
    async def _via(c: httpx.AsyncClient) -> dict:
        try:
            r = await c.post(f"{PERSONNAGES_URL}{chemin}", headers=_entetes(), json=corps)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"personnages injoignable ({PERSONNAGES_URL}) : {str(e)[:150]}")
        try:
            corps_reponse = r.json()
        except Exception:  # noqa: BLE001
            corps_reponse = {}
        if r.status_code >= 400:
            detail = corps_reponse.get("detail") if isinstance(corps_reponse, dict) else None
            raise HTTPException(r.status_code, detail or f"personnages a refusé la requête ({r.status_code}).")
        return corps_reponse

    if client is not None:
        return await _via(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _via(c)


async def portrait(fiche: dict, client: httpx.AsyncClient | None = None) -> dict:
    """Mode descendant : POST /holistique/portrait. `fiche` suit FicheHolistique de personnages."""
    return await _appeler("/holistique/portrait", fiche, client)


async def recherche_inverse(description: str, combien: int = 3,
                            client: httpx.AsyncClient | None = None) -> dict:
    """Mode montant : POST /holistique/recherche-inverse."""
    return await _appeler("/holistique/recherche-inverse",
                          {"description": description, "combien": combien}, client)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_moteur_personnages.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/moteur_personnages.py briques/jeu-factions/test_moteur_personnages.py briques/jeu-factions/pytest.ini briques/jeu-factions/requirements-dev.txt
git commit -m "feat(jeu-factions): HTTP client to personnages (portrait + recherche-inverse)"
```

---

### Task 3: Storage schema + joueurs/personnages_jeu (`stockage.py`)

**Files:**
- Create: `briques/jeu-factions/stockage.py`
- Test: `briques/jeu-factions/test_stockage.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `stockage._conn() -> sqlite3.Connection` (creates ALL 11 tables — every later module imports and reuses this), `stockage.assurer_joueur(cle_api: str, pseudo: str = "") -> None`, `stockage.creer_personnage(cle_api: str, nom: str, donnees_naissance: dict, snapshot: dict) -> dict`, `stockage.lister_personnages(cle_api: str) -> list[dict]`, `stockage.lire_personnage(cle_api: str, pid: str) -> dict | None`, `stockage.assigner_zone(cle_api: str, pid: str, zone_id: str) -> dict | None`, `stockage.log_resolution(zone_id: str | None, zone_archetype_id: str | None, contributions: dict, etat_resultant: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# test_stockage.py
import stockage as S


def test_creer_et_lire_personnage():
    S.assurer_joueur("cleA", "Alice")
    p = S.creer_personnage("cleA", "Aria", {"date_naissance": "1990-09-05"},
                           {"portrait": {"archetype": "Le Sage Contemplatif", "stats": {"Sagesse": 100}}})
    assert p["nom"] == "Aria"
    assert p["zone_actuelle"] is None
    lu = S.lire_personnage("cleA", p["id"])
    assert lu["snapshot_holistique"]["portrait"]["archetype"] == "Le Sage Contemplatif"


def test_lire_personnage_dun_autre_compte_renvoie_none():
    S.assurer_joueur("cleB", "Bob")
    p = S.creer_personnage("cleB", "Vorn", {"date_naissance": "1985-01-01"}, {"portrait": {}})
    assert S.lire_personnage("cleA", p["id"]) is None


def test_lister_personnages_filtre_par_compte():
    S.assurer_joueur("cleC", "Cid")
    S.creer_personnage("cleC", "Un", {"date_naissance": "2000-01-01"}, {"portrait": {}})
    S.creer_personnage("cleC", "Deux", {"date_naissance": "2000-01-02"}, {"portrait": {}})
    noms = {p["nom"] for p in S.lister_personnages("cleC")}
    assert noms == {"Un", "Deux"}


def test_un_compte_peut_avoir_plusieurs_personnages():
    S.assurer_joueur("cleD", "Dora")
    a = S.creer_personnage("cleD", "A", {"date_naissance": "1999-01-01"}, {"portrait": {}})
    b = S.creer_personnage("cleD", "B", {"date_naissance": "1999-01-02"}, {"portrait": {}})
    assert a["id"] != b["id"]
    assert len(S.lister_personnages("cleD")) == 2


def test_assigner_zone():
    S.assurer_joueur("cleE", "Eve")
    p = S.creer_personnage("cleE", "Zed", {"date_naissance": "2001-05-05"}, {"portrait": {}})
    maj = S.assigner_zone("cleE", p["id"], "zone-belier")
    assert maj["zone_actuelle"] == "zone-belier"


def test_assigner_zone_personnage_absent_renvoie_none():
    assert S.assigner_zone("cleE", "inconnu", "zone-belier") is None


def test_log_resolution_ne_leve_pas():
    S.log_resolution("zone-belier", None, {"Bélier": 10}, "vaincue")
    S.log_resolution(None, "arch-1", {"perso-1": 5}, "en_cours")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stockage'`.

- [ ] **Step 3: Write `stockage.py`**

```python
"""Schéma SQLite complet de `jeu-factions` (source unique de vérité pour toutes les tables)
+ CRUD des joueurs et personnages. Cloisonné par `cle_api` — mais voir zones.py/archetypes.py :
zones/scores/étapes/compétences sont un monde PARTAGÉ, pas filtré par tenant (design assumé,
cf. spec)."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("JEU_FACTIONS_DB", "/data/jeu_factions.db")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS joueurs (
        cle_api TEXT PRIMARY KEY, pseudo TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS personnages_jeu (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, nom TEXT NOT NULL,
        donnees_naissance TEXT NOT NULL, snapshot_holistique TEXT NOT NULL,
        zone_actuelle TEXT, cree_le TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_perso_cle ON personnages_jeu(cle_api)")
    c.execute("""CREATE TABLE IF NOT EXISTS zones (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, element_natif TEXT NOT NULL,
        signe_natif TEXT NOT NULL, difficulte_pve INTEGER NOT NULL,
        etat TEXT NOT NULL DEFAULT 'en_cours')""")
    c.execute("""CREATE TABLE IF NOT EXISTS scores_zone_guilde (
        zone_id TEXT NOT NULL, guilde TEXT NOT NULL, points_cumules INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (zone_id, guilde))""")
    c.execute("""CREATE TABLE IF NOT EXISTS resolutions (
        id TEXT PRIMARY KEY, zone_id TEXT, zone_archetype_id TEXT, horodatage TEXT NOT NULL,
        contributions TEXT NOT NULL, etat_resultant TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS zones_archetype (
        id TEXT PRIMARY KEY, archetype TEXT NOT NULL, ordre INTEGER NOT NULL,
        nom TEXT NOT NULL, difficulte_pve INTEGER NOT NULL, texte_lore TEXT NOT NULL,
        UNIQUE (archetype, ordre))""")
    c.execute("""CREATE TABLE IF NOT EXISTS progression_archetype (
        personnage_id TEXT NOT NULL, zone_archetype_id TEXT NOT NULL,
        etat TEXT NOT NULL DEFAULT 'en_cours', date_completion TEXT,
        PRIMARY KEY (personnage_id, zone_archetype_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS groupes (
        id TEXT PRIMARY KEY, personnage_cible_id TEXT NOT NULL, zone_archetype_id TEXT NOT NULL,
        etat TEXT NOT NULL DEFAULT 'actif', cree_le TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS membres_groupe (
        groupe_id TEXT NOT NULL, personnage_id TEXT NOT NULL,
        PRIMARY KEY (groupe_id, personnage_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS competences (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, texte TEXT NOT NULL,
        archetype TEXT NOT NULL, ordre_etape INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS competences_debloquees (
        personnage_id TEXT NOT NULL, competence_id TEXT NOT NULL, date TEXT NOT NULL,
        PRIMARY KEY (personnage_id, competence_id))""")
    return c


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def assurer_joueur(cle_api: str, pseudo: str = "") -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO joueurs (cle_api, pseudo) VALUES (?,?)",
                  (cle_api, pseudo or cle_api))


def _ligne_personnage(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"],
            "donnees_naissance": json.loads(r["donnees_naissance"]),
            "snapshot_holistique": json.loads(r["snapshot_holistique"]),
            "zone_actuelle": r["zone_actuelle"], "cree_le": r["cree_le"]}


def creer_personnage(cle_api: str, nom: str, donnees_naissance: dict, snapshot: dict) -> dict:
    pid = uuid.uuid4().hex
    cree_le = _maintenant()
    with _conn() as c:
        c.execute("""INSERT INTO personnages_jeu
                     (id, cle_api, nom, donnees_naissance, snapshot_holistique, zone_actuelle, cree_le)
                     VALUES (?,?,?,?,?,NULL,?)""",
                  (pid, cle_api, nom, json.dumps(donnees_naissance, ensure_ascii=False),
                   json.dumps(snapshot, ensure_ascii=False), cree_le))
    return {"id": pid, "nom": nom, "donnees_naissance": donnees_naissance,
            "snapshot_holistique": snapshot, "zone_actuelle": None, "cree_le": cree_le}


def lister_personnages(cle_api: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM personnages_jeu WHERE cle_api=? ORDER BY cree_le",
                         (cle_api,)).fetchall()
    return [_ligne_personnage(r) for r in rows]


def lire_personnage(cle_api: str, pid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM personnages_jeu WHERE id=? AND cle_api=?",
                      (pid, cle_api)).fetchone()
    return _ligne_personnage(r) if r else None


def assigner_zone(cle_api: str, pid: str, zone_id: str) -> dict | None:
    with _conn() as c:
        cur = c.execute("UPDATE personnages_jeu SET zone_actuelle=? WHERE id=? AND cle_api=?",
                        (zone_id, pid, cle_api))
        if cur.rowcount == 0:
            return None
    return lire_personnage(cle_api, pid)


def log_resolution(zone_id: str | None, zone_archetype_id: str | None,
                   contributions: dict, etat_resultant: str) -> None:
    with _conn() as c:
        c.execute("""INSERT INTO resolutions (id, zone_id, zone_archetype_id, horodatage,
                     contributions, etat_resultant) VALUES (?,?,?,?,?,?)""",
                  (uuid.uuid4().hex, zone_id, zone_archetype_id, _maintenant(),
                   json.dumps(contributions, ensure_ascii=False), etat_resultant))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/stockage.py briques/jeu-factions/test_stockage.py
git commit -m "feat(jeu-factions): SQLite schema (all 11 tables) + joueurs/personnages CRUD"
```

---

### Task 4: `POST/GET /personnages` + `PATCH /personnages/{id}/zone` routes

**Files:**
- Modify: `briques/jeu-factions/main.py`
- Test: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Consumes: `moteur_personnages.portrait`, `moteur_personnages.recherche_inverse` (Task 2); `stockage.assurer_joueur`, `stockage.creer_personnage`, `stockage.lister_personnages`, `stockage.lire_personnage`, `stockage.assigner_zone` (Task 3).
- Produces: `POST /personnages`, `GET /personnages`, `GET /personnages/{id}`, `PATCH /personnages/{id}/zone` — used by Task 6 (zone routes reuse `lire_personnage` for ownership checks) and Task 10 (groupe routes).

- [ ] **Step 1: Write the failing tests**

```python
# append to test_api.py
import httpx
import stockage


def _patch_moteur(monkeypatch, portrait_reponse=None, ri_reponse=None):
    async def _portrait(fiche, client=None):
        return portrait_reponse or {"portrait": {"archetype": "Le Sage Contemplatif",
                                                  "stats": {"Sagesse": 100}},
                                     "traditions": {"signe_solaire": {"nom": "Vierge"}},
                                     "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return ri_reponse if ri_reponse is not None else {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_creer_personnage_par_date(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Aria", "date_naissance": "1990-09-05"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["nom"] == "Aria"
    assert corps["snapshot_holistique"]["portrait"]["archetype"] == "Le Sage Contemplatif"


def test_creer_personnage_par_description(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Vorn", "description": "guerrier colérique"})
    assert r.status_code == 200
    assert r.json()["donnees_naissance"] == {"description": "guerrier colérique"}


def test_creer_personnage_sans_date_ni_description_422():
    r = client.post("/personnages", json={"nom": "Vide"})
    assert r.status_code == 422


def test_creer_personnage_description_sans_date_deduite_422(monkeypatch):
    _patch_moteur(monkeypatch, ri_reponse={"exemple_date": None})
    r = client.post("/personnages", json={"nom": "Flou", "description": "quelque chose"})
    assert r.status_code == 422


def test_lister_et_lire_personnage(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Lu", "date_naissance": "1990-01-01"})
    pid = r.json()["id"]
    assert any(p["id"] == pid for p in client.get("/personnages").json())
    assert client.get(f"/personnages/{pid}").json()["nom"] == "Lu"


def test_lire_personnage_inconnu_404():
    assert client.get("/personnages/inconnu").status_code == 404


def test_assigner_zone_personnage_inconnu_404():
    r = client.patch("/personnages/inconnu/zone", json={"zone_id": "zone-belier"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v -k creer_personnage`
Expected: FAIL — `404 Not Found` for the new routes (they don't exist yet).

- [ ] **Step 3: Extend `main.py`** — add imports, models, and routes

```python
# add near the top imports of main.py
from typing import Optional

import moteur_personnages
import stockage
from pydantic import BaseModel


class CreerPersonnage(BaseModel):
    nom: str
    prenoms: str = ""
    date_naissance: Optional[str] = None
    heure_naissance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset: Optional[float] = None
    description: Optional[str] = None


class AssignerZone(BaseModel):
    zone_id: str


@app.post("/personnages", tags=["personnages"])
async def creer_personnage_route(body: CreerPersonnage, cle: str = Depends(cle_api)):
    a_une_date = bool((body.date_naissance or "").strip())
    a_une_description = bool((body.description or "").strip())
    if not a_une_date and not a_une_description:
        raise HTTPException(422, "Fournis une date de naissance ou une description.")

    if a_une_date:
        donnees_naissance = {"date_naissance": body.date_naissance,
                             "heure_naissance": body.heure_naissance,
                             "latitude": body.latitude, "longitude": body.longitude,
                             "utc_offset": body.utc_offset}
        fiche = {**donnees_naissance, "prenoms": body.prenoms, "nom": body.nom}
    else:
        donnees_naissance = {"description": body.description}
        ri = await moteur_personnages.recherche_inverse(body.description)
        exemple_date = ri.get("exemple_date")
        if not exemple_date:
            raise HTTPException(422, "Description trop vague : aucune date déduite. "
                                     "Précise le caractère ou fournis une date.")
        fiche = {"date_naissance": exemple_date, "prenoms": body.prenoms, "nom": body.nom}

    resultat = await moteur_personnages.portrait(fiche)
    stockage.assurer_joueur(cle)
    return stockage.creer_personnage(cle, body.nom, donnees_naissance, resultat)


@app.get("/personnages", tags=["personnages"])
def lister_personnages_route(cle: str = Depends(cle_api)):
    return stockage.lister_personnages(cle)


@app.get("/personnages/{pid}", tags=["personnages"])
def lire_personnage_route(pid: str, cle: str = Depends(cle_api)):
    p = stockage.lire_personnage(cle, pid)
    if not p:
        raise HTTPException(404, "Personnage introuvable.")
    return p


@app.patch("/personnages/{pid}/zone", tags=["personnages"])
def assigner_zone_route(pid: str, body: AssignerZone, cle: str = Depends(cle_api)):
    p = stockage.assigner_zone(cle, pid, body.zone_id)
    if not p:
        raise HTTPException(404, "Personnage introuvable.")
    return p
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS (all tests including Task 1's `test_sante`).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/test_api.py
git commit -m "feat(jeu-factions): character creation routes (date + description paths)"
```

---

### Task 5: Sign zones — seed, pure resolution, orchestration (`zones.py`)

**Files:**
- Create: `briques/jeu-factions/zones.py`
- Test: `briques/jeu-factions/test_zones.py`

**Interfaces:**
- Consumes: `stockage._conn` (Task 3).
- Produces: `zones.ZONES_SEED` (12-tuple list), `zones.seed_zones() -> None`, `zones.lister_zones() -> list[dict]`, `zones.lire_zone(zone_id: str) -> dict | None`, `zones.calculer_resolution(personnages: list[dict], stats_cles: list[str], difficulte: int) -> dict` (pure), `zones.resoudre_toutes_zones(stats_cles: list[str]) -> list[dict]` (used by Task 11's `tick.py`).

- [ ] **Step 1: Write the failing tests**

```python
# test_zones.py
import stockage as S
import zones as Z


def test_seed_zones_cree_les_12_zones():
    Z.seed_zones()
    zs = Z.lister_zones()
    assert len(zs) == 12
    assert {z["signe_natif"] for z in zs} == {
        "Bélier", "Taureau", "Gémeaux", "Cancer", "Lion", "Vierge",
        "Balance", "Scorpion", "Sagittaire", "Capricorne", "Verseau", "Poissons"}


def test_seed_zones_est_idempotent():
    Z.seed_zones()
    Z.seed_zones()
    assert len(Z.lister_zones()) == 12


def test_lire_zone_inconnue_none():
    assert Z.lire_zone("inconnue") is None


def test_calculer_resolution_pure_vaincue():
    personnages = [{"id": "p1", "signe": "Bélier", "stats": {"Combativité": 60, "Énergie": 20}},
                  {"id": "p2", "signe": "Lion", "stats": {"Combativité": 10, "Énergie": 10}}]
    res = Z.calculer_resolution(personnages, ["Combativité", "Énergie"], difficulte=90)
    assert res["total"] == 100
    assert res["vaincue"] is True
    assert res["par_guilde"] == {"Bélier": 80, "Lion": 20}


def test_calculer_resolution_pure_pas_vaincue():
    personnages = [{"id": "p1", "signe": "Bélier", "stats": {"Combativité": 5, "Énergie": 5}}]
    res = Z.calculer_resolution(personnages, ["Combativité", "Énergie"], difficulte=90)
    assert res["vaincue"] is False


def test_resoudre_toutes_zones_marque_vaincue_et_note_le_score():
    Z.seed_zones()
    S.assurer_joueur("cleF", "Fay")
    p = S.creer_personnage("cleF", "Ram", {"date_naissance": "1990-01-01"},
                           {"portrait": {"stats": {"Combativité": 200, "Énergie": 200}}},
                           )
    zs = Z.lister_zones()
    belier = next(z for z in zs if z["signe_natif"] == "Bélier")
    S.assigner_zone("cleF", p["id"], belier["id"])
    # le personnage doit porter son signe pour compter dans scores_zone_guilde — voir Step 3
    Z._forcer_signe_pour_tests(p["id"], "Bélier")
    resultats = Z.resoudre_toutes_zones(["Combativité", "Énergie"])
    entree = next(r for r in resultats if r["zone_id"] == belier["id"])
    assert entree["etat_resultant"] == "vaincue"
    assert Z.lire_zone(belier["id"])["etat"] == "vaincue"


def test_resoudre_toutes_zones_ignore_les_zones_deja_vaincues():
    Z.seed_zones()
    zs = Z.lister_zones()
    scorpion = next(z for z in zs if z["signe_natif"] == "Scorpion")
    with S._conn() as c:
        c.execute("UPDATE zones SET etat='vaincue' WHERE id=?", (scorpion["id"],))
    resultats = Z.resoudre_toutes_zones(["Combativité", "Énergie"])
    assert all(r["zone_id"] != scorpion["id"] for r in resultats)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_zones.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zones'`.

- [ ] **Step 3: Write `zones.py`**

Note on the test above: real characters get their `signe` from `snapshot_holistique.traditions.signe_solaire.nom` (produced by `personnages`). To keep `resoudre_toutes_zones` simple and testable, it reads the signe directly out of each character's stored snapshot — the `_forcer_signe_pour_tests` helper exists purely so the test can inject a snapshot shape without depending on the real `personnages` response format for this zones-only test; production snapshots already have this shape from Task 4.

```python
"""Zones de signe (PvE partagé) — 12 zones fixes, une par signe solaire. Nation = élément,
guilde = signe : mapping figé, mirroir de `personnages/traditions.py::ELEMENTS_SIGNE` (pure
donnée de référence, pas un recalcul du moteur)."""
from __future__ import annotations

import uuid

import stockage as S

ZONES_SEED = [
    ("Bélier", "Feu"), ("Taureau", "Terre"), ("Gémeaux", "Air"), ("Cancer", "Eau"),
    ("Lion", "Feu"), ("Vierge", "Terre"), ("Balance", "Air"), ("Scorpion", "Eau"),
    ("Sagittaire", "Feu"), ("Capricorne", "Terre"), ("Verseau", "Air"), ("Poissons", "Eau"),
]
DIFFICULTE_PAR_DEFAUT = 150


def seed_zones() -> None:
    with S._conn() as c:
        for signe, element in ZONES_SEED:
            existe = c.execute("SELECT 1 FROM zones WHERE signe_natif=?", (signe,)).fetchone()
            if existe:
                continue
            c.execute("""INSERT INTO zones (id, nom, element_natif, signe_natif,
                         difficulte_pve, etat) VALUES (?,?,?,?,?, 'en_cours')""",
                      (uuid.uuid4().hex, f"Zone du {signe}", element, signe,
                       DIFFICULTE_PAR_DEFAUT))


def _ligne_zone(r) -> dict:
    return {"id": r["id"], "nom": r["nom"], "element_natif": r["element_natif"],
            "signe_natif": r["signe_natif"], "difficulte_pve": r["difficulte_pve"],
            "etat": r["etat"]}


def lister_zones() -> list[dict]:
    with S._conn() as c:
        rows = c.execute("SELECT * FROM zones ORDER BY nom").fetchall()
    return [_ligne_zone(r) for r in rows]


def lire_zone(zone_id: str) -> dict | None:
    with S._conn() as c:
        r = c.execute("SELECT * FROM zones WHERE id=?", (zone_id,)).fetchone()
    return _ligne_zone(r) if r else None


def calculer_resolution(personnages: list[dict], stats_cles: list[str], difficulte: int) -> dict:
    """Fonction PURE : `personnages` = [{"id", "signe", "stats": {...}}]. Somme les stats
    pertinentes, tous comptes confondus, et répartit les points par guilde (signe)."""
    total = 0
    par_guilde: dict[str, int] = {}
    for p in personnages:
        contribution = sum(int(p["stats"].get(s, 0)) for s in stats_cles)
        total += contribution
        par_guilde[p["signe"]] = par_guilde.get(p["signe"], 0) + contribution
    return {"total": total, "par_guilde": par_guilde, "vaincue": total >= difficulte}


def _signe_personnage(snapshot: dict) -> str | None:
    return ((snapshot.get("traditions") or {}).get("signe_solaire") or {}).get("nom")


def _stats_personnage(snapshot: dict) -> dict:
    return (snapshot.get("portrait") or {}).get("stats") or {}


def resoudre_toutes_zones(stats_cles: list[str]) -> list[dict]:
    """Orchestration DB : pour chaque zone `en_cours`, agrège les personnages assignés,
    résout, met à jour l'état + les scores + le log. Renvoie un résumé par zone traitée."""
    resultats = []
    with S._conn() as c:
        zones_en_cours = c.execute("SELECT * FROM zones WHERE etat='en_cours'").fetchall()
        for zr in zones_en_cours:
            rows = c.execute(
                "SELECT * FROM personnages_jeu WHERE zone_actuelle=?", (zr["id"],)).fetchall()
            personnages = []
            for r in rows:
                import json
                snap = json.loads(r["snapshot_holistique"])
                signe = _signe_personnage(snap)
                if not signe:
                    continue
                personnages.append({"id": r["id"], "signe": signe, "stats": _stats_personnage(snap)})
            res = calculer_resolution(personnages, stats_cles, zr["difficulte_pve"])
            etat_resultant = "vaincue" if res["vaincue"] else "en_cours"
            if res["vaincue"]:
                c.execute("UPDATE zones SET etat='vaincue' WHERE id=?", (zr["id"],))
            for guilde, points in res["par_guilde"].items():
                c.execute("""INSERT INTO scores_zone_guilde (zone_id, guilde, points_cumules)
                             VALUES (?,?,?)
                             ON CONFLICT(zone_id, guilde) DO UPDATE SET
                             points_cumules = points_cumules + excluded.points_cumules""",
                          (zr["id"], guilde, points))
            S.log_resolution(zr["id"], None, res["par_guilde"], etat_resultant)
            resultats.append({"zone_id": zr["id"], "etat_resultant": etat_resultant, **res})
    return resultats
```

- [ ] **Step 4: Fix the test's stored-snapshot shape** — replace the `_forcer_signe_pour_tests` placeholder in Step 1 with a real fixture (this is what "Step 3 note" above refers to): update `test_resoudre_toutes_zones_marque_vaincue_et_note_le_score` to build the snapshot with the correct shape directly, no helper needed:

```python
def test_resoudre_toutes_zones_marque_vaincue_et_note_le_score():
    Z.seed_zones()
    S.assurer_joueur("cleF", "Fay")
    p = S.creer_personnage("cleF", "Ram", {"date_naissance": "1990-01-01"},
                           {"traditions": {"signe_solaire": {"nom": "Bélier"}},
                            "portrait": {"stats": {"Combativité": 200, "Énergie": 200}}})
    zs = Z.lister_zones()
    belier = next(z for z in zs if z["signe_natif"] == "Bélier")
    S.assigner_zone("cleF", p["id"], belier["id"])
    resultats = Z.resoudre_toutes_zones(["Combativité", "Énergie"])
    entree = next(r for r in resultats if r["zone_id"] == belier["id"])
    assert entree["etat_resultant"] == "vaincue"
    assert Z.lire_zone(belier["id"])["etat"] == "vaincue"
```

(Remove the `Z._forcer_signe_pour_tests(...)` line and the note about it — the corrected snapshot shape makes it unnecessary.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_zones.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/zones.py briques/jeu-factions/test_zones.py
git commit -m "feat(jeu-factions): sign zones — seed, pure PvE resolution, DB orchestration"
```

---

### Task 6: Zone routes (`GET /zones`, `GET /zones/{id}`)

**Files:**
- Modify: `briques/jeu-factions/main.py`
- Modify: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Consumes: `zones.seed_zones`, `zones.lister_zones`, `zones.lire_zone` (Task 5).
- Produces: `GET /zones`, `GET /zones/{id}` — globally readable (auth required, no tenant filter, per spec's explicit exception).

- [ ] **Step 1: Write the failing tests**

```python
# append to test_api.py
import zones


def test_lister_zones_renvoie_les_12_zones():
    zones.seed_zones()
    r = client.get("/zones")
    assert r.status_code == 200
    assert len(r.json()) == 12


def test_lire_zone():
    zones.seed_zones()
    zid = zones.lister_zones()[0]["id"]
    r = client.get(f"/zones/{zid}")
    assert r.status_code == 200
    assert r.json()["id"] == zid


def test_lire_zone_inconnue_404():
    assert client.get("/zones/inconnue").status_code == 404


def test_zones_visibles_dun_autre_tenant(monkeypatch):
    """Confirme l'exception au cloisonnement : une autre clé API voit les mêmes zones."""
    zones.seed_zones()
    r = client.get("/zones", headers={"X-API-Key": "nimporte-quelle-cle"})
    assert len(r.json()) == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v -k zone`
Expected: FAIL — 404 on `/zones` (route doesn't exist).

- [ ] **Step 3: Extend `main.py`**

```python
# add to imports
import zones


@app.on_event("startup")
def _seed_donnees_globales():
    zones.seed_zones()


@app.get("/zones", tags=["zones"])
def lister_zones_route(cle: str = Depends(cle_api)):
    return zones.lister_zones()


@app.get("/zones/{zid}", tags=["zones"])
def lire_zone_route(zid: str, cle: str = Depends(cle_api)):
    z = zones.lire_zone(zid)
    if not z:
        raise HTTPException(404, "Zone introuvable.")
    return z
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/test_api.py
git commit -m "feat(jeu-factions): zone routes — globally readable, no tenant filter"
```

---

### Task 7: Archetype paths — seed, signature stats, progression (`archetypes.py`)

**Files:**
- Create: `briques/jeu-factions/archetypes.py`
- Test: `briques/jeu-factions/test_archetypes.py`

**Interfaces:**
- Consumes: `stockage._conn` (Task 3).
- Produces: `archetypes.ARCHETYPES_SIGNATURE` (dict, 10 entries), `archetypes.seed_zones_archetype() -> None`, `archetypes.seed_competences() -> None`, `archetypes.lister_etapes(archetype: str) -> list[dict]`, `archetypes.lire_etape(zone_archetype_id: str) -> dict | None`, `archetypes.prochaine_etape(personnage_id: str, archetype: str) -> str | None`, `archetypes.calculer_resolution(membres_stats: list[dict], stats_cles: tuple, difficulte: int) -> dict` (pure), `archetypes.marquer_etape_vaincue(personnage_id: str, zone_archetype_id: str) -> None`, `archetypes.debloquer_competence_si_existe(personnage_id: str, zone_archetype_id: str) -> None`, `archetypes.lister_competences_debloquees(personnage_id: str) -> list[dict]` — all consumed by Task 9 (`groupes.py`) and Task 10 (routes).

- [ ] **Step 1: Write the failing tests**

```python
# test_archetypes.py
import archetypes as A


def test_archetypes_signature_a_10_entrees_de_3_stats():
    assert len(A.ARCHETYPES_SIGNATURE) == 10
    for stats in A.ARCHETYPES_SIGNATURE.values():
        assert len(stats) == 3


def test_seed_zones_archetype_cree_3_etapes_par_archetype():
    A.seed_zones_archetype()
    for archetype in A.ARCHETYPES_SIGNATURE:
        etapes = A.lister_etapes(archetype)
        assert len(etapes) == 3
        assert [e["ordre"] for e in etapes] == [1, 2, 3]


def test_seed_est_idempotent():
    A.seed_zones_archetype()
    A.seed_zones_archetype()
    assert len(A.lister_etapes("Le Sage Contemplatif")) == 3


def test_prochaine_etape_personnage_neuf_est_la_premiere():
    A.seed_zones_archetype()
    etapes = A.lister_etapes("Le Sage Contemplatif")
    assert A.prochaine_etape("perso-neuf", "Le Sage Contemplatif") == etapes[0]["id"]


def test_prochaine_etape_apres_completion_avance():
    A.seed_zones_archetype()
    etapes = A.lister_etapes("Le Sage Contemplatif")
    A.marquer_etape_vaincue("perso-x", etapes[0]["id"])
    assert A.prochaine_etape("perso-x", "Le Sage Contemplatif") == etapes[1]["id"]


def test_prochaine_etape_none_quand_tout_vaincu():
    A.seed_zones_archetype()
    etapes = A.lister_etapes("Le Gardien Loyal")
    for e in etapes:
        A.marquer_etape_vaincue("perso-y", e["id"])
    assert A.prochaine_etape("perso-y", "Le Gardien Loyal") is None


def test_calculer_resolution_pure():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}},
              {"personnage_id": "p2", "stats": {"Charisme": 10, "Combativité": 5, "Énergie": 5}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100)
    assert res["total"] == 110
    assert res["vaincue"] is True


def test_debloquer_competence_si_existe():
    A.seed_zones_archetype()
    A.seed_competences()
    etapes = A.lister_etapes("Le Meneur Charismatique")
    A.debloquer_competence_si_existe("perso-z", etapes[0]["id"])
    debloquees = A.lister_competences_debloquees("perso-z")
    assert len(debloquees) == 1
    assert debloquees[0]["archetype"] == "Le Meneur Charismatique"


def test_debloquer_competence_deux_fois_ne_duplique_pas():
    A.seed_zones_archetype()
    A.seed_competences()
    etapes = A.lister_etapes("Le Meneur Charismatique")
    A.debloquer_competence_si_existe("perso-w", etapes[0]["id"])
    A.debloquer_competence_si_existe("perso-w", etapes[0]["id"])
    assert len(A.lister_competences_debloquees("perso-w")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'archetypes'`.

- [ ] **Step 3: Write `archetypes.py`**

```python
"""Voies d'archétype (PvE personnel + groupe) — 10 archétypes, chacun une suite d'étapes
ordonnées non-rejouables. `ARCHETYPES_SIGNATURE` mirrore `personnages/synthese.py::_ARCHETYPES`
(donnée de référence : quelles 3 stats définissent chaque archétype — pas un recalcul)."""
from __future__ import annotations

import uuid

import stockage as S

ARCHETYPES_SIGNATURE: dict[str, tuple[str, str, str]] = {
    "Le Stratège Solitaire": ("Discrétion", "Sagesse", "Combativité"),
    "Le Meneur Charismatique": ("Charisme", "Combativité", "Énergie"),
    "Le Sage Contemplatif": ("Sagesse", "Discrétion", "Stabilité"),
    "L'Artiste Visionnaire": ("Créativité", "Émotivité", "Charisme"),
    "Le Gardien Loyal": ("Stabilité", "Émotivité", "Sagesse"),
    "L'Aventurier Indomptable": ("Énergie", "Combativité", "Charisme"),
    "Le Diplomate Sensible": ("Charisme", "Émotivité", "Sagesse"),
    "Le Bâtisseur Méthodique": ("Stabilité", "Combativité", "Discrétion"),
    "L'Âme Empathique": ("Émotivité", "Sagesse", "Créativité"),
    "L'Électron Libre": ("Créativité", "Énergie", "Discrétion"),
}

# 3 étapes par voie pour la V1 — contenu narratif à enrichir plus tard (mécanique déjà complète).
_DIFFICULTES = (80, 140, 200)
_LORE_GENERIQUE = (
    "Un premier signe se manifeste — l'appel de la voie {archetype} se fait sentir.",
    "L'épreuve s'intensifie : {archetype} doit affronter le doute avant de continuer.",
    "Le dernier seuil : accomplir ce que {archetype} porte en lui depuis le début.",
)


def seed_zones_archetype() -> None:
    with S._conn() as c:
        for archetype in ARCHETYPES_SIGNATURE:
            existe = c.execute(
                "SELECT 1 FROM zones_archetype WHERE archetype=?", (archetype,)).fetchone()
            if existe:
                continue
            for ordre, (difficulte, lore) in enumerate(zip(_DIFFICULTES, _LORE_GENERIQUE), start=1):
                c.execute("""INSERT INTO zones_archetype
                             (id, archetype, ordre, nom, difficulte_pve, texte_lore)
                             VALUES (?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, archetype, ordre,
                           f"{archetype} — étape {ordre}", difficulte,
                           lore.format(archetype=archetype)))


def seed_competences() -> None:
    with S._conn() as c:
        etapes = c.execute("SELECT * FROM zones_archetype").fetchall()
        for e in etapes:
            existe = c.execute(
                "SELECT 1 FROM competences WHERE archetype=? AND ordre_etape=?",
                (e["archetype"], e["ordre"])).fetchone()
            if existe:
                continue
            c.execute("""INSERT INTO competences (id, nom, texte, archetype, ordre_etape)
                         VALUES (?,?,?,?,?)""",
                      (uuid.uuid4().hex, f"Compétence — {e['nom']}",
                       f"Débloquée en achevant « {e['nom']} ». Effet à définir (spec combat).",
                       e["archetype"], e["ordre"]))


def _ligne_etape(r) -> dict:
    return {"id": r["id"], "archetype": r["archetype"], "ordre": r["ordre"], "nom": r["nom"],
            "difficulte_pve": r["difficulte_pve"], "texte_lore": r["texte_lore"]}


def lister_etapes(archetype: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT * FROM zones_archetype WHERE archetype=? ORDER BY ordre", (archetype,)).fetchall()
    return [_ligne_etape(r) for r in rows]


def lire_etape(zone_archetype_id: str) -> dict | None:
    with S._conn() as c:
        r = c.execute("SELECT * FROM zones_archetype WHERE id=?", (zone_archetype_id,)).fetchone()
    return _ligne_etape(r) if r else None


def prochaine_etape(personnage_id: str, archetype: str) -> str | None:
    """La première étape (ordre croissant) de cette voie qui n'est pas encore `vaincue`
    pour ce personnage. Une étape sans ligne de progression compte comme non-vaincue."""
    with S._conn() as c:
        etapes = c.execute(
            "SELECT id FROM zones_archetype WHERE archetype=? ORDER BY ordre", (archetype,)).fetchall()
        for e in etapes:
            row = c.execute(
                "SELECT etat FROM progression_archetype WHERE personnage_id=? AND zone_archetype_id=?",
                (personnage_id, e["id"])).fetchone()
            if row is None or row["etat"] != "vaincue":
                return e["id"]
    return None


def calculer_resolution(membres_stats: list[dict], stats_cles: tuple[str, str, str],
                        difficulte: int) -> dict:
    """Fonction PURE : `membres_stats` = [{"personnage_id", "stats": {...}}]."""
    total = sum(sum(int(m["stats"].get(s, 0)) for s in stats_cles) for m in membres_stats)
    return {"total": total, "vaincue": total >= difficulte}


def marquer_etape_vaincue(personnage_id: str, zone_archetype_id: str) -> None:
    with S._conn() as c:
        c.execute("""INSERT INTO progression_archetype
                     (personnage_id, zone_archetype_id, etat, date_completion)
                     VALUES (?,?, 'vaincue', datetime('now'))
                     ON CONFLICT(personnage_id, zone_archetype_id) DO UPDATE SET
                     etat='vaincue', date_completion=datetime('now')""",
                  (personnage_id, zone_archetype_id))


def debloquer_competence_si_existe(personnage_id: str, zone_archetype_id: str) -> None:
    with S._conn() as c:
        etape = c.execute("SELECT archetype, ordre FROM zones_archetype WHERE id=?",
                          (zone_archetype_id,)).fetchone()
        if not etape:
            return
        comp = c.execute("SELECT id FROM competences WHERE archetype=? AND ordre_etape=?",
                         (etape["archetype"], etape["ordre"])).fetchone()
        if not comp:
            return
        c.execute("""INSERT OR IGNORE INTO competences_debloquees
                     (personnage_id, competence_id, date) VALUES (?,?, datetime('now'))""",
                  (personnage_id, comp["id"]))


def lister_competences_debloquees(personnage_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute("""SELECT c.id, c.nom, c.texte, c.archetype, c.ordre_etape, cd.date
                            FROM competences_debloquees cd JOIN competences c ON c.id = cd.competence_id
                            WHERE cd.personnage_id=? ORDER BY cd.date""", (personnage_id,)).fetchall()
    return [{"id": r["id"], "nom": r["nom"], "texte": r["texte"], "archetype": r["archetype"],
             "ordre_etape": r["ordre_etape"], "date": r["date"]} for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/archetypes.py briques/jeu-factions/test_archetypes.py
git commit -m "feat(jeu-factions): archetype paths — seed, signature stats, sequential progression"
```

---

### Task 8: Groups — create, join, resolve (`groupes.py`)

**Files:**
- Create: `briques/jeu-factions/groupes.py`
- Test: `briques/jeu-factions/test_groupes.py`

**Interfaces:**
- Consumes: `archetypes.prochaine_etape`, `archetypes.lire_etape`, `archetypes.calculer_resolution`, `archetypes.marquer_etape_vaincue`, `archetypes.debloquer_competence_si_existe`, `archetypes.ARCHETYPES_SIGNATURE` (Task 7); `stockage._conn`, `stockage.log_resolution`, `stockage.lire_personnage` (Task 3).
- Produces: `groupes.creer_groupe(personnage_cible_id: str, zone_archetype_id: str) -> dict` (raises `ValueError` on invalid target step), `groupes.rejoindre_groupe(groupe_id: str, personnage_id: str) -> dict` (raises `ValueError` if group not `actif` or not found), `groupes.resoudre_groupes_actifs() -> list[dict]` (used by Task 11's `tick.py`) — all consumed by Task 10 (routes).

- [ ] **Step 1: Write the failing tests**

```python
# test_groupes.py
import archetypes as A
import stockage as S
import groupes as G


def _personnage(cle, nom, stats):
    S.assurer_joueur(cle, nom)
    return S.creer_personnage(cle, nom, {"date_naissance": "1990-01-01"},
                              {"traditions": {"signe_solaire": {"nom": "Lion"}},
                               "portrait": {"stats": stats}})


def test_creer_groupe_sur_la_prochaine_etape_ok():
    A.seed_zones_archetype()
    p = _personnage("cleG1", "Cible", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    assert g["personnage_cible_id"] == p["id"]
    assert g["etat"] == "actif"


def test_creer_groupe_sur_une_etape_sautee_leve_valueerror():
    A.seed_zones_archetype()
    p = _personnage("cleG2", "Sauteur", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    try:
        G.creer_groupe(p["id"], etapes[1]["id"])   # ordre 2, alors que sa prochaine est ordre 1
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass


def test_rejoindre_groupe_ok():
    A.seed_zones_archetype()
    p = _personnage("cleG3", "Cible2", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    aide = _personnage("cleG3b", "Aide", {"Charisme": 50, "Combativité": 50, "Énergie": 50})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    membre = G.rejoindre_groupe(g["id"], aide["id"])
    assert aide["id"] in membre["membres"]


def test_rejoindre_groupe_dissous_leve_valueerror():
    A.seed_zones_archetype()
    p = _personnage("cleG4", "Cible3", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    G.resoudre_groupes_actifs()   # se résout tout de suite (stats énormes) → dissous
    try:
        G.rejoindre_groupe(g["id"], p["id"])
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass


def test_resoudre_groupes_actifs_avance_la_cible_et_debloque_competence():
    A.seed_zones_archetype()
    A.seed_competences()
    p = _personnage("cleG5", "Cible4", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    G.creer_groupe(p["id"], etapes[0]["id"])
    resultats = G.resoudre_groupes_actifs()
    assert any(r["etat_resultant"] == "vaincue" for r in resultats)
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
    assert len(A.lister_competences_debloquees(p["id"])) == 1


def test_resoudre_groupes_actifs_carry_naide_pas_la_progression_de_laide():
    A.seed_zones_archetype()
    A.seed_competences()
    p = _personnage("cleG6", "Cible5", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    aide = _personnage("cleG6b", "Copain", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    G.rejoindre_groupe(g["id"], aide["id"])
    G.resoudre_groupes_actifs()
    # la cible avance grâce à l'aide du copain...
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
    # ...mais le copain (qui n'était pas à CETTE étape dans SA propre séquence, il n'a
    # jamais rien tenté) ne voit pas sa progression sauter à l'étape 2 :
    assert A.prochaine_etape(aide["id"], "Le Meneur Charismatique") == etapes[0]["id"]


def test_resoudre_groupes_actifs_pas_vaincu_reste_actif():
    A.seed_zones_archetype()
    p = _personnage("cleG7", "Faible", {"Charisme": 1, "Combativité": 1, "Énergie": 1})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    resultats = G.resoudre_groupes_actifs()
    assert all(r["etat_resultant"] == "en_cours" for r in resultats if r["groupe_id"] == g["id"])
    with S._conn() as c:
        row = c.execute("SELECT etat FROM groupes WHERE id=?", (g["id"],)).fetchone()
    assert row["etat"] == "actif"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_groupes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'groupes'`.

- [ ] **Step 3: Write `groupes.py`**

```python
"""Groupes ouverts sur une voie d'archétype — n'importe qui peut rejoindre pour aider
(« carry »), mais seuls les membres pour qui l'étape ciblée est EXACTEMENT leur propre
prochaine étape voient leur progression avancer (pas de saut, pas de re-completion)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import archetypes as A
import stockage as S


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ligne_groupe(c, groupe_id: str) -> dict:
    g = c.execute("SELECT * FROM groupes WHERE id=?", (groupe_id,)).fetchone()
    membres = [r["personnage_id"] for r in
              c.execute("SELECT personnage_id FROM membres_groupe WHERE groupe_id=?",
                       (groupe_id,)).fetchall()]
    return {"id": g["id"], "personnage_cible_id": g["personnage_cible_id"],
            "zone_archetype_id": g["zone_archetype_id"], "etat": g["etat"],
            "cree_le": g["cree_le"], "membres": membres}


def creer_groupe(personnage_cible_id: str, zone_archetype_id: str) -> dict:
    etape = A.lire_etape(zone_archetype_id)
    if not etape:
        raise ValueError("Étape d'archétype introuvable.")
    attendu = A.prochaine_etape(personnage_cible_id, etape["archetype"])
    if attendu != zone_archetype_id:
        raise ValueError("Cette étape n'est pas la prochaine de ce personnage sur cette voie.")
    gid = uuid.uuid4().hex
    cree_le = _maintenant()
    with S._conn() as c:
        c.execute("""INSERT INTO groupes (id, personnage_cible_id, zone_archetype_id, etat, cree_le)
                     VALUES (?,?,?, 'actif', ?)""",
                  (gid, personnage_cible_id, zone_archetype_id, cree_le))
        c.execute("INSERT INTO membres_groupe (groupe_id, personnage_id) VALUES (?,?)",
                 (gid, personnage_cible_id))
        return _ligne_groupe(c, gid)


def rejoindre_groupe(groupe_id: str, personnage_id: str) -> dict:
    with S._conn() as c:
        g = c.execute("SELECT etat FROM groupes WHERE id=?", (groupe_id,)).fetchone()
        if not g:
            raise ValueError("Groupe introuvable.")
        if g["etat"] != "actif":
            raise ValueError("Ce groupe n'est plus actif (déjà résolu ou dissous).")
        c.execute("INSERT OR IGNORE INTO membres_groupe (groupe_id, personnage_id) VALUES (?,?)",
                 (groupe_id, personnage_id))
        return _ligne_groupe(c, groupe_id)


def resoudre_groupes_actifs() -> list[dict]:
    """Orchestration DB — même discipline de connexions que `zones.resoudre_toutes_zones`
    (voir son docstring) : chaque lecture/écriture utilise sa PROPRE connexion courte,
    refermée avant d'appeler une fonction qui ouvre la sienne (`archetypes.py`,
    `stockage.log_resolution`). Tenir une connexion ouverte pendant ces appels imbriqués
    se verrouille elle-même (`database is locked`) — NE PAS envelopper toute la fonction
    dans un seul `with S._conn() as c:`."""
    resultats = []
    with S._conn() as c:
        groupes_actifs = c.execute("SELECT * FROM groupes WHERE etat='actif'").fetchall()
    for gr in groupes_actifs:
        etape = A.lire_etape(gr["zone_archetype_id"])
        if not etape:
            continue
        stats_cles = A.ARCHETYPES_SIGNATURE[etape["archetype"]]
        with S._conn() as c:
            membres_ids = [r["personnage_id"] for r in c.execute(
                "SELECT personnage_id FROM membres_groupe WHERE groupe_id=?", (gr["id"],)).fetchall()]
            membres_stats = []
            for mid in membres_ids:
                row = c.execute("SELECT snapshot_holistique FROM personnages_jeu WHERE id=?",
                                (mid,)).fetchone()
                if not row:
                    continue
                snap = json.loads(row["snapshot_holistique"])
                stats = (snap.get("portrait") or {}).get("stats") or {}
                membres_stats.append({"personnage_id": mid, "stats": stats})
        res = A.calculer_resolution(membres_stats, stats_cles, etape["difficulte_pve"])
        etat_resultant = "vaincue" if res["vaincue"] else "en_cours"
        if res["vaincue"]:
            for mid in membres_ids:
                if A.prochaine_etape(mid, etape["archetype"]) == gr["zone_archetype_id"]:
                    A.marquer_etape_vaincue(mid, gr["zone_archetype_id"])
                    A.debloquer_competence_si_existe(mid, gr["zone_archetype_id"])
            with S._conn() as c:
                c.execute("UPDATE groupes SET etat='dissous' WHERE id=?", (gr["id"],))
        contributions = {m["personnage_id"]: sum(int(m["stats"].get(s, 0)) for s in stats_cles)
                         for m in membres_stats}
        S.log_resolution(None, gr["zone_archetype_id"], contributions, etat_resultant)
        resultats.append({"groupe_id": gr["id"], "etat_resultant": etat_resultant, **res})
    return resultats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_groupes.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/groupes.py briques/jeu-factions/test_groupes.py
git commit -m "feat(jeu-factions): open carry groups — create/join/resolve, sequential guard"
```

---

### Task 9: Archetype/group/competence routes

**Files:**
- Modify: `briques/jeu-factions/main.py`
- Modify: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Consumes: `archetypes.ARCHETYPES_SIGNATURE`, `archetypes.seed_zones_archetype`, `archetypes.seed_competences`, `archetypes.lister_etapes`, `archetypes.lister_competences_debloquees` (Task 7); `groupes.creer_groupe`, `groupes.rejoindre_groupe` (Task 8); `stockage.lire_personnage` (Task 3).
- Produces: `GET /archetypes/{archetype}/etapes`, `POST /groupes`, `POST /groupes/{id}/rejoindre`, `GET /personnages/{id}/competences`.

- [ ] **Step 1: Write the failing tests**

```python
# append to test_api.py
import archetypes


def _seed_archetypes():
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()


def _perso(nom, cle="cleH", monkeypatch=None, **overrides):
    donnees = {"nom": nom, "date_naissance": "1990-01-01"}
    r = client.post("/personnages", json=donnees, headers={"X-API-Key": cle} if cle != "public" else {})
    return r.json()


def test_lister_etapes_archetype_inconnu_404():
    assert client.get("/archetypes/Inexistant/etapes").status_code == 404


def test_lister_etapes_archetype_connu(monkeypatch):
    _seed_archetypes()
    r = client.get("/archetypes/Le Sage Contemplatif/etapes")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_creer_groupe_et_rejoindre_via_api(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    _seed_archetypes()
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"}).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes").json()[0]
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]})
    assert r.status_code == 200
    gid = r.json()["id"]
    aide = client.post("/personnages", json={"nom": "Aide", "date_naissance": "1991-01-01"}).json()
    r2 = client.post(f"/groupes/{gid}/rejoindre", json={"personnage_id": aide["id"]})
    assert r2.status_code == 200
    assert aide["id"] in r2.json()["membres"]


def test_creer_groupe_personnage_cible_inconnu_404():
    r = client.post("/groupes", json={"personnage_cible_id": "inconnu", "zone_archetype_id": "x"})
    assert r.status_code == 404


def test_creer_groupe_etape_sautee_400(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Sage Contemplatif", "stats": {}},
        "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []})
    _seed_archetypes()
    p = client.post("/personnages", json={"nom": "Sauteur2", "date_naissance": "1990-01-01"}).json()
    etapes = client.get("/archetypes/Le Sage Contemplatif/etapes").json()
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etapes[1]["id"]})
    assert r.status_code == 400


def test_lister_competences_personnage_inconnu_404():
    assert client.get("/personnages/inconnu/competences").status_code == 404


def test_lister_competences_personnage_connu(monkeypatch):
    _patch_moteur(monkeypatch)
    p = client.post("/personnages", json={"nom": "Vide2", "date_naissance": "1990-01-01"}).json()
    r = client.get(f"/personnages/{p['id']}/competences")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v -k "groupe or etape or competence"`
Expected: FAIL — 404 on all new routes.

- [ ] **Step 3: Extend `main.py`**

```python
# add to imports
import archetypes
import groupes


class CreerGroupe(BaseModel):
    personnage_cible_id: str
    zone_archetype_id: str


class RejoindreGroupe(BaseModel):
    personnage_id: str


@app.on_event("startup")
def _seed_donnees_globales_archetypes():
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()


@app.get("/archetypes/{archetype}/etapes", tags=["archetypes"])
def lister_etapes_route(archetype: str):
    if archetype not in archetypes.ARCHETYPES_SIGNATURE:
        raise HTTPException(404, "Archétype inconnu.")
    return archetypes.lister_etapes(archetype)


@app.post("/groupes", tags=["archetypes"])
def creer_groupe_route(body: CreerGroupe, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, body.personnage_cible_id):
        raise HTTPException(404, "Personnage introuvable.")
    try:
        return groupes.creer_groupe(body.personnage_cible_id, body.zone_archetype_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/groupes/{gid}/rejoindre", tags=["archetypes"])
def rejoindre_groupe_route(gid: str, body: RejoindreGroupe, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, body.personnage_id):
        raise HTTPException(404, "Personnage introuvable.")
    try:
        return groupes.rejoindre_groupe(gid, body.personnage_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/personnages/{pid}/competences", tags=["personnages"])
def lister_competences_route(pid: str, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, pid):
        raise HTTPException(404, "Personnage introuvable.")
    return archetypes.lister_competences_debloquees(pid)
```

- [ ] **Step 4: Note the two startup hooks** — merge `_seed_donnees_globales` (Task 6) and `_seed_donnees_globales_archetypes` into a single function to avoid confusion:

```python
# replace both @app.on_event("startup") functions with one:
@app.on_event("startup")
def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/test_api.py
git commit -m "feat(jeu-factions): archetype/group/competence routes"
```

---

### Task 10: Scheduled tick (`tick.py`)

**Files:**
- Create: `briques/jeu-factions/tick.py`
- Test: `briques/jeu-factions/test_tick.py`
- Modify: `briques/jeu-factions/main.py`

**Interfaces:**
- Consumes: `zones.resoudre_toutes_zones` (Task 5), `groupes.resoudre_groupes_actifs` (Task 8).
- Produces: `tick.executer_tick() -> dict` (pure orchestration, no sleep — this is what tests call directly), `tick.boucle_tick() -> None` (the real asyncio loop, started from `main.py`'s startup event, gated by `JEU_FACTIONS_TICK_AUTOSTART`).

- [ ] **Step 1: Write the failing tests**

```python
# test_tick.py
import archetypes as A
import stockage as S
import zones as Z
import tick as T


def test_executer_tick_resout_zones_et_groupes():
    Z.seed_zones()
    A.seed_zones_archetype()
    S.assurer_joueur("cleT", "Tick")
    p = S.creer_personnage("cleT", "Tock", {"date_naissance": "1990-01-01"},
                           {"traditions": {"signe_solaire": {"nom": "Bélier"}},
                            "portrait": {"stats": {"Combativité": 300, "Énergie": 300}}})
    belier = next(z for z in Z.lister_zones() if z["signe_natif"] == "Bélier")
    S.assigner_zone("cleT", p["id"], belier["id"])
    resultat = T.executer_tick()
    assert "zones" in resultat and "groupes" in resultat
    assert any(r["zone_id"] == belier["id"] and r["etat_resultant"] == "vaincue"
              for r in resultat["zones"])


def test_executer_tick_sans_rien_a_resoudre_ne_plante_pas():
    Z.seed_zones()
    A.seed_zones_archetype()
    resultat = T.executer_tick()
    assert resultat["zones"] == [] or all(r["etat_resultant"] == "en_cours" for r in resultat["zones"])
    assert resultat["groupes"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_tick.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tick'`.

- [ ] **Step 3: Write `tick.py`**

```python
"""Résolution planifiée des zones de signe et des groupes actifs. `executer_tick()` est une
passe unique, appelée par les tests SANS sleep, et par `boucle_tick()` en production."""
import asyncio
import os

import groupes
import zones

STATS_ZONE_SIGNE = [s.strip() for s in
                    os.getenv("STATS_ZONE_SIGNE", "Combativité,Énergie").split(",") if s.strip()]
TICK_INTERVAL_HOURS = float(os.getenv("TICK_INTERVAL_HOURS", "24"))


def executer_tick() -> dict:
    return {"zones": zones.resoudre_toutes_zones(STATS_ZONE_SIGNE),
            "groupes": groupes.resoudre_groupes_actifs()}


async def boucle_tick() -> None:
    while True:
        executer_tick()
        await asyncio.sleep(TICK_INTERVAL_HOURS * 3600)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_tick.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire the loop into `main.py`'s startup, gated for tests**

```python
# add to imports
import asyncio

import tick


@app.on_event("startup")
async def _demarrer_tick():
    if os.getenv("JEU_FACTIONS_TICK_AUTOSTART", "1") != "0":
        asyncio.create_task(tick.boucle_tick())
```

(This merges with the `_seed_donnees_globales` startup function from Task 9 — FastAPI allows multiple `@app.on_event("startup")` handlers, both run.)

- [ ] **Step 6: Run the full API test suite to confirm the gated autostart doesn't break anything**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS (conftest.py sets `JEU_FACTIONS_TICK_AUTOSTART=0`, so no real 24h-sleep task starts during tests).

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions/tick.py briques/jeu-factions/test_tick.py briques/jeu-factions/main.py
git commit -m "feat(jeu-factions): scheduled tick — resolves zones + groups, gated in tests"
```

---

### Task 11: Isolation tests (tenant boundary vs. shared world)

**Files:**
- Create: `briques/jeu-factions/test_isolation.py`

**Interfaces:**
- Consumes: everything from Tasks 3, 5, 6, 7, 9 (no new production code — this task only adds a dedicated regression test, per the spec's explicit request to guard the exception).

- [ ] **Step 1: Write the tests**

```python
# test_isolation.py
"""Filet dédié : personnages/groupes restent cloisonnés par cle_api, zones/scores/étapes
restent un monde PARTAGÉ (exception délibérée documentée dans le spec — cf.
docs/superpowers/specs/2026-07-29-jeu-factions-design.md § Architecture)."""
from fastapi.testclient import TestClient

import archetypes
import zones
from main import app

client = TestClient(app)


def test_personnage_invisible_pour_un_autre_tenant():
    r = client.post("/personnages", json={"nom": "Secret", "date_naissance": "1990-01-01"},
                    headers={"X-API-Key": "tenant-a"})
    pid = r.json()["id"]
    assert client.get(f"/personnages/{pid}", headers={"X-API-Key": "tenant-a"}).status_code == 200
    assert client.get(f"/personnages/{pid}", headers={"X-API-Key": "tenant-b"}).status_code == 404
    assert not any(p["id"] == pid for p in
                  client.get("/personnages", headers={"X-API-Key": "tenant-b"}).json())


def test_zones_identiques_pour_tous_les_tenants():
    zones.seed_zones()
    a = client.get("/zones", headers={"X-API-Key": "tenant-a"}).json()
    b = client.get("/zones", headers={"X-API-Key": "tenant-b"}).json()
    assert {z["id"] for z in a} == {z["id"] for z in b}


def test_etapes_archetype_identiques_pour_tous_les_tenants():
    archetypes.seed_zones_archetype()
    a = client.get("/archetypes/Le Sage Contemplatif/etapes",
                   headers={"X-API-Key": "tenant-a"}).json()
    b = client.get("/archetypes/Le Sage Contemplatif/etapes",
                   headers={"X-API-Key": "tenant-b"}).json()
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_groupe_dun_tenant_pas_manipulable_par_un_autre():
    """Un joueur ne peut pas créer un groupe pour un personnage qu'il ne possède pas —
    même si ce personnage existe (appartient à un autre tenant)."""
    r = client.post("/personnages", json={"nom": "AutreTenant", "date_naissance": "1990-01-01"},
                    headers={"X-API-Key": "tenant-c"})
    pid = r.json()["id"]
    archetypes.seed_zones_archetype()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes").json()[0]
    r2 = client.post("/groupes", json={"personnage_cible_id": pid, "zone_archetype_id": etape["id"]},
                     headers={"X-API-Key": "tenant-d"})
    assert r2.status_code == 404
```

- [ ] **Step 2: Run tests to verify they pass** (no new production code needed — this task documents and locks in behavior already built)

Run: `cd briques/jeu-factions && python -m pytest test_isolation.py -v`
Expected: PASS (4 tests). If any fails, it means an earlier task's ownership check is missing — go back and fix that task before continuing.

- [ ] **Step 3: Commit**

```bash
git add briques/jeu-factions/test_isolation.py
git commit -m "test(jeu-factions): dedicated isolation regression — tenant vs shared-world boundary"
```

---

### Task 12: Minimal front-end (no build step)

**Files:**
- Create: `briques/jeu-factions/front.html`
- Copy: `briques/jeu-factions/workplace.css` (from `briques/personnages/workplace.css`)
- Modify: `briques/jeu-factions/main.py`
- Test: `briques/jeu-factions/test_front.py`

**Interfaces:**
- Consumes: all routes from Tasks 4, 6, 9.
- Produces: `GET /` (serves `front.html`), `GET /workplace.css`.

- [ ] **Step 1: Copy the shared stylesheet**

```bash
cp briques/personnages/workplace.css briques/jeu-factions/workplace.css
```

- [ ] **Step 2: Write the failing test**

```python
# test_front.py
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_accueil_sert_le_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd briques/jeu-factions && python -m pytest test_front.py -v`
Expected: FAIL — 404 on `/`.

- [ ] **Step 4: Write `front.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Jeu-factions</title>
<link rel="stylesheet" href="/workplace.css">
</head>
<body>
<h1>Jeu-factions — factions &amp; territoire (PvE)</h1>

<section id="creation">
  <h2>Créer un personnage</h2>
  <label><input type="radio" name="mode" value="date" checked> Par date de naissance</label>
  <label><input type="radio" name="mode" value="description"> Par description</label>
  <form id="formCreation">
    <input id="nom" placeholder="Nom du personnage" required>
    <div id="champsDate">
      <input id="date_naissance" type="date">
    </div>
    <div id="champsDescription" style="display:none">
      <textarea id="description" placeholder="Décris le caractère..."></textarea>
    </div>
    <button type="submit">Créer</button>
  </form>
  <pre id="resultatCreation"></pre>
</section>

<section id="mesPersonnages">
  <h2>Mes personnages</h2>
  <ul id="listePersonnages"></ul>
</section>

<section id="zones">
  <h2>Zones de signe (PvE partagé)</h2>
  <ul id="listeZones"></ul>
</section>

<script>
const cleApi = localStorage.getItem("jeu_factions_cle") || "";
const entetes = () => cleApi ? {"X-API-Key": cleApi, "Content-Type": "application/json"}
                             : {"Content-Type": "application/json"};

document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", e => {
  document.getElementById("champsDate").style.display = e.target.value === "date" ? "block" : "none";
  document.getElementById("champsDescription").style.display = e.target.value === "description" ? "block" : "none";
}));

document.getElementById("formCreation").addEventListener("submit", async e => {
  e.preventDefault();
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const corps = {nom: document.getElementById("nom").value};
  if (mode === "date") corps.date_naissance = document.getElementById("date_naissance").value;
  else corps.description = document.getElementById("description").value;
  const r = await fetch("/personnages", {method: "POST", headers: entetes(), body: JSON.stringify(corps)});
  document.getElementById("resultatCreation").textContent = JSON.stringify(await r.json(), null, 2);
  chargerPersonnages();
});

async function chargerPersonnages() {
  const r = await fetch("/personnages", {headers: entetes()});
  const items = await r.json();
  document.getElementById("listePersonnages").innerHTML = items.map(p =>
    `<li>${p.nom} — ${(p.snapshot_holistique.portrait || {}).archetype || "?"} (zone: ${p.zone_actuelle || "aucune"})</li>`
  ).join("");
}

async function chargerZones() {
  const r = await fetch("/zones", {headers: entetes()});
  const items = await r.json();
  document.getElementById("listeZones").innerHTML = items.map(z =>
    `<li>${z.nom} (${z.element_natif}) — ${z.etat}</li>`
  ).join("");
}

chargerPersonnages();
chargerZones();
</script>
</body>
</html>
```

- [ ] **Step 5: Serve the front in `main.py`**

```python
# add to imports
from fastapi.responses import FileResponse


@app.get("/", response_class=FileResponse, include_in_schema=False)
def accueil():
    return FileResponse("front.html")


@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse("workplace.css")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_front.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions/front.html briques/jeu-factions/workplace.css briques/jeu-factions/main.py briques/jeu-factions/test_front.py
git commit -m "feat(jeu-factions): minimal no-build front — character creation + zones view"
```

---

### Task 13: Wire into the launcher, capacités, README, full smoke pass

**Files:**
- Modify: `Lancer Workplace.command`
- Modify: `briques/jeu-factions/manifest.json`
- Create: `briques/jeu-factions/README.md`

**Interfaces:**
- Consumes: everything (this is the integration/wiring task).

- [ ] **Step 1: Add capacités to `manifest.json`** (read-only ones first, per `GUIDE-ajouter-un-outil.md` convention — `action:false` for GET, `action:true` for anything that writes)

```json
"capacites": [
  {
    "nom": "jeu_factions_lister_personnages",
    "description": "Liste les personnages de jeu du compte courant, avec leur élément/signe/archétype et zone actuelle.",
    "methode": "GET",
    "chemin": "/personnages",
    "params": {},
    "action": false
  },
  {
    "nom": "jeu_factions_lister_zones",
    "description": "Liste les 12 zones de signe (PvE partagé) et leur état (en cours / vaincue).",
    "methode": "GET",
    "chemin": "/zones",
    "params": {},
    "action": false
  },
  {
    "nom": "jeu_factions_creer_personnage",
    "description": "Crée un nouveau personnage de jeu, par date de naissance ou par description de caractère. À n'appeler qu'après accord explicite de l'utilisateur.",
    "methode": "POST",
    "chemin": "/personnages",
    "params": {
      "nom": {"type": "string", "description": "Nom du personnage."},
      "date_naissance": {"type": "string", "description": "Date de naissance YYYY-MM-DD (optionnel si description fournie)."},
      "description": {"type": "string", "description": "Description du caractère souhaité (optionnel si date fournie)."}
    },
    "action": true
  }
]
```

- [ ] **Step 2: Add the launcher line** — open `Lancer Workplace.command`, find the `briques` list (same list documented in `GUIDE-ajouter-une-brique.md` §4), add, **before** `core` (this brick doesn't call the Cœur):

```
"jeu-factions|$RACINE/briques/jeu-factions|http://localhost:6210/sante"
```

- [ ] **Step 3: Write `README.md`**

```markdown
# jeu-factions — création de personnage + factions/territoire (PvE)

Premier sous-projet du jeu holistique (voir `docs/superpowers/specs/2026-07-29-jeu-factions-design.md`).
Réutilise le moteur de `personnages` (5900) en HTTP — aucun calcul de tradition/stat dupliqué ici.

## Démarrer

```bash
docker compose up -d --build      # API sur http://localhost:6210
curl localhost:6210/sante
```

## Concepts

- **Nation** = élément du signe solaire (Feu/Terre/Air/Eau).
- **Guilde** = signe solaire (12).
- **Classe** = archétype calculé (10) — orthogonal à la politique.
- **Zones de signe** (12) : PvE **partagé**, tous comptes confondus, pas de possession exclusive (pas de PvP dans ce spec).
- **Voies d'archétype** (10 × 3 étapes) : PvE **personnel et séquentiel**, non-rejouable une fois vaincu. Groupes ouverts : n'importe qui peut aider (« carry »), mais seul celui pour qui l'étape est sa PROCHAINE progresse réellement.

## Exception au cloisonnement

Contrairement au reste de Workplace, `/zones` et `/archetypes/*/etapes` sont un **monde partagé** : toute clé API valide les voit toutes. Seuls `/personnages` et `/groupes` restent cloisonnés par propriétaire. Voir le spec pour la justification.

## Non fait ici (specs séparés à venir)

Combat temps réel, PvP, vrais comptes/hébergement public, progression idle, effets de compétences, lore riche.

## Tests

```bash
python -m pytest -q
```
```

- [ ] **Step 4: Run the full test suite for the brick**

Run: `cd briques/jeu-factions && python -m pytest -v`
Expected: PASS — every test file from Tasks 1–12.

- [ ] **Step 5: Run the repo-wide smoke test**

Run (from the repo root — the worktree root, NOT the original checkout path): `python -m pytest tests/test_briques_smoke.py -v`
Expected: PASS — manifest valid, port 6210 unique, `/sante` reachable path declared correctly.

- [ ] **Step 6: Build and boot the brick standalone, prove health end-to-end**

Run:
```bash
cd briques/jeu-factions && docker compose up -d --build
curl http://localhost:6210/sante
```
Expected: `{"statut":"ok"}`.

- [ ] **Step 7: Commit**

```bash
git add "Lancer Workplace.command" briques/jeu-factions/manifest.json briques/jeu-factions/README.md
git commit -m "feat(jeu-factions): wire into launcher, add assistant capacités, README"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-29-jeu-factions-design.md`):
- Architecture (brick, port, no engine duplication, SQLite, internal tick) → Tasks 1, 2, 10.
- Tenant exception (zones/scores/etapes global, personnages/groupes owner-only) → Tasks 6, 9, 11.
- Full data model (11 tables) → Task 3 (`stockage._conn`), seeded in Tasks 5 & 7.
- Moteur holistique mapping (nation/guilde/classe, signature stats) → Tasks 5, 7.
- Character creation flow (both paths, snapshot freeze, 503 on failure) → Tasks 2, 4.
- Sign-zone flow (assignment, no-op on already-defeated, tick resolution, guild scores) → Tasks 4, 5, 10.
- Archetype-path flow (sequential, groups, carry, competence unlock) → Tasks 7, 8, 9.
- API surface (all 10 routes) → Tasks 4, 6, 9.
- Edge cases (503, skip-step 400, already-resolved-group 400) → Tasks 2, 8, 9.
- Tests (mocked HTTP, pure resolution functions, group edge cases, isolation) → Tasks 2, 5, 7, 8, 11.
- No gaps found.

**Placeholder scan:** no `TBD`/`TODO` in any step; every code block is complete and runnable as written.

**Type consistency check:** `moteur_personnages.portrait`/`recherche_inverse` signatures (Task 2) match their usage in `main.py` (Task 4). `stockage.creer_personnage(cle_api, nom, donnees_naissance, snapshot)` signature is identical across Tasks 3, 4, 5, 8. `zones.calculer_resolution`/`archetypes.calculer_resolution` both return `{"total", "vaincue", ...}` and are used consistently in `resoudre_toutes_zones`/`resoudre_groupes_actifs`. `archetypes.prochaine_etape(personnage_id, archetype)` is called identically in Tasks 7, 8, 9. `groupes.creer_groupe`/`rejoindre_groupe` raise `ValueError` consistently, caught the same way in Task 9's routes.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-29-jeu-factions.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
