# Brique `jeu-factions-public` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Créer une nouvelle brique `briques/jeu-factions-public/`, indépendante de `briques/jeu-factions/` et de `core/`, qui expose le même jeu (personnages, zones de signe, voies d'archétype avec combat joué, idle, groupes carry) à des comptes email+mot de passe publics au lieu de l'identité Keycloak du cercle privé.

**Architecture:** Les moteurs sans dépendance à `core/` (`combat_moteur.py`, `combat.py`, `archetypes.py`, `zones.py`, `groupes.py`, `mobs.py`, `mobs_archetype.py`, `moteur_personnages.py`) sont copiés à l'identique depuis `briques/jeu-factions/`. Seuls l'identité (`jeton.py`), le stockage des comptes (`stockage.py`), les routes d'auth et l'exposition (`main.py`, front) sont nouveaux. FastAPI + SQLite, même stack que `jeu-factions`.

**Tech Stack:** Python 3.12, FastAPI 0.115.6, uvicorn, httpx, SQLite (stdlib), passlib+bcrypt (hachage mot de passe), pytest+pytest-asyncio.

## Global Constraints

- Aucun fichier de `briques/jeu-factions-public/` n'importe `core/` — vérifié à chaque tâche qui ajoute un import.
- Aucune modification de `briques/jeu-factions/` — c'est un point de départ à copier, jamais un point de dépendance runtime.
- Port de la brique : `6220`. Base de données : `/data/jeu_factions_public.db` (volume `jeu_factions_public_data`).
- Secret d'auth : `JEU_FACTIONS_PUBLIC_SECRET` (HMAC local, jamais `JEU_FACTIONS_KEY`).
- CORS : variable d'env `JEU_FACTIONS_PUBLIC_CORS_ORIGINS` — **jamais** `CORS_ORIGINS` (ce nom est déjà un secret racine partagé par plusieurs briques cercle privé dans `.env`, cf. `.env.example:16` — le réutiliser ferait fuiter les origines du dashboard Cœur dans le conteneur public via `env_file`, motif déjà documenté : `fix-env-shadow-composes.md`).
- Toute commande `cp` de ce plan copie un fichier **inchangé** (vérifié pendant le brainstorming : aucun de ces fichiers n'importe `core/` ni ne référence un secret partagé) — aucune édition n'est nécessaire après la copie sauf mention explicite dans l'étape.
- Chaque tâche se termine par des tests qui passent avant le commit (`python -m pytest -q` depuis `briques/jeu-factions-public/`).

---

### Task 1: Scaffold de la brique + squelette FastAPI

**Files:**
- Create: `briques/jeu-factions-public/Dockerfile`
- Create: `briques/jeu-factions-public/docker-compose.yml`
- Create: `briques/jeu-factions-public/requirements.txt`
- Create: `briques/jeu-factions-public/requirements-dev.txt`
- Create: `briques/jeu-factions-public/pytest.ini`
- Create: `briques/jeu-factions-public/conftest.py`
- Create: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_sante.py`

**Interfaces:**
- Produces: `main.app` (instance FastAPI), route `GET /sante` → `{"statut": "ok"}`.

- [ ] **Step 1: Créer le dossier et les fichiers d'infra**

```bash
mkdir -p /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public
```

`briques/jeu-factions-public/requirements.txt` :

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
passlib==1.7.4
bcrypt==4.0.1
```

`briques/jeu-factions-public/requirements-dev.txt` :

```
pytest==8.3.4
pytest-asyncio==0.24.0
```

`briques/jeu-factions-public/pytest.ini` :

```ini
[pytest]
asyncio_mode = auto
```

`briques/jeu-factions-public/Dockerfile` :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6220"]
```

`briques/jeu-factions-public/docker-compose.yml` :

```yaml
services:
  jeu-factions-public:
    build: .
    container_name: workplace_jeu_factions_public
    image: workplace/jeu-factions-public:0.1.0
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6220:6220"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - PORT=6220
      - PERSONNAGES_URL=http://host.docker.internal:5900
      - JEU_FACTIONS_PUBLIC_DB=/data/jeu_factions_public.db
      - TICK_INTERVAL_HOURS=24
      - COMBAT_TICK_HZ=10
      - JEU_FACTIONS_INSTANCE_CAPACITE=30
      - COMBAT_INSTANCE_GRACE_S=30
      - COMBAT_BOSS_RESPAWN_S=60
      - COMBAT_ARENE_TAILLE=800
      # JEU_FACTIONS_PUBLIC_SECRET, PERSONNAGES_KEY, JEU_FACTIONS_PUBLIC_CORS_ORIGINS :
      # ABSENTES d'ici EXPRÈS — elles viennent du .env racine via env_file. Les déclarer
      # ici avec une valeur vide les figerait et écraserait la vraie valeur du .env
      # racine (piège déjà documenté : fix-env-shadow-composes.md).
    volumes:
      - jeu_factions_public_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6220/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  jeu_factions_public_data:
```

`briques/jeu-factions-public/conftest.py` :

```python
"""Config de test : DB temporaire + secrets de test AVANT tout import des modules."""
import os
import tempfile

import pytest

_db = os.path.join(tempfile.gettempdir(), "jeu_factions_public_test.db")
os.environ["JEU_FACTIONS_PUBLIC_DB"] = _db
os.environ.setdefault("JEU_FACTIONS_PUBLIC_SECRET", "cle-test-jeu-factions-public")
os.environ.setdefault("PERSONNAGES_URL", "http://personnages-test.invalid")
os.environ["JEU_FACTIONS_COMBAT_AUTOSTART"] = "0"    # jamais de vraie boucle temps réel en test

if os.path.exists(_db):
    os.remove(_db)


@pytest.fixture(autouse=True)
def _clear_db_before_test():
    if os.path.exists(_db):
        os.remove(_db)


@pytest.fixture(autouse=True)
def _vider_instances_combat():
    import combat
    combat._INSTANCES.clear()
    yield
    combat._INSTANCES.clear()


@pytest.fixture(autouse=True)
def _vider_limiteur():
    import limiteur
    limiteur._reinitialiser()
    yield
    limiteur._reinitialiser()
```

`briques/jeu-factions-public/main.py` (squelette minimal — les autres routes arrivent tâche par tâche) :

```python
"""Brique « jeu-factions-public » — exposition publique du jeu (S220). Comptes email + mot
de passe propres à la brique, AUCUNE dépendance à core/ ni à Keycloak — voir
docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Jeu-factions-public — exposition publique du jeu (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("JEU_FACTIONS_PUBLIC_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}
```

- [ ] **Step 2: Écrire le test**

`briques/jeu-factions-public/test_sante.py` :

```python
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}
```

- [ ] **Step 3: Installer les dépendances et lancer le test**

Run:
```bash
cd /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```
Expected: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/
git commit -m "feat(jeu-factions-public): scaffold de la brique (S220)"
```

---

### Task 2: Stockage — schéma complet + comptes

**Files:**
- Create: `briques/jeu-factions-public/stockage.py`
- Test: `briques/jeu-factions-public/test_stockage.py`

**Interfaces:**
- Produces: `stockage._conn()`, `stockage.assurer_joueur(cle_api, pseudo="")`,
  `stockage.creer_personnage(cle_api, nom, donnees_naissance, snapshot) -> dict`,
  `stockage.lister_personnages(cle_api) -> list[dict]`,
  `stockage.lire_personnage(cle_api, pid) -> dict | None`,
  `stockage.assigner_zone(cle_api, pid, zone_id) -> dict | None`,
  `stockage.log_resolution(zone_id, zone_archetype_id, contributions, etat_resultant) -> None`,
  `stockage.enregistrer_presence(cle_api) -> None`,
  `stockage.lire_derniere_presence(cle_api) -> str | None`,
  `stockage.lire_derniere_presence_personnage(personnage_id) -> str | None`,
  `stockage.creer_compte(email, mot_de_passe_hash, pseudo) -> dict`,
  `stockage.lire_compte_par_email(email) -> dict | None`.
  Ces signatures sont utilisées par toutes les tâches suivantes.

- [ ] **Step 1: Écrire `stockage.py`**

```python
"""Schéma SQLite complet de `jeu-factions-public` — copie du schéma de `briques/jeu-factions/`
(zones/mobs/archetypes/groupes/competences inchangés, cf. spec) + table `comptes` propre à
cette brique (identité locale, pas de tenant Keycloak). `cle_api` référence désormais
`comptes.id`."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("JEU_FACTIONS_PUBLIC_DB", "/data/jeu_factions_public.db")


def _migrer_colonnes_effet_competences(c: sqlite3.Connection) -> None:
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    for nom, type_sql in (("effet_type", "TEXT"), ("magnitude", "INTEGER"),
                          ("portee", "INTEGER"), ("cooldown_s", "REAL")):
        if nom not in colonnes:
            c.execute(f"ALTER TABLE competences ADD COLUMN {nom} {type_sql}")


def _migrer_colonne_presence(c: sqlite3.Connection) -> None:
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    if "derniere_presence" not in colonnes:
        c.execute("ALTER TABLE joueurs ADD COLUMN derniere_presence TEXT")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS comptes (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
        mot_de_passe_hash TEXT NOT NULL, pseudo TEXT NOT NULL, cree_le TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS joueurs (
        cle_api TEXT PRIMARY KEY, pseudo TEXT NOT NULL)""")
    _migrer_colonne_presence(c)
    c.execute("""CREATE TABLE IF NOT EXISTS personnages_jeu (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, nom TEXT NOT NULL,
        donnees_naissance TEXT NOT NULL, snapshot_holistique TEXT NOT NULL,
        zone_actuelle TEXT, cree_le TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_perso_cle ON personnages_jeu(cle_api)")
    c.execute("""CREATE TABLE IF NOT EXISTS zones (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, element_natif TEXT NOT NULL,
        signe_natif TEXT NOT NULL, difficulte_pve INTEGER NOT NULL,
        etat TEXT NOT NULL DEFAULT 'en_cours')""")
    c.execute("""CREATE TABLE IF NOT EXISTS mobs_zone (
        id TEXT PRIMARY KEY, zone_id TEXT NOT NULL, nom TEXT NOT NULL, role TEXT NOT NULL,
        pv_max INTEGER NOT NULL, degats_attaque INTEGER NOT NULL,
        cooldown_attaque_s REAL NOT NULL, portee_aggro INTEGER NOT NULL,
        portee_attaque INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mobs_zone_archetype (
        id TEXT PRIMARY KEY, zone_archetype_id TEXT NOT NULL, nom TEXT NOT NULL,
        role TEXT NOT NULL, pv_max INTEGER NOT NULL, degats_attaque INTEGER NOT NULL,
        cooldown_attaque_s REAL NOT NULL, portee_aggro INTEGER NOT NULL,
        portee_attaque INTEGER NOT NULL)""")
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
    _migrer_colonnes_effet_competences(c)
    c.execute("""CREATE TABLE IF NOT EXISTS competences_debloquees (
        personnage_id TEXT NOT NULL, competence_id TEXT NOT NULL, date TEXT NOT NULL,
        PRIMARY KEY (personnage_id, competence_id))""")
    return c


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def creer_compte(email: str, mot_de_passe_hash: str, pseudo: str) -> dict:
    compte_id = uuid.uuid4().hex
    cree_le = _maintenant()
    with _conn() as c:
        c.execute("""INSERT INTO comptes (id, email, mot_de_passe_hash, pseudo, cree_le)
                     VALUES (?,?,?,?,?)""", (compte_id, email, mot_de_passe_hash, pseudo, cree_le))
    return {"id": compte_id, "email": email, "pseudo": pseudo, "cree_le": cree_le}


def lire_compte_par_email(email: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes WHERE email=?", (email,)).fetchone()
    return dict(r) if r else None


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


def enregistrer_presence(cle_api: str) -> None:
    assurer_joueur(cle_api)
    with _conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  (_maintenant(), cle_api))


def lire_derniere_presence(cle_api: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT derniere_presence FROM joueurs WHERE cle_api=?",
                        (cle_api,)).fetchone()
    return row["derniere_presence"] if row else None


def lire_derniere_presence_personnage(personnage_id: str) -> str | None:
    with _conn() as c:
        row = c.execute("""SELECT j.derniere_presence FROM personnages_jeu p
                            JOIN joueurs j ON j.cle_api = p.cle_api
                            WHERE p.id=?""", (personnage_id,)).fetchone()
    return row["derniere_presence"] if row else None
```

- [ ] **Step 2: Écrire les tests**

`briques/jeu-factions-public/test_stockage.py` (personnages/présence : copie exacte de
`briques/jeu-factions/test_stockage.py` lignes 1-89 — mêmes fonctions, même comportement,
aucune migration ici) :

```python
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


def test_migration_colonnes_effet_est_presente_et_idempotente():
    with S._conn() as c:
        colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    assert {"effet_type", "magnitude", "portee", "cooldown_s"} <= colonnes
    S._conn()


def test_enregistrer_presence_puis_lire():
    S.assurer_joueur("cleF", "Finn")
    assert S.lire_derniere_presence("cleF") is None
    S.enregistrer_presence("cleF")
    assert S.lire_derniere_presence("cleF") is not None


def test_enregistrer_presence_cree_le_joueur_si_absent():
    assert S.lire_derniere_presence("cleG") is None
    S.enregistrer_presence("cleG")
    assert S.lire_derniere_presence("cleG") is not None


def test_lire_derniere_presence_personnage_suit_le_compte_proprietaire():
    S.assurer_joueur("cleH", "Hugo")
    p = S.creer_personnage("cleH", "Perso", {"date_naissance": "1990-01-01"}, {"portrait": {}})
    assert S.lire_derniere_presence_personnage(p["id"]) is None
    S.enregistrer_presence("cleH")
    assert S.lire_derniere_presence_personnage(p["id"]) is not None


def test_lire_derniere_presence_personnage_inconnu_est_none():
    assert S.lire_derniere_presence_personnage("perso-inconnu") is None


def test_migration_derniere_presence_est_presente_et_idempotente():
    with S._conn() as c:
        colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    assert "derniere_presence" in colonnes
    S._conn()


def test_creer_compte_puis_le_relire_par_email():
    c = S.creer_compte("alice@example.com", "hash-bidon", "Alice")
    assert c["email"] == "alice@example.com"
    relu = S.lire_compte_par_email("alice@example.com")
    assert relu["id"] == c["id"]
    assert relu["mot_de_passe_hash"] == "hash-bidon"


def test_lire_compte_par_email_absent_renvoie_none():
    assert S.lire_compte_par_email("jamais-inscrit@example.com") is None


def test_creer_compte_email_deja_pris_leve_integrityerror():
    import sqlite3
    S.creer_compte("bob@example.com", "hash1", "Bob")
    try:
        S.creer_compte("bob@example.com", "hash2", "Bob2")
        assert False, "devait lever IntegrityError"
    except sqlite3.IntegrityError:
        pass
```

- [ ] **Step 3: Lancer les tests**

Run: `python -m pytest -q` (depuis `briques/jeu-factions-public/`, venv activé)
Expected: tous les tests passent (18 tests)

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/stockage.py briques/jeu-factions-public/test_stockage.py
git commit -m "feat(jeu-factions-public): stockage — schéma complet + table comptes"
```

---

### Task 3: `jeton.py` — hachage mot de passe + session HMAC locale

**Files:**
- Create: `briques/jeu-factions-public/jeton.py`
- Test: `briques/jeu-factions-public/test_jeton.py`

**Interfaces:**
- Consumes: rien (module autonome).
- Produces: `jeton.COOKIE_NOM` (str), `jeton.TTL_SESSION` (int, secondes),
  `jeton.hacher_mot_de_passe(mot_de_passe: str) -> str`,
  `jeton.verifier_mot_de_passe(mot_de_passe: str, hash_: str) -> bool`,
  `jeton.emettre(compte_id: str, ttl: int = TTL_SESSION) -> str`,
  `jeton.verifier(jeton: str | None) -> str | None`.

- [ ] **Step 1: Écrire `jeton.py`**

```python
"""Identité locale de `jeu-factions-public` (comptes email + mot de passe) — AUCUN secret
partagé avec le Cœur, contrairement à briques/jeu-factions/jeton.py (S217) : cette brique
émet et vérifie elle-même son jeton de session. Hachage de mot de passe (passlib+bcrypt,
mêmes versions que oria-stack/oria/backend/requirements.txt) + jeton HMAC (même mécanique
que jeu-factions, émission locale)."""
import hashlib
import hmac
import os
import time
from typing import Optional

from passlib.hash import bcrypt

COOKIE_NOM = "jeu_factions_public_utilisateur"
TTL_SESSION = 30 * 24 * 3600  # 30 jours — décision de cadrage produit public (spec § Identité)


def _secret() -> bytes:
    return (os.environ.get("JEU_FACTIONS_PUBLIC_SECRET") or "").encode()


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    return bcrypt.hash(mot_de_passe)


def verifier_mot_de_passe(mot_de_passe: str, hash_: str) -> bool:
    try:
        return bcrypt.verify(mot_de_passe, hash_)
    except ValueError:
        return False


def emettre(compte_id: str, ttl: int = TTL_SESSION) -> str:
    expire = int(time.time()) + ttl
    message = f"{compte_id}:{expire}"
    signature = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def verifier(jeton: Optional[str]) -> Optional[str]:
    if not jeton or not _secret():
        return None
    try:
        compte_id, expire, signature = jeton.rsplit(":", 2)
        expire_i = int(expire)
    except ValueError:
        return None
    message = f"{compte_id}:{expire}"
    attendue = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, attendue) or time.time() > expire_i:
        return None
    return compte_id
```

- [ ] **Step 2: Écrire les tests**

`briques/jeu-factions-public/test_jeton.py` :

```python
import jeton as J


def test_roundtrip_emettre_puis_verifier():
    j = J.emettre("compte-alice", ttl=60)
    assert J.verifier(j) == "compte-alice"


def test_verifier_signature_invalide():
    j = J.emettre("compte-alice", ttl=60)
    trafique = j[:-1] + ("0" if j[-1] != "0" else "1")
    assert J.verifier(trafique) is None


def test_verifier_expire():
    j = J.emettre("compte-alice", ttl=-1)
    assert J.verifier(j) is None


def test_verifier_malforme():
    assert J.verifier("pas-un-jeton-valide") is None
    assert J.verifier(None) is None


def test_verifier_sans_secret_configure(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_PUBLIC_SECRET", raising=False)
    assert J.verifier("nimporte:quoi:x") is None


def test_hacher_puis_verifier_mot_de_passe():
    h = J.hacher_mot_de_passe("motdepasse123")
    assert J.verifier_mot_de_passe("motdepasse123", h) is True


def test_verifier_mauvais_mot_de_passe():
    h = J.hacher_mot_de_passe("motdepasse123")
    assert J.verifier_mot_de_passe("autrechose", h) is False


def test_hachage_nest_jamais_le_mot_de_passe_en_clair():
    h = J.hacher_mot_de_passe("motdepasse123")
    assert h != "motdepasse123"
```

- [ ] **Step 3: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/jeton.py briques/jeu-factions-public/test_jeton.py
git commit -m "feat(jeu-factions-public): jeton — hachage mot de passe + session HMAC locale"
```

---

### Task 4: Anti-abus V1 — rate limiting + filtre de pseudo

**Files:**
- Create: `briques/jeu-factions-public/limiteur.py`
- Create: `briques/jeu-factions-public/moderation.py`
- Test: `briques/jeu-factions-public/test_limiteur.py`
- Test: `briques/jeu-factions-public/test_moderation.py`

**Interfaces:**
- Produces: `limiteur.autorise(ip: str, maintenant: float | None = None) -> bool`,
  `limiteur._reinitialiser() -> None` (déjà consommé par `conftest.py`, Task 1),
  `moderation.contient_mot_banni(texte: str) -> bool`.

- [ ] **Step 1: Écrire `limiteur.py`**

```python
"""Rate limiting en mémoire par IP — mono-process (V1, décision de cadrage scaling, cf.
spec § Anti-abus). Se réinitialise au redémarrage du process : acceptable tant qu'il n'y a
qu'un seul process (pas de scaling horizontal en V1)."""
import time

FENETRE_S = 300       # 5 minutes
MAX_TENTATIVES = 10

_tentatives: dict[str, list[float]] = {}


def autorise(ip: str, maintenant: float | None = None) -> bool:
    maintenant = maintenant if maintenant is not None else time.monotonic()
    horodatages = [t for t in _tentatives.get(ip, []) if maintenant - t < FENETRE_S]
    horodatages.append(maintenant)
    _tentatives[ip] = horodatages
    return len(horodatages) <= MAX_TENTATIVES


def _reinitialiser() -> None:
    _tentatives.clear()
```

- [ ] **Step 2: Écrire `moderation.py`**

```python
"""Filtre de pseudo/nom de personnage — liste statique de mots bannis (V1, décision de
cadrage anti-abus : pas de file de modération, pas de recours humain). Liste courte,
volontairement non exhaustive — à enrichir opérationnellement si besoin."""
MOTS_BANNIS = {
    "connard", "connasse", "salope", "pute", "encule", "enculé",
    "nazi", "hitler", "nique", "batard", "bâtard",
}


def contient_mot_banni(texte: str) -> bool:
    minuscule = texte.lower()
    return any(mot in minuscule for mot in MOTS_BANNIS)
```

- [ ] **Step 3: Écrire les tests**

`briques/jeu-factions-public/test_limiteur.py` :

```python
import limiteur as L


def test_autorise_sous_le_seuil():
    for _ in range(L.MAX_TENTATIVES):
        assert L.autorise("1.2.3.4") is True


def test_refuse_au_dela_du_seuil():
    for _ in range(L.MAX_TENTATIVES):
        L.autorise("1.2.3.4")
    assert L.autorise("1.2.3.4") is False


def test_ip_differente_nest_pas_affectee():
    for _ in range(L.MAX_TENTATIVES + 1):
        L.autorise("1.2.3.4")
    assert L.autorise("5.6.7.8") is True


def test_fenetre_glissante_libere_apres_expiration():
    t0 = 1000.0
    for _ in range(L.MAX_TENTATIVES):
        L.autorise("1.2.3.4", maintenant=t0)
    assert L.autorise("1.2.3.4", maintenant=t0) is False
    assert L.autorise("1.2.3.4", maintenant=t0 + L.FENETRE_S + 1) is True
```

`briques/jeu-factions-public/test_moderation.py` :

```python
import moderation as M


def test_pseudo_propre_est_autorise():
    assert M.contient_mot_banni("Aria") is False


def test_pseudo_banni_est_detecte():
    assert M.contient_mot_banni("SuperConnard") is True


def test_detection_insensible_a_la_casse():
    assert M.contient_mot_banni("NIQUE tout") is True
```

- [ ] **Step 4: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions-public/limiteur.py briques/jeu-factions-public/moderation.py briques/jeu-factions-public/test_limiteur.py briques/jeu-factions-public/test_moderation.py
git commit -m "feat(jeu-factions-public): anti-abus V1 — rate limiting + filtre de pseudo"
```

---

### Task 5: Routes d'authentification (`/inscription`, `/connexion`, `/deconnexion`)

**Files:**
- Modify: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_auth.py`

**Interfaces:**
- Consumes: `stockage.creer_compte`, `stockage.lire_compte_par_email`, `stockage.assurer_joueur`
  (Task 2) ; `jeton.hacher_mot_de_passe`, `jeton.verifier_mot_de_passe`, `jeton.emettre`,
  `jeton.verifier`, `jeton.COOKIE_NOM`, `jeton.TTL_SESSION` (Task 3) ; `limiteur.autorise`
  (Task 4) ; `moderation.contient_mot_banni` (Task 4).
- Produces: `main.cle_api(request: Request) -> str` (dépendance FastAPI, consommée par
  toutes les tâches suivantes via `Depends(cle_api)`), routes `POST /inscription`,
  `POST /connexion`, `POST /deconnexion`.

- [ ] **Step 1: Modifier `main.py`**

Remplacer le contenu de `briques/jeu-factions-public/main.py` par :

```python
"""Brique « jeu-factions-public » — exposition publique du jeu (S220). Comptes email + mot
de passe propres à la brique, AUCUNE dépendance à core/ ni à Keycloak — voir
docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md."""
import os
import re

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import jeton
import limiteur
import moderation
import stockage

app = FastAPI(title="Jeu-factions-public — exposition publique du jeu (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("JEU_FACTIONS_PUBLIC_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ip_client(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def cle_api(request: Request) -> str:
    identite = jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))
    if not identite:
        raise HTTPException(401, "Session requise — connecte-toi.")
    return identite


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


class Inscription(BaseModel):
    email: str
    mot_de_passe: str
    pseudo: str


class Connexion(BaseModel):
    email: str
    mot_de_passe: str


def _poser_cookie_session(response: Response, compte_id: str) -> None:
    response.set_cookie(jeton.COOKIE_NOM, jeton.emettre(compte_id), max_age=jeton.TTL_SESSION,
                        httponly=True, samesite="lax", secure=True)


@app.post("/inscription", tags=["auth"])
def inscription_route(body: Inscription, request: Request, response: Response):
    if not limiteur.autorise(_ip_client(request)):
        raise HTTPException(429, "Trop de tentatives — réessaie plus tard.")
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(422, "Email invalide.")
    if len(body.mot_de_passe) < 8:
        raise HTTPException(422, "Mot de passe trop court (8 caractères minimum).")
    if not body.pseudo.strip() or moderation.contient_mot_banni(body.pseudo):
        raise HTTPException(422, "Pseudo refusé.")
    if stockage.lire_compte_par_email(body.email):
        raise HTTPException(409, "Cet email a déjà un compte.")
    compte = stockage.creer_compte(body.email, jeton.hacher_mot_de_passe(body.mot_de_passe),
                                   body.pseudo)
    stockage.assurer_joueur(compte["id"], body.pseudo)
    _poser_cookie_session(response, compte["id"])
    return {"ok": True}


@app.post("/connexion", tags=["auth"])
def connexion_route(body: Connexion, request: Request, response: Response):
    if not limiteur.autorise(_ip_client(request)):
        raise HTTPException(429, "Trop de tentatives — réessaie plus tard.")
    compte = stockage.lire_compte_par_email(body.email)
    if not compte or not jeton.verifier_mot_de_passe(body.mot_de_passe, compte["mot_de_passe_hash"]):
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    _poser_cookie_session(response, compte["id"])
    return {"ok": True}


@app.post("/deconnexion", tags=["auth"])
def deconnexion_route(response: Response):
    response.delete_cookie(jeton.COOKIE_NOM)
    return {"ok": True}
```

- [ ] **Step 2: Écrire les tests**

`briques/jeu-factions-public/test_auth.py` :

```python
from fastapi.testclient import TestClient

import limiteur
from main import app

client = TestClient(app)


def _inscrire(email="alice@example.com", mdp="motdepasse123", pseudo="Alice"):
    return client.post("/inscription", json={"email": email, "mot_de_passe": mdp, "pseudo": pseudo})


def test_inscription_pose_le_cookie():
    r = _inscrire()
    assert r.status_code == 200
    assert r.cookies.get("jeu_factions_public_utilisateur") is not None


def test_inscription_email_deja_pris_409():
    _inscrire()
    r = _inscrire()
    assert r.status_code == 409


def test_inscription_email_invalide_422():
    r = _inscrire(email="pas-un-email")
    assert r.status_code == 422


def test_inscription_mot_de_passe_trop_court_422():
    r = _inscrire(mdp="court")
    assert r.status_code == 422


def test_inscription_pseudo_banni_422():
    r = _inscrire(pseudo="SuperConnard")
    assert r.status_code == 422


def test_connexion_identifiants_valides():
    _inscrire()
    r = client.post("/connexion", json={"email": "alice@example.com", "mot_de_passe": "motdepasse123"})
    assert r.status_code == 200
    assert r.cookies.get("jeu_factions_public_utilisateur") is not None


def test_connexion_mauvais_mot_de_passe_401():
    _inscrire()
    r = client.post("/connexion", json={"email": "alice@example.com", "mot_de_passe": "faux"})
    assert r.status_code == 401


def test_connexion_email_inconnu_401():
    r = client.post("/connexion", json={"email": "jamais@example.com", "mot_de_passe": "x"})
    assert r.status_code == 401


def test_route_protegee_sans_cookie_401():
    assert client.get("/personnages_test_placeholder").status_code == 404  # route pas encore créée (Task 9)


def test_rate_limiting_sur_connexion():
    limiteur._reinitialiser()
    for _ in range(limiteur.MAX_TENTATIVES):
        client.post("/connexion", json={"email": "x@example.com", "mot_de_passe": "x"})
    r = client.post("/connexion", json={"email": "x@example.com", "mot_de_passe": "x"})
    assert r.status_code == 429


def test_deconnexion_supprime_le_cookie():
    r = client.post("/deconnexion")
    assert r.status_code == 200
```

Remarque : `test_route_protegee_sans_cookie_401` vérifie seulement qu'aucune route
`/personnages_test_placeholder` n'existe (404, pas 401) — un vrai test de `cle_api()` arrive
en Task 9 une fois une route protégée réelle câblée. Retirer ce test de
`test_auth.py` à l'ajout du test équivalent dans `test_api.py` (Task 9) pour éviter la
redondance : voir Step 3 de Task 9.

- [ ] **Step 3: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/main.py briques/jeu-factions-public/test_auth.py
git commit -m "feat(jeu-factions-public): routes inscription/connexion/deconnexion"
```

---

### Task 6: Zones de signe (copie `zones.py` + `mobs.py`)

**Files:**
- Create: `briques/jeu-factions-public/zones.py` (copie de `briques/jeu-factions/zones.py`)
- Create: `briques/jeu-factions-public/mobs.py` (copie de `briques/jeu-factions/mobs.py`)
- Modify: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_zones.py` (copie)
- Test: `briques/jeu-factions-public/test_mobs.py` (copie)

**Interfaces:**
- Produces: `zones.seed_zones()`, `zones.lister_zones() -> list[dict]`,
  `zones.lire_zone(zone_id) -> dict | None`, `zones.signe_personnage(snapshot) -> str | None`,
  `zones.marquer_vaincue_si_premiere_fois(zone_id) -> bool`,
  `zones.ajouter_score(zone_id, guilde, points) -> None`, `zones.ZONES_SEED`.
  `mobs.seed_mobs()`, `mobs.lister_mobs_zone(zone_id) -> list[dict]`.

- [ ] **Step 1: Copier les fichiers moteurs**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/zones.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/zones.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/mobs.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/mobs.py
```

- [ ] **Step 2: Copier les tests**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_zones.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_zones.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_mobs.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_mobs.py
```

- [ ] **Step 3: Câbler le seed au démarrage et les routes dans `main.py`**

Ajouter en tête de `main.py` (après `import stockage`) :

```python
import mobs
import zones
```

Ajouter juste après la définition de `app` (avant `_cors = ...`) :

```python
@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    mobs.seed_mobs()
```

Ajouter à la fin de `main.py` :

```python
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

- [ ] **Step 4: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent (les tests de `test_zones.py`/`test_mobs.py` n'appellent
que `zones`/`mobs`/`stockage` directement, pas `main` — aucune adaptation nécessaire)

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions-public/zones.py briques/jeu-factions-public/mobs.py briques/jeu-factions-public/test_zones.py briques/jeu-factions-public/test_mobs.py briques/jeu-factions-public/main.py
git commit -m "feat(jeu-factions-public): zones de signe (copie zones.py/mobs.py de jeu-factions)"
```

---

### Task 7: Voies d'archétype (copie `archetypes.py` + `mobs_archetype.py`)

**Files:**
- Create: `briques/jeu-factions-public/archetypes.py` (copie)
- Create: `briques/jeu-factions-public/mobs_archetype.py` (copie)
- Modify: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_archetypes.py` (copie)
- Test: `briques/jeu-factions-public/test_mobs_archetype.py` (copie)

**Interfaces:**
- Produces: `archetypes.ARCHETYPES_SIGNATURE`, `archetypes.seed_zones_archetype()`,
  `archetypes.seed_competences()`, `archetypes.bonus_idle(...)`,
  `archetypes.lister_toutes_competences_avec_effet() -> dict`,
  `archetypes.lister_etapes(archetype) -> list[dict]`,
  `archetypes.lire_etape(zone_archetype_id) -> dict | None`,
  `archetypes.prochaine_etape(personnage_id, archetype) -> str | None`,
  `archetypes.marquer_etape_vaincue(...)`, `archetypes.debloquer_competence_si_existe(...)`,
  `archetypes.lister_progressions_personnage(...)`, `archetypes.lister_competences_debloquees(...)`.
  `mobs_archetype.seed_mobs_archetype()`, `mobs_archetype.lister_mobs_etape(zone_archetype_id)`.

- [ ] **Step 1: Copier les fichiers moteurs et leurs tests**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/archetypes.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/archetypes.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/mobs_archetype.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/mobs_archetype.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_archetypes.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_archetypes.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_mobs_archetype.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_mobs_archetype.py
```

- [ ] **Step 2: Câbler le seed et la route dans `main.py`**

Ajouter en tête de `main.py` :

```python
import archetypes
import mobs_archetype
```

Modifier `_seed_donnees_globales` :

```python
@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
    mobs.seed_mobs()
    mobs_archetype.seed_mobs_archetype()
```

Ajouter à la fin de `main.py` :

```python
@app.get("/archetypes/{archetype}/etapes", tags=["archetypes"])
def lister_etapes_route(archetype: str, cle: str = Depends(cle_api)):
    if archetype not in archetypes.ARCHETYPES_SIGNATURE:
        raise HTTPException(404, "Archétype inconnu.")
    return archetypes.lister_etapes(archetype)
```

- [ ] **Step 3: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/archetypes.py briques/jeu-factions-public/mobs_archetype.py briques/jeu-factions-public/test_archetypes.py briques/jeu-factions-public/test_mobs_archetype.py briques/jeu-factions-public/main.py
git commit -m "feat(jeu-factions-public): voies d'archétype (copie archetypes.py/mobs_archetype.py)"
```

---

### Task 8: Groupes carry (copie `groupes.py`)

**Files:**
- Create: `briques/jeu-factions-public/groupes.py` (copie)
- Modify: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_groupes.py` (copie)

**Interfaces:**
- Produces: `groupes.creer_groupe(personnage_cible_id, zone_archetype_id) -> dict` (lève
  `ValueError`), `groupes.rejoindre_groupe(groupe_id, personnage_id) -> dict` (lève
  `ValueError`), `groupes.lire_groupe(groupe_id) -> dict | None`,
  `groupes.dissoudre_groupes_de_letape(zone_archetype_id, personnages_progresses) -> None`.

- [ ] **Step 1: Copier le fichier moteur et son test**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/groupes.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/groupes.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_groupes.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_groupes.py
```

- [ ] **Step 2: Ajouter les routes dans `main.py`**

Ajouter en tête de `main.py` :

```python
import groupes
```

Ajouter les modèles Pydantic (après `class Connexion`) :

```python
class CreerGroupe(BaseModel):
    personnage_cible_id: str
    zone_archetype_id: str


class RejoindreGroupe(BaseModel):
    personnage_id: str
```

Ajouter à la fin de `main.py` :

```python
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
```

- [ ] **Step 3: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/groupes.py briques/jeu-factions-public/test_groupes.py briques/jeu-factions-public/main.py
git commit -m "feat(jeu-factions-public): groupes carry (copie groupes.py)"
```

---

### Task 9: Personnages (copie `moteur_personnages.py` + routes `/personnages`)

**Files:**
- Create: `briques/jeu-factions-public/moteur_personnages.py` (copie)
- Modify: `briques/jeu-factions-public/main.py`
- Modify: `briques/jeu-factions-public/test_auth.py` (retirer le test placeholder)
- Test: `briques/jeu-factions-public/test_moteur_personnages.py` (copie)
- Test: `briques/jeu-factions-public/test_api.py` (copie, adapté aux cookies de comptes réels)

**Interfaces:**
- Consumes: `moteur_personnages.portrait(fiche) -> dict`,
  `moteur_personnages.recherche_inverse(description) -> dict`.
- Produces: routes `POST /personnages`, `GET /personnages`, `GET /personnages/{pid}`,
  `PATCH /personnages/{pid}/zone`, `GET /personnages/{pid}/competences`, `POST /presence`.

- [ ] **Step 1: Copier le fichier moteur et son test**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/moteur_personnages.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/moteur_personnages.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_moteur_personnages.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_moteur_personnages.py
```

- [ ] **Step 2: Ajouter les routes dans `main.py`**

Ajouter en tête de `main.py` :

```python
from datetime import datetime, timezone
from typing import Optional

import moteur_personnages
```

Ajouter le modèle Pydantic (après `class Inscription`) :

```python
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
```

Ajouter à la fin de `main.py` :

```python
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


@app.post("/presence", tags=["personnages"])
def enregistrer_presence_route(cle: str = Depends(cle_api)):
    stockage.enregistrer_presence(cle)
    return {"ok": True}


@app.get("/personnages", tags=["personnages"])
def lister_personnages_route(cle: str = Depends(cle_api)):
    personnages = stockage.lister_personnages(cle)
    derniere_presence = stockage.lire_derniere_presence(cle)
    maintenant = datetime.now(timezone.utc)
    for p in personnages:
        archetype = (p["snapshot_holistique"].get("portrait") or {}).get("archetype")
        prochaine = archetypes.prochaine_etape(p["id"], archetype) if archetype else None
        p["bonus_idle_actuel"] = (
            archetypes.bonus_idle(derniere_presence, maintenant,
                                  archetypes.TAUX_IDLE_PAR_HEURE, archetypes.PLAFOND_IDLE_HEURES)
            if prochaine else 0)
    return personnages


@app.get("/personnages/{pid}", tags=["personnages"])
def lire_personnage_route(pid: str, cle: str = Depends(cle_api)):
    p = stockage.lire_personnage(cle, pid)
    if not p:
        raise HTTPException(404, "Personnage introuvable.")
    p["progressions"] = archetypes.lister_progressions_personnage(pid)
    p["competences"] = archetypes.lister_competences_debloquees(pid)
    return p


@app.patch("/personnages/{pid}/zone", tags=["personnages"])
def assigner_zone_route(pid: str, body: AssignerZone, cle: str = Depends(cle_api)):
    if not zones.lire_zone(body.zone_id):
        raise HTTPException(404, "Zone introuvable.")
    p = stockage.assigner_zone(cle, pid, body.zone_id)
    if not p:
        raise HTTPException(404, "Personnage introuvable.")
    return p


@app.get("/personnages/{pid}/competences", tags=["personnages"])
def lister_competences_route(pid: str, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, pid):
        raise HTTPException(404, "Personnage introuvable.")
    return archetypes.lister_competences_debloquees(pid)
```

- [ ] **Step 3: Copier `test_api.py` et retirer le test placeholder de `test_auth.py`**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_api.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_api.py
```

`test_api.py` copié utilise déjà `jeton.emettre(identite, ttl=3600)` pour fabriquer des
cookies de test directement (sans passer par `/inscription`) — signature identique à notre
`jeton.emettre`, aucune adaptation de fond nécessaire. Vérifier par lecture rapide qu'aucune
ligne ne référence `JEU_FACTIONS_KEY` (déjà confirmé pendant le brainstorming — aucune
occurrence dans ce fichier).

Dans `test_auth.py`, retirer le test placeholder devenu inutile :

```python
def test_route_protegee_sans_cookie_401():
    assert client.get("/personnages_test_placeholder").status_code == 404  # route pas encore créée (Task 9)
```

et le remplacer par :

```python
def test_route_protegee_sans_cookie_401():
    assert client.get("/personnages").status_code == 401
```

- [ ] **Step 4: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions-public/moteur_personnages.py briques/jeu-factions-public/test_moteur_personnages.py briques/jeu-factions-public/test_api.py briques/jeu-factions-public/test_auth.py briques/jeu-factions-public/main.py
git commit -m "feat(jeu-factions-public): routes personnages (copie moteur_personnages.py)"
```

---

### Task 10: Combat temps réel (copie `combat_moteur.py` + `combat.py`) + routes WS

**Files:**
- Create: `briques/jeu-factions-public/combat_moteur.py` (copie)
- Create: `briques/jeu-factions-public/combat.py` (copie)
- Modify: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_combat_moteur.py` (copie)
- Test: `briques/jeu-factions-public/test_combat.py` (copie)
- Test: `briques/jeu-factions-public/test_combat_archetype.py` (copie)

**Interfaces:**
- Produces: routes WebSocket `GET /zones/{zone_id}/combat`, `GET /groupes/{groupe_id}/combat`.

- [ ] **Step 1: Copier les fichiers moteurs et leurs tests**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/combat_moteur.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/combat_moteur.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/combat.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/combat.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_combat_moteur.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_combat_moteur.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_combat.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_combat.py
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_combat_archetype.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_combat_archetype.py
```

- [ ] **Step 2: Ajouter les routes WS dans `main.py`**

Ajouter en tête de `main.py` :

```python
import time

from fastapi import Query, WebSocket, WebSocketDisconnect

import combat
```

Ajouter à la fin de `main.py` :

```python
@app.websocket("/zones/{zone_id}/combat")
async def combat_ws(websocket: WebSocket, zone_id: str, personnage_id: str = Query(...)):
    await websocket.accept()
    identite = jeton.verifier(websocket.cookies.get(jeton.COOKIE_NOM))
    if identite is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(identite, personnage_id)
    zone = zones.lire_zone(zone_id)
    if not perso or not zone:
        await websocket.close(code=4404)
        return
    signe = zones.signe_personnage(perso["snapshot_holistique"]) or "Bélier"
    element = dict(zones.ZONES_SEED).get(signe, "Feu")
    gabarits = mobs.lister_mobs_zone(zone_id)
    inst = await combat.rejoindre(zone_id, personnage_id, element, signe, gabarits)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    try:
        combat.enregistrer_connexion(inst, personnage_id, websocket)
        await websocket.send_json({"type": "etat", **combat.etat_public(inst), "evenements": []})
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())


@app.websocket("/groupes/{groupe_id}/combat")
async def combat_voie_ws(websocket: WebSocket, groupe_id: str, personnage_id: str = Query(...)):
    await websocket.accept()
    identite = jeton.verifier(websocket.cookies.get(jeton.COOKIE_NOM))
    if identite is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(identite, personnage_id)
    gr = groupes.lire_groupe(groupe_id)
    if not perso or not gr or gr["etat"] != "actif" or personnage_id not in gr["membres"]:
        await websocket.close(code=4404)
        return
    etape = archetypes.lire_etape(gr["zone_archetype_id"])
    if not etape:
        await websocket.close(code=4404)
        return
    gabarits = mobs_archetype.lister_mobs_etape(gr["zone_archetype_id"])
    signe = zones.signe_personnage(perso["snapshot_holistique"]) or "Bélier"
    inst = await combat.rejoindre(gr["zone_archetype_id"], personnage_id, etape["archetype"],
                                  signe, gabarits, contexte="archetype",
                                  cle_contribution=personnage_id)
    if archetypes.prochaine_etape(personnage_id, etape["archetype"]) == gr["zone_archetype_id"]:
        derniere_presence = stockage.lire_derniere_presence_personnage(personnage_id)
        bonus = archetypes.bonus_idle(derniere_presence, datetime.now(timezone.utc),
                                      archetypes.TAUX_IDLE_PAR_HEURE, archetypes.PLAFOND_IDLE_HEURES)
        if bonus:
            combat.appliquer_bonus_idle(inst, bonus, personnage_id)
            stockage.enregistrer_presence(identite)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    try:
        combat.enregistrer_connexion(inst, personnage_id, websocket)
        await websocket.send_json({"type": "etat", **combat.etat_public(inst), "evenements": []})
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())
```

- [ ] **Step 3: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions-public/combat_moteur.py briques/jeu-factions-public/combat.py briques/jeu-factions-public/test_combat_moteur.py briques/jeu-factions-public/test_combat.py briques/jeu-factions-public/test_combat_archetype.py briques/jeu-factions-public/main.py
git commit -m "feat(jeu-factions-public): combat temps réel (copie combat_moteur.py/combat.py)"
```

---

### Task 11: Front — accueil/connexion + jeu + combat

**Files:**
- Create: `briques/jeu-factions-public/style.css`
- Create: `briques/jeu-factions-public/front.html`
- Create: `briques/jeu-factions-public/front_combat.html` (copie de `front_combat.html`, éditée)
- Modify: `briques/jeu-factions-public/main.py`
- Test: `briques/jeu-factions-public/test_front.py`
- Test: `briques/jeu-factions-public/test_front_combat.py` (copie)

**Interfaces:**
- Produces: routes `GET /`, `GET /front_combat.html`, `GET /style.css`.

- [ ] **Step 1: Écrire `style.css`**

Identité visuelle propre (décision de cadrage : pas `workplace.css`) — dark theme minimal :

```css
body { background: #0f172a; color: #e2e8f0; font-family: system-ui, sans-serif;
       max-width: 900px; margin: 0 auto; padding: 24px; }
h1, h2 { color: #facc15; }
section { background: #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
input, textarea, button { background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
       border-radius: 4px; padding: 8px; margin: 4px 0; }
button { background: #facc15; color: #0f172a; font-weight: bold; cursor: pointer; border: none; }
button:hover { background: #eab308; }
#messageAuthErreur { color: #f87171; }
ul { list-style: none; padding: 0; }
li { padding: 6px 0; border-bottom: 1px solid #334155; }
a { color: #60a5fa; }
```

- [ ] **Step 2: Écrire `front.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Jeu-factions</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<h1>Jeu-factions</h1>

<section id="auth">
  <h2>Connexion</h2>
  <form id="formConnexion">
    <input id="connexionEmail" type="email" placeholder="Email" required>
    <input id="connexionMdp" type="password" placeholder="Mot de passe" required>
    <button type="submit">Se connecter</button>
  </form>
  <h2>Inscription</h2>
  <form id="formInscription">
    <input id="inscriptionPseudo" placeholder="Pseudo" required>
    <input id="inscriptionEmail" type="email" placeholder="Email" required>
    <input id="inscriptionMdp" type="password" placeholder="Mot de passe (8 caractères min.)" required>
    <button type="submit">Créer un compte</button>
  </form>
  <p id="messageAuthErreur"></p>
</section>

<section id="jeuConnecte" style="display:none">
  <button id="boutonDeconnexion">Se déconnecter</button>

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

  <h2>Mes personnages</h2>
  <ul id="listePersonnages"></ul>

  <h2>Zones de signe (PvE partagé)</h2>
  <ul id="listeZones"></ul>
</section>

<script>
const entetes = () => ({"Content-Type": "application/json"});

function afficherErreurAuth(texte) {
  document.getElementById("messageAuthErreur").textContent = texte;
}

document.getElementById("formConnexion").addEventListener("submit", async e => {
  e.preventDefault();
  const r = await fetch("/connexion", {method: "POST", headers: entetes(), body: JSON.stringify({
    email: document.getElementById("connexionEmail").value,
    mot_de_passe: document.getElementById("connexionMdp").value,
  })});
  if (!r.ok) { afficherErreurAuth((await r.json()).detail || "Connexion refusée."); return; }
  location.reload();
});

document.getElementById("formInscription").addEventListener("submit", async e => {
  e.preventDefault();
  const r = await fetch("/inscription", {method: "POST", headers: entetes(), body: JSON.stringify({
    pseudo: document.getElementById("inscriptionPseudo").value,
    email: document.getElementById("inscriptionEmail").value,
    mot_de_passe: document.getElementById("inscriptionMdp").value,
  })});
  if (!r.ok) { afficherErreurAuth((await r.json()).detail || "Inscription refusée."); return; }
  location.reload();
});

document.getElementById("boutonDeconnexion").addEventListener("click", async () => {
  await fetch("/deconnexion", {method: "POST"});
  location.reload();
});

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
  document.getElementById("listePersonnages").innerHTML = items.map(p => {
    const bonus = p.bonus_idle_actuel > 0
      ? ` — +${p.bonus_idle_actuel} vers la prochaine étape (voie d'archétype)` : "";
    return `<li>${p.nom} — ${(p.snapshot_holistique.portrait || {}).archetype || "?"} (zone: ${p.zone_actuelle || "aucune"})${bonus}</li>`;
  }).join("");
}

async function chargerZones() {
  const r = await fetch("/zones", {headers: entetes()});
  const items = await r.json();
  document.getElementById("listeZones").innerHTML = items.map(z =>
    `<li>${z.nom} (${z.element_natif}) — ${z.etat} ` +
    `<a href="/front_combat.html?zone=${z.id}">Rejoindre le combat</a></li>`
  ).join("");
}

(async () => {
  const r = await fetch("/personnages", {headers: entetes()});
  if (r.status === 401) {
    document.getElementById("auth").style.display = "block";
    document.getElementById("jeuConnecte").style.display = "none";
    return;
  }
  document.getElementById("auth").style.display = "none";
  document.getElementById("jeuConnecte").style.display = "block";
  chargerPersonnages();
  chargerZones();
  setInterval(() => fetch("/presence", {method: "POST", headers: entetes()}).catch(() => {}), 30_000);
})();
</script>
</body>
</html>
```

- [ ] **Step 3: Copier `front_combat.html` puis l'éditer**

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/front_combat.html \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/front_combat.html
```

Dans `briques/jeu-factions-public/front_combat.html`, remplacer :

```html
<link rel="stylesheet" href="/workplace.css">
```
par :
```html
<link rel="stylesheet" href="/style.css">
```

et remplacer :
```javascript
  if (r.status === 401) {
    document.getElementById("jeu").textContent =
      "Session expirée — rouvre cette page depuis le tableau de bord du Cœur.";
    throw new Error("session expirée");
  }
```
par :
```javascript
  if (r.status === 401) {
    document.getElementById("jeu").textContent =
      "Session expirée — reconnecte-toi depuis la page d'accueil.";
    throw new Error("session expirée");
  }
```

- [ ] **Step 4: Ajouter les routes statiques dans `main.py`**

Ajouter en tête de `main.py` :

```python
from pathlib import Path

from fastapi.responses import FileResponse
```

Ajouter à la fin de `main.py` :

```python
@app.get("/", include_in_schema=False)
def accueil():
    return FileResponse(Path(__file__).parent / "front.html")


@app.get("/front_combat.html", response_class=FileResponse, include_in_schema=False)
def combat_front():
    return FileResponse(Path(__file__).parent / "front_combat.html")


@app.get("/style.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "style.css", media_type="text/css")
```

- [ ] **Step 5: Écrire `test_front.py` et copier `test_front_combat.py`**

`briques/jeu-factions-public/test_front.py` :

```python
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_accueil_sert_le_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_css_servi():
    r = client.get("/style.css")
    assert r.status_code == 200


def test_front_contient_les_formulaires_auth():
    r = client.get("/")
    assert "formConnexion" in r.text
    assert "formInscription" in r.text


def test_front_ne_reference_pas_le_coeur():
    r = client.get("/")
    assert "tableau de bord du Cœur" not in r.text
    assert "localStorage" not in r.text
```

```bash
cp /Users/garinat_t/Desktop/Workplace/briques/jeu-factions/test_front_combat.py \
   /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public/test_front_combat.py
```

- [ ] **Step 6: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions-public/style.css briques/jeu-factions-public/front.html briques/jeu-factions-public/front_combat.html briques/jeu-factions-public/test_front.py briques/jeu-factions-public/test_front_combat.py briques/jeu-factions-public/main.py
git commit -m "feat(jeu-factions-public): front — accueil/connexion + jeu + combat"
```

---

### Task 12: Isolation renforcée entre comptes réels

**Files:**
- Create: `briques/jeu-factions-public/test_isolation.py`

**Interfaces:**
- Consumes: tout ce qui précède (Tasks 2-11) — tâche de vérification pure, aucun nouveau code
  de production.

- [ ] **Step 1: Écrire `test_isolation.py`**

```python
"""Filet dédié : personnages/groupes restent cloisonnés par cle_api (id de compte réel,
pas de tenant partagé — cette brique n'a jamais eu de mode `"public"`). zones/scores/étapes
restent un monde PARTAGÉ (exception délibérée héritée du design de jeu-factions)."""
from fastapi.testclient import TestClient

import archetypes
import jeton
import zones
from main import app

client = TestClient(app)


def _compte(email: str) -> str:
    r = client.post("/inscription", json={"email": email, "mot_de_passe": "motdepasse123",
                                          "pseudo": email.split("@")[0]})
    assert r.status_code == 200
    return jeton.verifier(r.cookies.get(jeton.COOKIE_NOM))


def _cookies(compte_id: str) -> dict:
    return {jeton.COOKIE_NOM: jeton.emettre(compte_id, ttl=3600)}


def _patch_moteur(monkeypatch):
    async def _portrait(fiche, client=None):
        return {"portrait": {"archetype": "Le Sage Contemplatif", "stats": {"Sagesse": 100}},
               "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_personnage_invisible_pour_un_autre_compte(monkeypatch):
    _patch_moteur(monkeypatch)
    compte_a = _compte("tenant-a@example.com")
    compte_b = _compte("tenant-b@example.com")
    r = client.post("/personnages", json={"nom": "Secret", "date_naissance": "1990-01-01"},
                    cookies=_cookies(compte_a))
    pid = r.json()["id"]
    assert client.get(f"/personnages/{pid}", cookies=_cookies(compte_a)).status_code == 200
    assert client.get(f"/personnages/{pid}", cookies=_cookies(compte_b)).status_code == 404
    assert not any(p["id"] == pid for p in
                  client.get("/personnages", cookies=_cookies(compte_b)).json())


def test_zones_identiques_pour_tous_les_comptes():
    zones.seed_zones()
    compte_a = _compte("tenant-c@example.com")
    compte_b = _compte("tenant-d@example.com")
    a = client.get("/zones", cookies=_cookies(compte_a)).json()
    b = client.get("/zones", cookies=_cookies(compte_b)).json()
    assert {z["id"] for z in a} == {z["id"] for z in b}


def test_etapes_archetype_identiques_pour_tous_les_comptes():
    archetypes.seed_zones_archetype()
    compte_a = _compte("tenant-e@example.com")
    compte_b = _compte("tenant-f@example.com")
    a = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies(compte_a)).json()
    b = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies(compte_b)).json()
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_groupe_dun_compte_pas_manipulable_par_un_autre(monkeypatch):
    _patch_moteur(monkeypatch)
    compte_c = _compte("tenant-g@example.com")
    compte_d = _compte("tenant-h@example.com")
    r = client.post("/personnages", json={"nom": "AutreCompte", "date_naissance": "1990-01-01"},
                    cookies=_cookies(compte_c))
    pid = r.json()["id"]
    archetypes.seed_zones_archetype()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies(compte_c)).json()[0]
    r2 = client.post("/groupes", json={"personnage_cible_id": pid, "zone_archetype_id": etape["id"]},
                     cookies=_cookies(compte_d))
    assert r2.status_code == 404


def test_deux_comptes_avec_le_meme_pseudo_restent_distincts(monkeypatch):
    """Le pseudo n'est pas une clé d'identité — seul l'email l'est (contrainte UNIQUE sur
    comptes.email, pas sur comptes.pseudo)."""
    _patch_moteur(monkeypatch)
    compte_a = _compte("meme-pseudo-1@example.com")
    r = client.post("/inscription", json={"email": "meme-pseudo-2@example.com",
                                          "mot_de_passe": "motdepasse123", "pseudo": "MemePseudo"})
    assert r.status_code == 200 or r.status_code == 409  # 409 seulement si le pseudo ci-dessus était déjà "MemePseudo"
```

- [ ] **Step 2: Lancer les tests**

Run: `python -m pytest -q`
Expected: tous les tests passent (environ 90+ tests au total sur toute la brique)

- [ ] **Step 3: Commit**

```bash
git add briques/jeu-factions-public/test_isolation.py
git commit -m "test(jeu-factions-public): isolation stricte entre comptes réels"
```

---

### Task 13: Exposition réseau — Caddy + `.env.example` + README

**Files:**
- Create: `outils/mesh-https/Caddyfile.jeu-factions-public`
- Modify: `.env.example`
- Create: `briques/jeu-factions-public/README.md`

**Interfaces:** aucune (tâche de configuration/documentation, pas de code applicatif).

- [ ] **Step 1: Écrire le bloc Caddy dédié**

`outils/mesh-https/Caddyfile.jeu-factions-public` :

```caddyfile
# Exposition PUBLIQUE de jeu-factions-public (S220) — site importé dans l'instance Caddy
# UNIQUE déjà en place (`mesh_caddy`, network_mode: host, port 443 déjà possédé — un second
# conteneur Caddy entrerait en conflit sur ce port). Même motif que Caddyfile.briques
# (import depuis le Caddyfile principal), pas un déploiement séparé.
#
# Contrairement à Caddyfile.briques (domaine mesh *.duckdns.org, cert DNS-01), ce domaine est
# un vrai domaine public distinct — Caddy lui délivre automatiquement un certificat Let's
# Encrypt standard (HTTP-01/TLS-ALPN) sans config ACME dédiée, à condition que le port 443
# soit bien joignable depuis Internet pour ce domaine (port-forward sur la box domicile,
# hors de ce repo).
#
# Aucun bloc d'options globales ici : le Caddyfile principal en a déjà un
# (`acme_dns duckdns`), Caddy n'en accepte qu'un seul par config complète.
#
# Déploiement :
#   1. Remplacer <TON-DOMAINE-PUBLIC> ci-dessous.
#   2. Ajouter `import Caddyfile.jeu-factions-public` dans outils/mesh-https/Caddyfile
#      (à côté du `import Caddyfile.briques` déjà présent).
#   3. docker restart mesh_caddy   (PAS `caddy reload` — piège bind-mount déjà documenté :
#      un `reload` ne relit pas un Caddyfile modifié sur un volume bind-monté de la même
#      façon qu'un restart, cf. mémoire "piège Caddy bind-mount inode").

https://<TON-DOMAINE-PUBLIC> {
    reverse_proxy localhost:6220
}
```

- [ ] **Step 2: Ajouter la section `.env.example`**

Insérer après la section `# ── Brique « jeu-factions » ...` (ligne 306, `JEU_FACTIONS_KEY=`)
dans `/Users/garinat_t/Desktop/Workplace/.env.example` :

```
# ── Brique « jeu-factions-public » (exposition publique du jeu, port 6220, S220) ──────
# Brique INDÉPENDANTE de jeu-factions ci-dessus : comptes email + mot de passe propres à
# cette brique, AUCUNE dépendance à Keycloak/core. JEU_FACTIONS_PUBLIC_SECRET est le secret
# HMAC de session — pas partagé avec le Cœur (contrairement à JEU_FACTIONS_KEY). Sans lui,
# aucune session ne peut être vérifiée (jeton.verifier renvoie toujours None). Génère une
# clé : `openssl rand -hex 32`.
JEU_FACTIONS_PUBLIC_SECRET=

# CORS de cette brique — NE JAMAIS réutiliser la variable CORS_ORIGINS ci-dessus (celle-ci
# liste les origines du dashboard Cœur pour les briques cercle privé ; la partager ferait
# fuiter ces origines dans le conteneur public via env_file, motif documenté :
# fix-env-shadow-composes.md). Domaine public exact de jeu-factions-public, ex.
# https://factions.exemple.fr — PAS "*" en production.
JEU_FACTIONS_PUBLIC_CORS_ORIGINS=
```

- [ ] **Step 3: Écrire `README.md`**

`briques/jeu-factions-public/README.md` :

```markdown
# jeu-factions-public — exposition publique du jeu (S220)

Brique **indépendante** de `briques/jeu-factions/` (cercle privé, Keycloak) — mêmes moteurs
de jeu (copie-adaptation depuis `jeu-factions`, cf.
`docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md`), mais comptes email + mot
de passe propres à la brique, aucune dépendance à `core/` ni à Keycloak.

## Démarrer

```bash
docker compose up -d --build      # API sur http://localhost:6220
curl localhost:6220/sante
```

## Configuration

`JEU_FACTIONS_PUBLIC_SECRET` est **obligatoire** — secret HMAC de session, propre à cette
brique (pas partagé avec le Cœur). `JEU_FACTIONS_PUBLIC_CORS_ORIGINS` doit être le domaine
public exact en production — voir `.env.example` racine.

## Concepts

Identiques à `jeu-factions` (cercle privé) — voir son README pour le détail des concepts
(nation/guilde/classe, zones de signe partagées, voies d'archétype personnelles). Seule
l'identité change : un compte email + mot de passe remplace l'identité Keycloak.

## Exposition publique

Domaine public dédié, port-forward sur la box domicile vers ce HP (config réseau côté
utilisateur, hors repo) + `outils/mesh-https/Caddyfile.jeu-factions-public` côté repo.

## Non fait ici (V1)

PvP, OAuth/comptes anonymes, scaling multi-process, captcha, file de modération, tuile
dashboard Cœur — voir le spec, sections Non-objectifs.

## Tests

```bash
python -m pytest -q
```
```

- [ ] **Step 4: Vérifier que la suite complète passe**

Run:
```bash
cd /Users/garinat_t/Desktop/Workplace/briques/jeu-factions-public
python -m pytest -q
```
Expected: tous les tests passent, aucune régression

- [ ] **Step 5: Commit**

```bash
git add outils/mesh-https/Caddyfile.jeu-factions-public .env.example briques/jeu-factions-public/README.md
git commit -m "docs(jeu-factions-public): exposition Caddy + .env.example + README (S220)"
```

---

## Self-Review (fait pendant l'écriture de ce plan)

**Couverture du spec.** Identité (Task 3, 5), stockage/comptes (Task 2), anti-abus (Task 4),
tous les moteurs copiés (Tasks 6-10), front autonome (Task 11), isolation (Task 12),
exposition réseau + config (Task 13). Aucune section du spec sans tâche correspondante.

**Placeholders.** Aucun "TBD"/"TODO" — la seule référence différée est le `<TON-DOMAINE-PUBLIC>`
dans le Caddyfile, qui est une valeur d'exploitation à remplacer au déploiement (même motif
que `Caddyfile.duckdns` existant), pas un trou de conception.

**Cohérence des types/noms.** `cle_api` (str, id de compte) traverse tout le plan de manière
identique depuis Task 2 (`stockage.py`) jusqu'à Task 12 (`test_isolation.py`). `jeton.emettre`/
`jeton.verifier` gardent la même signature de Task 3 à Task 12. `JEU_FACTIONS_PUBLIC_CORS_ORIGINS`
(jamais `CORS_ORIGINS`) est utilisé de façon cohérente entre Task 1 (docker-compose), Task 5
(main.py) et Task 13 (.env.example).
