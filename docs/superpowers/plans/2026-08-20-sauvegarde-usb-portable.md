# Sauvegarde portable sur clé USB — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une capacité assistant « sauvegarde sur la clé » / « restaure depuis la clé » qui
prend un instantané à la demande de toutes les bases Postgres/SQLite du stack (découverte
dynamique, pas de liste figée), l'écrit sur une clé USB montée sur le HP (un seul instantané
à la fois), et sait le réinjecter sur une autre machine — sans dépendre d'aucun service cloud.

**Architecture:** Nouveau module natif dans `core` (`core/sauvegarde_usb.py` + routeur
`core/routers/sauvegarde_usb.py`), réutilisant le socket Docker déjà monté sur `core`
(`core/docker-compose.yml`, motif déjà en place dans `config_assistant.py` pour redémarrer la
Gateway). Toutes les interactions Docker passent par l'API HTTP du démon (via `httpx` sur le
socket Unix), jamais par le SDK `docker` ni par le CLI — c'est déjà le motif établi du projet.

**Tech Stack:** Python 3.12+, FastAPI, httpx (déjà utilisé pour parler au socket Docker),
`tarfile`/`io` (stdlib, pour lire/écrire les archives de l'API Docker `archive`), pytest +
`httpx.MockTransport` (motif déjà utilisé par `core/test_muscle.py`, `core/test_netbird.py`).

## Global Constraints

- Aucune donnée de ce plan (bases, dumps) n'est jamais écrite ailleurs qu'à la racine du point
  de montage de la clé USB — jamais sur le disque interne du HP, sauf le `.env` qui, lui,
  n'est **jamais** écrit sur la clé de sauvegarde des bases (cf. spec, non-objectifs).
- Toute action `action: true` passe par le gate structurel existant
  (`core/accord_action.py`, S222) — ne rien réimplémenter, juste déclarer `"action": true`
  dans le manifest (cf. Task 9).
- Style du dépôt : identifiants et commentaires en français, docstrings expliquant le
  « pourquoi » plutôt que le « quoi » (cf. tout le code déjà lu de `core/`).
- Dump Postgres = **logique** (`pg_dump`), jamais de copie brute de
  `/var/lib/postgresql/data` (portabilité inter-machines/versions, cf. spec).
- Un seul instantané par clé : chaque sauvegarde écrase le précédent (pas de dossier
  horodaté).

---

## File Structure

- **Create** `core/sauvegarde_usb.py` — logique pure + appels Docker (découverte, dump,
  restauration, export .env). Aucune dépendance à FastAPI.
- **Create** `core/test_sauvegarde_usb.py` — tests de `core/sauvegarde_usb.py`
  (`httpx.MockTransport` + `tmp_path`).
- **Create** `core/routers/sauvegarde_usb.py` — 3 routes FastAPI + dépendance d'auth double
  (session navigateur OU `X-API-Key: NOYAU_KEY`).
- **Create** `core/test_sauvegarde_usb_router.py` — tests du routeur (FastAPI `TestClient`,
  module de logique mocké).
- **Modify** `core/main.py` — inclusion du nouveau routeur.
- **Modify** `core/docker-compose.yml` — montage du point de montage USB + montage RO du
  `.env` racine + `NOYAU_KEY`.
- **Modify** `.env.example` — nouvelles variables (`SAUVEGARDE_USB_MONTAGE`, `NOYAU_KEY`).
- **Modify** `briques/noyau/manifest.json` — 3 nouvelles `capacites`.
- **Modify** `core/dashboard.html` — 3 boutons (sauvegarde / restauration / export .env).
- **Create** `outils/sauvegarde-usb/95-workplace-usb.rules` — règle udev (montage auto par
  label de partition).
- **Create** `outils/sauvegarde-usb/README.md` — comment préparer la clé (sentinelle, label)
  et installer la règle udev sur le HP.
- **Create** `docs/INSTALLATION-MACHINE-NEUVE.md` — guide de bootstrap sur un PC neuf (sur le
  modèle de `MIGRATION-HP.md`), pour qu'un agent de code (Claude Code/OpenCode) puisse le
  suivre.

---

### Task 1: Client Docker de base (socket, exec, démultiplexage)

**Files:**
- Create: `core/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb.py`

**Interfaces:**
- Produces: `_docker_client() -> httpx.AsyncClient`, `_demultiplexer(brut: bytes) -> bytes`,
  `async def _exec(client: httpx.AsyncClient, conteneur_id: str, cmd: list[str]) -> tuple[int, bytes]`
  (code de sortie, stdout démultiplexé) — utilisés par toutes les tâches suivantes.

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb.py
import asyncio

import httpx
import pytest

import sauvegarde_usb


def _cadre_exec(type_flux: int, charge: bytes) -> bytes:
    """Construit une trame du format multiplexé Docker exec (Tty=false) :
    1 octet type + 3 octets réservés + 4 octets longueur (big-endian) + charge."""
    entete = bytes([type_flux, 0, 0, 0]) + len(charge).to_bytes(4, "big")
    return entete + charge


def test_demultiplexer_isole_stdout():
    brut = _cadre_exec(1, b"bonjour") + _cadre_exec(2, b"ignore-moi") + _cadre_exec(1, b" monde")
    assert sauvegarde_usb._demultiplexer(brut) == b"bonjour monde"


def test_demultiplexer_flux_vide():
    assert sauvegarde_usb._demultiplexer(b"") == b""


def test_exec_renvoie_code_et_stdout():
    # Async via asyncio.run — motif déjà en usage dans toute la suite core/ (cf.
    # core/test_muscle.py, core/test_amelioration_outils.py), pas de marqueur pytest.
    appels = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request.url.path)
        if request.url.path == "/containers/abc123/exec":
            return httpx.Response(200, json={"Id": "exec1"})
        if request.url.path == "/exec/exec1/start":
            return httpx.Response(200, content=_cadre_exec(1, b"ok\n"))
        if request.url.path == "/exec/exec1/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {request.url.path}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb._exec(client, "abc123", ["echo", "ok"])

    code, sortie = asyncio.run(go())
    assert code == 0
    assert sortie == b"ok\n"
    assert appels == ["/containers/abc123/exec", "/exec/exec1/start", "/exec/exec1/json"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'sauvegarde_usb'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/sauvegarde_usb.py
"""Sauvegarde/restauration portable sur clé USB — instantané à la demande (pas de
réplication continue, pas de cloud). Remplace, pour cet usage, l'approche « réplication
continue vers S3 » abandonnée (Litestream/WAL-G jamais branchés en prod, cf.
docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md).

Toutes les interactions Docker passent par l'API HTTP du démon via `httpx` sur le socket
Unix — même motif que `config_assistant._docker_client()` (S168, redémarrage de la
Gateway) : évite d'ajouter le SDK `docker` en dépendance pour un besoin déjà couvert.
"""
import os

import httpx

DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


def _docker_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=60)


def _demultiplexer(brut: bytes) -> bytes:
    """Isole les trames STDOUT (type 1) d'un flux `exec/start` Docker (Tty=false).

    Format par trame, imposé par l'API Docker : 1 octet type de flux (0=stdin, 1=stdout,
    2=stderr) + 3 octets réservés + 4 octets de longueur (big-endian) + la charge. STDERR
    est délibérément ignoré ici (pas utile pour lire une sortie `pg_dump`/`find`/`stat` ;
    en cas d'échec, `_exec` renvoie aussi le code de sortie, qui suffit à détecter l'erreur)."""
    sortie = bytearray()
    i = 0
    while i + 8 <= len(brut):
        type_flux = brut[i]
        taille = int.from_bytes(brut[i + 4:i + 8], "big")
        charge = brut[i + 8:i + 8 + taille]
        if type_flux == 1:
            sortie += charge
        i += 8 + taille
    return bytes(sortie)


async def _exec(client: httpx.AsyncClient, conteneur_id: str, cmd: list[str]) -> tuple[int, bytes]:
    """Exécute `cmd` dans un conteneur déjà démarré, renvoie (code_sortie, stdout).

    Équivalent de `docker exec` via l'API : création de l'exec, démarrage (le corps de la
    réponse EST le flux multiplexé stdout/stderr), puis relecture du code de sortie."""
    r = await client.post(f"/containers/{conteneur_id}/exec",
                           json={"AttachStdout": True, "AttachStderr": True, "Cmd": cmd})
    r.raise_for_status()
    exec_id = r.json()["Id"]
    r2 = await client.post(f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
    r2.raise_for_status()
    sortie = _demultiplexer(r2.content)
    r3 = await client.get(f"/exec/{exec_id}/json")
    r3.raise_for_status()
    code = r3.json().get("ExitCode") or 0
    return code, sortie
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/sauvegarde_usb.py core/test_sauvegarde_usb.py
git commit -m "feat(sauvegarde-usb): client Docker de base (exec + démultiplexage)"
```

---

### Task 2: Découverte dynamique des sources (SQLite + Postgres)

**Files:**
- Modify: `core/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb.py`

**Interfaces:**
- Consumes: `_docker_client`, `_exec` (Task 1).
- Produces: `async def decouvrir_sources(client: httpx.AsyncClient) -> list[dict]` — chaque
  entrée : `{"brique": str, "type": "sqlite"|"postgres", "conteneur_id": str}` +
  `{"chemin": str}` (sqlite) ou `{"db": str, "user": str}` (postgres). Utilisé par Task 4
  (sauvegarde) et indirectement par Task 5 via `decouvrir_conteneurs_par_brique`.
- Produces aussi : `async def decouvrir_conteneurs_par_brique(client) -> dict[str, str]`
  (brique → conteneur_id, pour la restauration).

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb.py (ajouts)
def _reponse_containers_json(conteneurs: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=conteneurs)


def test_decouvrir_sources_sqlite_et_postgres():
    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin == "/containers/sq1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/donnees.db\n"))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 0})
        if chemin == "/containers/pg1/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory", "PATH=/usr/bin"]}})
        raise AssertionError(f"appel inattendu : {chemin}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb.decouvrir_sources(client)

    sources = asyncio.run(go())

    assert {"brique": "workplace_donnees", "type": "sqlite", "conteneur_id": "sq1",
            "chemin": "/data/donnees.db"} in sources
    assert {"brique": "memoire-memoire-db-1", "type": "postgres", "conteneur_id": "pg1",
            "db": "memory", "user": "memory"} in sources


def test_decouvrir_sources_ignore_conteneur_sans_db():
    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json(
                [{"Id": "vide1", "Names": ["/mesh_caddy"], "Image": "caddy:2"}])
        if chemin == "/containers/vide1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b""))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 1})
        raise AssertionError(f"appel inattendu : {chemin}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb.decouvrir_sources(client)

    assert asyncio.run(go()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v -k decouvrir_sources`
Expected: FAIL avec `AttributeError: module 'sauvegarde_usb' has no attribute 'decouvrir_sources'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/sauvegarde_usb.py (ajouts)

def _est_postgres(image: str) -> bool:
    """Détecte une base Postgres par motif d'image — couvre les 6 bases connues du HP au
    2026-08-20 (postgres:16.*, workplace/*-walg, patroni-pg16) sans en coder les noms."""
    image = image.lower()
    return any(motif in image for motif in ("postgres", "-walg", "patroni"))


async def _chercher_sqlite(client: httpx.AsyncClient, conteneur_id: str) -> list[str]:
    """Fichiers `*.db` sous /data (SQLite) dans un conteneur — motif vérifié en pratique
    (inventaire manuel du HP, 2026-08-20) sur les 19 conteneurs SQLite du stack."""
    code, sortie = await _exec(client, conteneur_id,
                                ["find", "/data", "-maxdepth", "2", "-iname", "*.db"])
    if code != 0:
        return []
    return [l for l in sortie.decode("utf-8", "ignore").splitlines() if l.strip()]


async def decouvrir_sources(client: httpx.AsyncClient) -> list[dict]:
    """Inventaire dynamique : interroge Docker plutôt qu'une liste figée (une liste en dur
    serait fausse dès la prochaine brique ajoutée — cf. spec). Ne considère que les
    conteneurs ACTIFS (`/containers/json` sans `all=true` ne renvoie que ceux-là)."""
    r = await client.get("/containers/json")
    r.raise_for_status()
    sources: list[dict] = []
    for resume in r.json():
        conteneur_id = resume["Id"]
        nom = resume["Names"][0].lstrip("/")
        if _est_postgres(resume.get("Image", "")):
            insp = await client.get(f"/containers/{conteneur_id}/json")
            insp.raise_for_status()
            env = dict(e.split("=", 1) for e in insp.json()["Config"]["Env"] if "=" in e)
            user = env.get("POSTGRES_USER", "postgres")
            db = env.get("POSTGRES_DB", user)
            sources.append({"brique": nom, "type": "postgres", "conteneur_id": conteneur_id,
                             "db": db, "user": user})
        else:
            for chemin in await _chercher_sqlite(client, conteneur_id):
                sources.append({"brique": nom, "type": "sqlite", "conteneur_id": conteneur_id,
                                 "chemin": chemin})
    return sources


async def decouvrir_conteneurs_par_brique(client: httpx.AsyncClient) -> dict[str, str]:
    """Nom de brique (= nom du conteneur) → id du conteneur, pour les conteneurs ACTIFS.
    Utilisé par la restauration pour retrouver la cible d'une entrée du manifeste."""
    r = await client.get("/containers/json")
    r.raise_for_status()
    return {resume["Names"][0].lstrip("/"): resume["Id"] for resume in r.json()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: PASS (tous les tests, y compris ceux de Task 1)

- [ ] **Step 5: Commit**

```bash
git add core/sauvegarde_usb.py core/test_sauvegarde_usb.py
git commit -m "feat(sauvegarde-usb): découverte dynamique des sources Postgres/SQLite"
```

---

### Task 3: Garde-fous (sentinelle, espace disque)

**Files:**
- Modify: `core/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb.py`

**Interfaces:**
- Produces: `SENTINELLE_NOM = ".cle-sauvegarde-workplace"`,
  `verifier_sentinelle(destination: Path) -> None` (lève `RuntimeError`),
  `verifier_espace(destination: Path, octets_requis: int) -> None` (lève `RuntimeError`).

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb.py (ajouts)
from pathlib import Path


def test_verifier_sentinelle_absente_leve(tmp_path):
    with pytest.raises(RuntimeError, match="sentinelle"):
        sauvegarde_usb.verifier_sentinelle(tmp_path)


def test_verifier_sentinelle_presente_ne_leve_pas(tmp_path):
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")
    sauvegarde_usb.verifier_sentinelle(tmp_path)  # ne doit rien lever


def test_verifier_espace_insuffisant_leve(tmp_path, monkeypatch):
    import shutil as shutil_mod

    class FauxUsage:
        free = 100

    monkeypatch.setattr(shutil_mod, "disk_usage", lambda _: FauxUsage())
    with pytest.raises(RuntimeError, match="Espace insuffisant"):
        sauvegarde_usb.verifier_espace(tmp_path, octets_requis=1_000_000)


def test_verifier_espace_suffisant_ne_leve_pas(tmp_path, monkeypatch):
    import shutil as shutil_mod

    class FauxUsage:
        free = 10_000_000

    monkeypatch.setattr(shutil_mod, "disk_usage", lambda _: FauxUsage())
    sauvegarde_usb.verifier_espace(tmp_path, octets_requis=1_000_000)  # ne doit rien lever
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v -k "sentinelle or espace"`
Expected: FAIL (`AttributeError`, fonctions absentes)

- [ ] **Step 3: Write minimal implementation**

```python
# core/sauvegarde_usb.py (ajouts en tête, après les imports)
import shutil
from pathlib import Path

SENTINELLE_NOM = ".cle-sauvegarde-workplace"


def verifier_sentinelle(destination: Path) -> None:
    """Garde-fou anti-écriture-silencieuse : refuse si le fichier sentinelle n'est pas déjà
    présent à la racine du point de montage. Posé une fois, à la main, lors de la
    préparation de la clé (cf. outils/sauvegarde-usb/README.md) — son absence signifie soit
    que la clé n'est pas vraiment montée (le dossier existe mais est vide), soit qu'il ne
    s'agit pas de LA clé de sauvegarde. Sans ce garde-fou, une sauvegarde lancée avec une clé
    débranchée écrirait silencieusement sur le disque interne du HP."""
    if not (destination / SENTINELLE_NOM).exists():
        raise RuntimeError(
            f"Clé de sauvegarde absente ou non montée sur {destination} "
            f"(fichier sentinelle « {SENTINELLE_NOM} » introuvable)."
        )


def verifier_espace(destination: Path, octets_requis: int) -> None:
    """Abandon propre AVANT d'écrire quoi que ce soit si la clé n'a pas la place."""
    libre = shutil.disk_usage(destination).free
    if libre < octets_requis:
        raise RuntimeError(
            f"Espace insuffisant sur {destination} : {libre} octet(s) libre(s), "
            f"{octets_requis} requis."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add core/sauvegarde_usb.py core/test_sauvegarde_usb.py
git commit -m "feat(sauvegarde-usb): garde-fous sentinelle + espace disque"
```

---

### Task 4: Sauvegarde — dump SQLite/Postgres + manifest.json

**Files:**
- Modify: `core/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb.py`

**Interfaces:**
- Consumes: `_docker_client`, `_exec`, `decouvrir_sources`, `verifier_sentinelle`,
  `verifier_espace` (Tasks 1-3).
- Produces: `async def sauvegarder(destination: Path) -> dict` (renvoie le manifeste écrit).
  Format du manifeste (persisté dans `<destination>/manifest.json`) :
  `{"horodatage": str ISO 8601, "sources": [{"brique": str, "type": "sqlite"|"postgres",
  "fichier": str|None, "taille_octets": int, "ignore": bool, "raison": str|None,
  "chemin"?: str, "db"?: str, "user"?: str}]}`.

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb.py (ajouts)
import io
import json
import tarfile


def _tar_dun_fichier(nom: str, contenu: bytes) -> bytes:
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        info = tarfile.TarInfo(name=nom)
        info.size = len(contenu)
        tar.addfile(info, io.BytesIO(contenu))
    return tampon.getvalue()


def test_sauvegarder_ecrit_manifest_et_fichiers(tmp_path, monkeypatch):
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")

    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin == "/containers/sq1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/donnees.db\n"))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 0})
        if chemin == "/containers/pg1/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory"]}})
        if chemin == "/containers/sq1/archive":
            return httpx.Response(200, content=_tar_dun_fichier("donnees.db", b"contenu-sqlite"))
        if chemin == "/containers/pg1/exec":
            return httpx.Response(200, json={"Id": "exec-dump"})
        if chemin == "/exec/exec-dump/start":
            return httpx.Response(200, content=_cadre_exec(1, b"-- dump sql --\n"))
        if chemin == "/exec/exec-dump/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {chemin}")

    # `_docker_client` réel est une fonction SYNCHRONE qui renvoie un `httpx.AsyncClient`
    # (utilisé ensuite en `async with`) — le remplacement doit garder la même forme, pas
    # devenir une coroutine (sinon `async with _docker_client()` échoue : on ne peut pas
    # ouvrir un contexte async sur une coroutine non attendue).
    def _client_de_test():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")

    monkeypatch.setattr(sauvegarde_usb, "_docker_client", _client_de_test)

    manifeste = asyncio.run(sauvegarde_usb.sauvegarder(tmp_path))

    assert (tmp_path / "manifest.json").exists()
    disque = json.loads((tmp_path / "manifest.json").read_text())
    assert disque == manifeste
    par_brique = {s["brique"]: s for s in manifeste["sources"]}
    assert par_brique["workplace_donnees"]["fichier"] == "donnees.db"
    assert (tmp_path / "workplace_donnees" / "donnees.db").read_bytes() == b"contenu-sqlite"
    assert par_brique["memoire-memoire-db-1"]["fichier"] == "memory.sql"
    assert (tmp_path / "memoire-memoire-db-1" / "memory.sql").read_bytes() == b"-- dump sql --\n"
    assert all("conteneur_id" not in s for s in manifeste["sources"])


def test_sauvegarder_refuse_sans_sentinelle(tmp_path):
    with pytest.raises(RuntimeError, match="sentinelle"):
        asyncio.run(sauvegarde_usb.sauvegarder(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v -k sauvegarder`
Expected: FAIL (`AttributeError: module 'sauvegarde_usb' has no attribute 'sauvegarder'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/sauvegarde_usb.py (ajouts)
import io
import json
import tarfile
from datetime import datetime, timezone


def _sans_conteneur_id(source: dict) -> dict:
    """Le manifeste est portable (lu sur une AUTRE machine) : l'id de conteneur n'y a pas
    sa place, il ne sera de toute façon plus valide ailleurs."""
    return {k: v for k, v in source.items() if k != "conteneur_id"}


async def _taille_sqlite(client: httpx.AsyncClient, source: dict) -> int:
    code, sortie = await _exec(client, source["conteneur_id"], ["stat", "-c", "%s", source["chemin"]])
    if code != 0:
        return 0
    try:
        return int(sortie.decode().strip())
    except ValueError:
        return 0


async def _taille_postgres(client: httpx.AsyncClient, source: dict) -> int:
    cmd = ["psql", "-U", source["user"], "-d", source["db"], "-tAc",
           f"SELECT pg_database_size('{source['db']}');"]
    code, sortie = await _exec(client, source["conteneur_id"], cmd)
    if code != 0:
        return 0
    try:
        return int(sortie.decode().strip())
    except ValueError:
        return 0


async def _copier_sqlite(client: httpx.AsyncClient, source: dict, dest_dir: Path) -> str:
    """Équivalent `docker cp <conteneur>:<chemin> <dest>` via l'API `archive` (GET)."""
    r = await client.get(f"/containers/{source['conteneur_id']}/archive",
                          params={"path": source["chemin"]})
    r.raise_for_status()
    dest_dir.mkdir(parents=True, exist_ok=True)
    nom_fichier = Path(source["chemin"]).name
    with tarfile.open(fileobj=io.BytesIO(r.content)) as tar:
        membre = tar.getmembers()[0]
        with tar.extractfile(membre) as src:
            (dest_dir / nom_fichier).write_bytes(src.read())
    return nom_fichier


async def _dumper_postgres(client: httpx.AsyncClient, source: dict, dest_dir: Path) -> str:
    """Dump LOGIQUE (`pg_dump`), jamais de copie brute du répertoire de données — un dump
    logique est portable entre machines/versions, une copie brute ne l'est pas (cf. spec)."""
    code, sortie = await _exec(client, source["conteneur_id"],
                                ["pg_dump", "-U", source["user"], source["db"]])
    if code != 0:
        raise RuntimeError(
            f"pg_dump a échoué sur « {source['db']} » (code {code}) : "
            f"{sortie.decode('utf-8', 'ignore')[:300]}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    nom_fichier = f"{source['db']}.sql"
    (dest_dir / nom_fichier).write_bytes(sortie)
    return nom_fichier


async def sauvegarder(destination: Path) -> dict:
    """Instantané à la demande de toutes les bases actives, écrasant le précédent sur
    `destination`. Un conteneur arrêté est simplement absent (pas d'échec global) ; un dump
    qui échoue laisse une entrée `ignore: true` avec la raison, plutôt que de tout stopper."""
    verifier_sentinelle(destination)
    async with _docker_client() as client:
        sources = await decouvrir_sources(client)
        tailles = [
            await (_taille_sqlite(client, s) if s["type"] == "sqlite" else _taille_postgres(client, s))
            for s in sources
        ]
        verifier_espace(destination, sum(tailles))

        entrees = []
        for source, taille in zip(sources, tailles):
            dest_dir = destination / source["brique"]
            try:
                if source["type"] == "sqlite":
                    fichier = await _copier_sqlite(client, source, dest_dir)
                else:
                    fichier = await _dumper_postgres(client, source, dest_dir)
            except Exception as e:  # noqa: BLE001 — une source en échec ne bloque pas les autres
                entrees.append({**_sans_conteneur_id(source), "fichier": None,
                                 "taille_octets": 0, "ignore": True, "raison": str(e)})
                continue
            entrees.append({**_sans_conteneur_id(source), "fichier": fichier,
                             "taille_octets": taille, "ignore": False, "raison": None})

    manifeste = {"horodatage": datetime.now(timezone.utc).isoformat(), "sources": entrees}
    (destination / "manifest.json").write_text(json.dumps(manifeste, ensure_ascii=False, indent=2))
    return manifeste
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add core/sauvegarde_usb.py core/test_sauvegarde_usb.py
git commit -m "feat(sauvegarde-usb): sauvegarde — dump SQLite/Postgres + manifest.json"
```

---

### Task 5: Restauration depuis le manifest

**Files:**
- Modify: `core/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb.py`

**Interfaces:**
- Consumes: `_docker_client`, `_exec`, `decouvrir_conteneurs_par_brique`,
  `verifier_sentinelle` (Tasks 1-3).
- Produces: `async def restaurer(source: Path) -> dict` — renvoie
  `{"resultats": [{"brique": str, "ok": bool, "message": str|None}]}`.

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb.py (ajouts)
def test_restaurer_sqlite_et_postgres(tmp_path, monkeypatch):
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")
    (tmp_path / "workplace_donnees").mkdir()
    (tmp_path / "workplace_donnees" / "donnees.db").write_bytes(b"contenu-sqlite")
    (tmp_path / "memoire-memoire-db-1").mkdir()
    (tmp_path / "memoire-memoire-db-1" / "memory.sql").write_bytes(b"-- dump --")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "horodatage": "2026-08-20T18:00:00+00:00",
        "sources": [
            {"brique": "workplace_donnees", "type": "sqlite", "chemin": "/data/donnees.db",
             "fichier": "donnees.db", "taille_octets": 14, "ignore": False, "raison": None},
            {"brique": "memoire-memoire-db-1", "type": "postgres", "db": "memory",
             "user": "memory", "fichier": "memory.sql", "taille_octets": 10,
             "ignore": False, "raison": None},
            {"brique": "brique-arretee", "type": "sqlite", "chemin": "/data/x.db",
             "fichier": "x.db", "taille_octets": 1, "ignore": False, "raison": None},
        ],
    }))

    appels_put = []

    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin in ("/containers/sq1/archive", "/containers/pg1/archive") and request.method == "PUT":
            appels_put.append(chemin)
            return httpx.Response(200)
        if chemin == "/containers/pg1/exec":
            return httpx.Response(200, json={"Id": "exec-psql"})
        if chemin == "/exec/exec-psql/start":
            return httpx.Response(200, content=_cadre_exec(1, b""))
        if chemin == "/exec/exec-psql/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {request.method} {chemin}")

    def _client_de_test():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")

    monkeypatch.setattr(sauvegarde_usb, "_docker_client", _client_de_test)

    resultat = asyncio.run(sauvegarde_usb.restaurer(tmp_path))
    par_brique = {r["brique"]: r for r in resultat["resultats"]}

    assert par_brique["workplace_donnees"]["ok"] is True
    assert par_brique["memoire-memoire-db-1"]["ok"] is True
    assert par_brique["brique-arretee"]["ok"] is False
    assert "introuvable" in par_brique["brique-arretee"]["message"]
    assert appels_put == ["/containers/sq1/archive", "/containers/pg1/archive"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v -k restaurer`
Expected: FAIL (`AttributeError: module 'sauvegarde_usb' has no attribute 'restaurer'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/sauvegarde_usb.py (ajouts)

def _tar_dun_fichier(chemin_local: Path, nom_dans_tar: str) -> bytes:
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        tar.add(chemin_local, arcname=nom_dans_tar)
    return tampon.getvalue()


async def _restaurer_sqlite(client: httpx.AsyncClient, conteneur_id: str, entree: dict,
                            source_dir: Path) -> None:
    chemin_local = source_dir / entree["brique"] / entree["fichier"]
    contenu_tar = _tar_dun_fichier(chemin_local, entree["fichier"])
    dossier_cible = str(Path(entree["chemin"]).parent)
    r = await client.put(f"/containers/{conteneur_id}/archive",
                          params={"path": dossier_cible}, content=contenu_tar)
    r.raise_for_status()


async def _restaurer_postgres(client: httpx.AsyncClient, conteneur_id: str, entree: dict,
                              source_dir: Path) -> None:
    chemin_local = source_dir / entree["brique"] / entree["fichier"]
    contenu_tar = _tar_dun_fichier(chemin_local, "restaurer.sql")
    r = await client.put(f"/containers/{conteneur_id}/archive",
                          params={"path": "/tmp"}, content=contenu_tar)
    r.raise_for_status()
    cmd = ["sh", "-c", f"psql -U {entree['user']} {entree['db']} < /tmp/restaurer.sql"]
    code, sortie = await _exec(client, conteneur_id, cmd)
    if code != 0:
        raise RuntimeError(
            f"Restauration Postgres échouée (code {code}) : "
            f"{sortie.decode('utf-8', 'ignore')[:300]}")


async def restaurer(source: Path) -> dict:
    """Symétrique de `sauvegarder` : relit `manifest.json`, réinjecte chaque source dans le
    conteneur ACTIF portant le même nom de brique. Une brique introuvable (conteneur pas
    démarré) ou une entrée déjà marquée `ignore` est signalée sans bloquer les autres."""
    verifier_sentinelle(source)
    manifeste_path = source / "manifest.json"
    if not manifeste_path.exists():
        raise RuntimeError(f"Aucun manifest.json trouvé sur {source}.")
    manifeste = json.loads(manifeste_path.read_text())

    resultats = []
    async with _docker_client() as client:
        conteneurs = await decouvrir_conteneurs_par_brique(client)
        for entree in manifeste["sources"]:
            if entree.get("ignore"):
                resultats.append({"brique": entree["brique"], "ok": False,
                                   "message": "Ignorée à la sauvegarde : " + (entree.get("raison") or "")})
                continue
            conteneur_id = conteneurs.get(entree["brique"])
            if not conteneur_id:
                resultats.append({"brique": entree["brique"], "ok": False,
                                   "message": "Conteneur cible introuvable (brique arrêtée ?)."})
                continue
            try:
                if entree["type"] == "sqlite":
                    await _restaurer_sqlite(client, conteneur_id, entree, source)
                else:
                    await _restaurer_postgres(client, conteneur_id, entree, source)
                resultats.append({"brique": entree["brique"], "ok": True, "message": None})
            except Exception as e:  # noqa: BLE001 — une brique en échec ne bloque pas les autres
                resultats.append({"brique": entree["brique"], "ok": False, "message": str(e)})
    return {"resultats": resultats}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add core/sauvegarde_usb.py core/test_sauvegarde_usb.py
git commit -m "feat(sauvegarde-usb): restauration symétrique depuis le manifest"
```

---

### Task 6: Export du `.env`

**Files:**
- Modify: `core/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb.py`

**Interfaces:**
- Produces: `lire_env() -> str` (lève `RuntimeError` si le fichier est absent).

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb.py (ajouts)
def test_lire_env_absent_leve(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV_RACINE_PATH", str(tmp_path / "absent.env"))
    with pytest.raises(RuntimeError, match="introuvable"):
        sauvegarde_usb.lire_env()


def test_lire_env_renvoie_le_contenu(tmp_path, monkeypatch):
    fichier = tmp_path / "vrai.env"
    fichier.write_text("GATEWAY_KEY=abc123\n")
    monkeypatch.setenv("ENV_RACINE_PATH", str(fichier))
    assert sauvegarde_usb.lire_env() == "GATEWAY_KEY=abc123\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v -k lire_env`
Expected: FAIL (`AttributeError: module 'sauvegarde_usb' has no attribute 'lire_env'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/sauvegarde_usb.py (ajouts)

def lire_env() -> str:
    """Contenu brut du `.env` racine, monté en lecture seule dans `core` (cf.
    `core/docker-compose.yml`, Task 8). Simple sortie du fichier — c'est à l'utilisateur de
    le ranger ensuite où il veut (Drive, doc…) ; aucune écriture vers un service externe."""
    chemin = Path(os.getenv("ENV_RACINE_PATH", "/env-racine/.env"))
    if not chemin.exists():
        raise RuntimeError(f".env introuvable à {chemin}.")
    return chemin.read_text()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add core/sauvegarde_usb.py core/test_sauvegarde_usb.py
git commit -m "feat(sauvegarde-usb): export du contenu du .env racine"
```

---

### Task 7: Routeur FastAPI + auth double (session ou `NOYAU_KEY`)

**Files:**
- Create: `core/routers/sauvegarde_usb.py`
- Test: `core/test_sauvegarde_usb_router.py`
- Modify: `core/main.py`

**Interfaces:**
- Consumes: `sauvegarde_usb.sauvegarder`, `sauvegarde_usb.restaurer`,
  `sauvegarde_usb.lire_env` (Tasks 4-6), `auth.exiger_session` (existant, `core/auth.py:195`).
- Produces: `router` (APIRouter) avec 3 routes :
  `POST /sauvegarde-usb/lancer`, `POST /sauvegarde-usb/restaurer`,
  `GET /sauvegarde-usb/env`.

**Pourquoi une auth double** : la brique « noyau » (= `core` lui-même) n'a pas de clé de
service comme les autres briques (`NOYAU_KEY` n'existe pas encore, cf. `orchestrateur.py:
entetes_brique`) — sans elle, le dispatch dynamique de capacités (`outils_communs._appel_dynamique`,
appelé par le LLM en tour d'outil) atteindrait cette route SANS cookie de session (c'est un
appel serveur→serveur en boucle sur lui-même, `NOYAU_URL=http://127.0.0.1:5000`). Il faut donc
accepter SOIT une session navigateur valide (bouton du dashboard) SOIT une clé de service
`X-API-Key: NOYAU_KEY` (appel LLM). Cette clé est **obligatoire** dès qu'on veut que la
capacité assistant fonctionne — pas de mode ouvert, vu la sensibilité (export de TOUS les
secrets du stack en clair sur une des 3 routes).

- [ ] **Step 1: Write the failing test**

```python
# core/test_sauvegarde_usb_router.py
import os
from unittest.mock import AsyncMock

os.environ.setdefault("NOYAU_KEY", "cle-test-noyau")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
import sauvegarde_usb
from routers import sauvegarde_usb as routeur_sauvegarde_usb


def _app():
    app = FastAPI()
    app.include_router(routeur_sauvegarde_usb.router)
    return app


def test_lancer_refuse_sans_auth(monkeypatch):
    # AUTH_ENABLED est un CONSTANTE de module lue à l'import (core/auth.py:54) : la forcer
    # avec monkeypatch.setattr (pas setenv, qui n'aurait aucun effet après l'import).
    # AUTH_ENABLED=false (défaut dev/tests) laisserait passer en identité anonyme — ce n'est
    # PAS ce qu'on teste ici (on teste le refus quand l'auth est vraiment exigée).
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    client = TestClient(_app(), follow_redirects=False)
    r = client.post("/sauvegarde-usb/lancer")
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login"


def test_lancer_accepte_cle_service(monkeypatch):
    monkeypatch.setattr(sauvegarde_usb, "sauvegarder", AsyncMock(
        return_value={"horodatage": "2026-08-20T18:00:00+00:00", "sources": []}))
    client = TestClient(_app())
    r = client.post("/sauvegarde-usb/lancer", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 200
    assert r.json()["sources"] == []


def test_lancer_refuse_mauvaise_cle_service(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    client = TestClient(_app(), follow_redirects=False)
    r = client.post("/sauvegarde-usb/lancer", headers={"X-API-Key": "mauvaise-cle"})
    assert r.status_code == 303


def test_lancer_echec_devient_400(monkeypatch):
    monkeypatch.setattr(sauvegarde_usb, "sauvegarder",
                         AsyncMock(side_effect=RuntimeError("Clé de sauvegarde absente")))
    client = TestClient(_app())
    r = client.post("/sauvegarde-usb/lancer", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 400
    assert "absente" in r.json()["detail"]


def test_env_accepte_cle_service(monkeypatch):
    monkeypatch.setattr(sauvegarde_usb, "lire_env", lambda: "GATEWAY_KEY=abc\n")
    client = TestClient(_app())
    r = client.get("/sauvegarde-usb/env", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 200
    assert r.text == "GATEWAY_KEY=abc\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_sauvegarde_usb_router.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'routers.sauvegarde_usb'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/routers/sauvegarde_usb.py
"""Routes « sauvegarde-usb » du Cœur — instantané portable à la demande (S233, cf.
docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md).

Auth double (cf. plan, Task 7) : session navigateur (bouton dashboard) OU clé de service
`X-API-Key: NOYAU_KEY` (dispatch dynamique de capacités, appel LLM en boucle sur lui-même)."""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

import auth
import sauvegarde_usb

router = APIRouter(prefix="/sauvegarde-usb", tags=["sauvegarde-usb"])

MONTAGE = Path(os.getenv("SAUVEGARDE_USB_MONTAGE", "/mnt/sauvegarde-usb"))


async def _exiger_session_ou_cle_noyau(request: Request) -> dict:
    cle_recue = request.headers.get("X-API-Key")
    cle_attendue = os.environ.get("NOYAU_KEY", "")
    if cle_recue and cle_attendue and cle_recue == cle_attendue:
        return {"sub": "service", "nom": None, "avatarEmoji": None}
    return await auth.exiger_session(request)


@router.post("/lancer")
async def lancer(_identite: dict = Depends(_exiger_session_ou_cle_noyau)):
    try:
        return await sauvegarde_usb.sauvegarder(MONTAGE)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/restaurer")
async def restaurer(_identite: dict = Depends(_exiger_session_ou_cle_noyau)):
    try:
        return await sauvegarde_usb.restaurer(MONTAGE)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/env")
async def env(_identite: dict = Depends(_exiger_session_ou_cle_noyau)):
    try:
        return PlainTextResponse(sauvegarde_usb.lire_env())
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_sauvegarde_usb_router.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire into `core/main.py`**

Ouvrir `core/main.py`, ajouter `sauvegarde_usb` à l'import groupé des routers (ligne 24) et
inclure le routeur juste après `app.include_router(systeme.router)` (ligne 85) — PAS de
`dependencies=[Depends(exiger_session)]` au niveau de l'`include_router` (l'auth double est
gérée PAR ROUTE, à l'intérieur du module, pour accepter aussi la clé de service) :

```python
# core/main.py — dans le bloc d'import (ligne 24), ajouter sauvegarde_usb à la liste :
from routers import (agenda, assistant, atelier_images_video_proxy, atelier_veille_proxy,
                      # ... (reste de la liste inchangé) ...
                      sauvegarde_usb)

# core/main.py — après app.include_router(systeme.router) :
app.include_router(sauvegarde_usb.router)
```

- [ ] **Step 6: Run full core test suite to check no regression**

Run: `cd core && python3 -m pytest -q`
Expected: PASS (aucune régression sur les routers existants)

- [ ] **Step 7: Commit**

```bash
git add core/routers/sauvegarde_usb.py core/test_sauvegarde_usb_router.py core/main.py
git commit -m "feat(sauvegarde-usb): routeur FastAPI + auth double (session ou NOYAU_KEY)"
```

---

### Task 8: Câblage infra — docker-compose, `.env.example`, manifest `noyau`

**Files:**
- Modify: `core/docker-compose.yml`
- Modify: `.env.example`
- Modify: `briques/noyau/manifest.json`

**Interfaces:**
- Consumes: routes `POST /sauvegarde-usb/lancer`, `POST /sauvegarde-usb/restaurer`,
  `GET /sauvegarde-usb/env` (Task 7).
- Produces : les 3 capacités deviennent visibles du catalogue de l'assistant
  (`core/catalogue.py::collecter_capacites`, déjà générique — rien à modifier là).

- [ ] **Step 1: Ajouter les montages et `NOYAU_KEY` à `core/docker-compose.yml`**

Dans le bloc `environment:` de `core`, ajouter (à côté des autres clés de service déjà
commentées, ex. `AGENDA_KEY`) :

```yaml
      # NOYAU_KEY vient du .env racine via env_file — NE PAS la redéclarer en
      # `NOYAU_KEY=${NOYAU_KEY:-}` (piège « env shadow », cf. AGENDA_KEY plus haut) :
      # c'est la clé de service que le dispatch dynamique de capacités envoie en
      # X-API-Key pour joindre les 3 routes /sauvegarde-usb/* du noyau lui-même
      # (S233) — sans elle, le LLM ne peut pas déclencher sauvegarde/restauration/export.
      - SAUVEGARDE_USB_MONTAGE=${SAUVEGARDE_USB_MONTAGE:-/mnt/sauvegarde-usb}
      - ENV_RACINE_PATH=/env-racine/.env
```

Dans le bloc `volumes:` de `core`, ajouter (à côté du montage du `.env` de la Gateway) :

```yaml
      # .env racine en LECTURE SEULE (S233, export via ⚙ Sauvegarde) — jamais en écriture,
      # ce module ne modifie jamais le .env, il ne fait que le lire pour l'exporter.
      - ../.env:/env-racine/.env:ro
      # Point de montage de la clé USB de sauvegarde portable (S233) — monté par une règle
      # udev sur le HP (cf. outils/sauvegarde-usb/), vide/absent hors HP (le garde-fou
      # sentinelle de sauvegarde_usb.py refuse alors proprement, cf. Task 3).
      - ${SAUVEGARDE_USB_MONTAGE:-/mnt/sauvegarde-usb}:/mnt/sauvegarde-usb
```

- [ ] **Step 2: Ajouter les variables à `.env.example`**

Après le bloc « Sauvegarde continue (RPO…) » déjà présent (autour de la ligne 565), ajouter
une nouvelle section :

```bash
# ── Sauvegarde portable sur clé USB (S233, à la demande, sans cloud) ──────────────────────
# Remplace, pour l'usage « instantané ponctuel emporté sur un autre PC », la réplication
# continue ci-dessus (jamais branchée en prod). Voir
# docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md.
# Chemin HÔTE (HP) où la clé USB est montée (règle udev, cf. outils/sauvegarde-usb/README.md).
SAUVEGARDE_USB_MONTAGE=/mnt/sauvegarde-usb
# Clé de service que le dispatch dynamique de capacités envoie en X-API-Key pour joindre les
# routes /sauvegarde-usb/* du noyau — OBLIGATOIRE (comme JEU_FACTIONS_PUBLIC_SECRET, aucun
# mode ouvert vu la sensibilité : une des 3 routes exporte tous les secrets du stack en
# clair). Génère une clé : `openssl rand -hex 32`.
NOYAU_KEY=
```

- [ ] **Step 3: Ajouter les 3 capacités à `briques/noyau/manifest.json`**

Ajouter un champ `"capacites"` (absent aujourd'hui, seul `"taches"` existe) :

```json
  "capacites": [
    {
      "nom": "sauvegarde_usb_lancer",
      "description": "Sauvegarde un instantané de toutes les bases du stack (Postgres et SQLite, découvertes dynamiquement) sur la clé USB actuellement branchée sur le HP. Écrase l'instantané précédent — un seul à la fois. Sert « sauvegarde sur la clé », « fais une sauvegarde ». Nécessite que la clé soit déjà branchée et préparée (fichier sentinelle posé).",
      "methode": "POST",
      "chemin": "/sauvegarde-usb/lancer",
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "sauvegarde_usb_restaurer",
      "description": "Restaure toutes les bases depuis l'instantané présent sur la clé USB actuellement branchée, dans les conteneurs déjà démarrés du stack local. Sert « restaure depuis la clé », après avoir cloné le dépôt et démarré le Cœur sur une machine neuve.",
      "methode": "POST",
      "chemin": "/sauvegarde-usb/restaurer",
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "env_exporter",
      "description": "Renvoie le contenu actuel du fichier .env racine (tous les secrets/clés API du stack), pour que l'utilisateur le range lui-même où il veut (Drive, autre clé…). N'écrit jamais vers un service externe. Sert « exporte le .env », « donne-moi les secrets pour les sauvegarder ».",
      "methode": "GET",
      "chemin": "/sauvegarde-usb/env",
      "action": true,
      "niveau": 1,
      "socle": false
    }
  ],
```

- [ ] **Step 4: Vérifier que le manifest reste un JSON valide et que le registre le charge**

Run: `python3 -c "import json; json.load(open('briques/noyau/manifest.json'))" && echo OK`
Expected: `OK`

Puis (test d'intégration léger, sans Docker) :
Run: `cd core && python3 -m pytest test_conscience.py -v` (le test existant qui valide déjà
la structure du registre autour de « noyau », cf. `core/test_conscience.py:24-46` lu pendant
le cadrage — vérifie qu'il n'y a pas de régression sur son exclusion des « organes »)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/docker-compose.yml .env.example briques/noyau/manifest.json
git commit -m "feat(sauvegarde-usb): câblage infra — montages, NOYAU_KEY, capacités noyau"
```

---

### Task 9: Bouton dashboard (sauvegarde / restauration / export .env)

**Files:**
- Modify: `core/dashboard.html`

**Interfaces:**
- Consumes: `POST /sauvegarde-usb/lancer`, `POST /sauvegarde-usb/restaurer`,
  `GET /sauvegarde-usb/env` (Task 7) — appelées en `fetch` depuis le navigateur, session déjà
  posée par le cookie (`exiger_session`), pas de `X-API-Key` à ajouter côté front.

- [ ] **Step 1: Ajouter un panneau « Sauvegarde » avec 3 boutons**

Repérer dans `core/dashboard.html` la zone des panneaux ⚙ existants (ex. section « Cerveau »,
autour de la ligne 500-560, motif `btn-cle`/`enregistrerCle` déjà lu pendant le cadrage) et
ajouter, sur le même modèle :

```html
<div class="panel">
  <h3>💾 Sauvegarde portable (clé USB)</h3>
  <p class="hint">Instantané à la demande de toutes les bases du stack, sur la clé USB
     branchée sur le HP. Un seul instantané à la fois (écrase le précédent).</p>
  <button class="btn" id="btn-sauvegarde-lancer" onclick="lancerSauvegardeUsb()">Sauvegarder sur la clé</button>
  <button class="btn ghost" id="btn-sauvegarde-restaurer" onclick="restaurerSauvegardeUsb()">Restaurer depuis la clé</button>
  <button class="btn ghost" id="btn-env-exporter" onclick="exporterEnv()">Exporter le .env</button>
  <div id="sauvegarde-msg"></div>
</div>
```

- [ ] **Step 2: Ajouter les 3 fonctions JS (motif `enregistrerCle`, cf. `dashboard.html:2455`)**

```javascript
function sauvegardeMsg(texte, type) {
  const el = document.getElementById('sauvegarde-msg');
  el.textContent = texte;
  el.className = type === 'ok' ? 'ok' : (type === 'ko' ? 'ko' : '');
}

async function lancerSauvegardeUsb() {
  const btn = document.getElementById('btn-sauvegarde-lancer');
  btn.classList.add('loading');
  sauvegardeMsg('Sauvegarde en cours…', 'info');
  try {
    const r = await fetch('/sauvegarde-usb/lancer', { method: 'POST' });
    const d = await r.json();
    if (r.ok) {
      const ignorees = (d.sources || []).filter(s => s.ignore).length;
      sauvegardeMsg(`✔ ${d.sources.length - ignorees} base(s) sauvegardée(s)` +
                    (ignorees ? `, ${ignorees} ignorée(s).` : '.'), 'ok');
    } else {
      sauvegardeMsg('⚠ ' + (d.detail || 'échec'), 'ko');
    }
  } catch (e) { sauvegardeMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}

async function restaurerSauvegardeUsb() {
  const btn = document.getElementById('btn-sauvegarde-restaurer');
  btn.classList.add('loading');
  sauvegardeMsg('Restauration en cours…', 'info');
  try {
    const r = await fetch('/sauvegarde-usb/restaurer', { method: 'POST' });
    const d = await r.json();
    if (r.ok) {
      const echecs = (d.resultats || []).filter(x => !x.ok);
      sauvegardeMsg(echecs.length
        ? `⚠ ${echecs.length} brique(s) en échec : ` + echecs.map(x => x.brique).join(', ')
        : '✔ Toutes les bases restaurées.', echecs.length ? 'ko' : 'ok');
    } else {
      sauvegardeMsg('⚠ ' + (d.detail || 'échec'), 'ko');
    }
  } catch (e) { sauvegardeMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}

async function exporterEnv() {
  const r = await fetch('/sauvegarde-usb/env');
  if (!r.ok) { sauvegardeMsg('⚠ Export .env impossible.', 'ko'); return; }
  const texte = await r.text();
  const lien = document.createElement('a');
  lien.href = URL.createObjectURL(new Blob([texte], { type: 'text/plain' }));
  lien.download = '.env';
  lien.click();
  URL.revokeObjectURL(lien.href);
}
```

- [ ] **Step 3: Test manuel dans un navigateur**

Démarrer le Cœur localement (`cd core && docker compose up -d --build` ou
`uvicorn main:app --port 5100` selon le mode de preuve déjà en usage dans ce dépôt), ouvrir
`/dashboard`, vérifier que le panneau s'affiche et que les 3 boutons déclenchent bien un appel
réseau (onglet réseau du navigateur) — les réponses réelles (200 vs 400 sentinelle absente)
ne sont testables qu'avec Docker + une clé USB, reporté à la preuve LIVE HP (Task 11).

- [ ] **Step 4: Commit**

```bash
git add core/dashboard.html
git commit -m "feat(sauvegarde-usb): panneau dashboard (sauvegarde/restauration/export .env)"
```

---

### Task 10: Documentation — règle udev + guide d'installation machine neuve

**Files:**
- Create: `outils/sauvegarde-usb/95-workplace-usb.rules`
- Create: `outils/sauvegarde-usb/README.md`
- Create: `docs/INSTALLATION-MACHINE-NEUVE.md`

**Interfaces:** aucune (documentation/config, pas de code Python).

- [ ] **Step 1: Écrire la règle udev**

```
# outils/sauvegarde-usb/95-workplace-usb.rules
# Montage automatique de la clé de sauvegarde portable Workplace (S233) sur le HP.
# Cible une partition par son LABEL (WORKPLACE-USB) plutôt que par device (/dev/sdX change
# selon les ports/l'ordre de branchement) — le label est stable, à poser une fois au
# formatage de la clé (cf. README.md de ce dossier).
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="WORKPLACE-USB", \
  RUN+="/bin/mkdir -p /mnt/sauvegarde-usb", \
  RUN+="/bin/mount -o uid=1000,gid=1000 /dev/%k /mnt/sauvegarde-usb"

ACTION=="remove", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="WORKPLACE-USB", \
  RUN+="/bin/umount /mnt/sauvegarde-usb"
```

- [ ] **Step 2: Écrire le README (préparation de la clé + installation de la règle)**

```markdown
# outils/sauvegarde-usb/README.md

# Sauvegarde portable — préparation de la clé + montage automatique sur le HP

Sur le modèle de `outils/sauvegarde/` (MinIO local, pour Litestream/WAL-G — approche
abandonnée pour cet usage, cf. `docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md`),
ce dossier prépare une sauvegarde **portable, à la demande, sans cloud**.

## 1. Préparer la clé (une seule fois)

1. Formater la clé en ext4 (ou une autre FS Linux) avec le label `WORKPLACE-USB` :
   `sudo mkfs.ext4 -L WORKPLACE-USB /dev/sdX1` (remplacer `sdX1` par la bonne partition —
   vérifier avec `lsblk` avant, ne JAMAIS deviner le device).
2. La monter une fois à la main, y créer le fichier sentinelle, la démonter :
   ```
   sudo mount /dev/sdX1 /mnt/sauvegarde-usb
   sudo touch /mnt/sauvegarde-usb/.cle-sauvegarde-workplace
   sudo umount /mnt/sauvegarde-usb
   ```

## 2. Installer le montage automatique sur le HP

```
sudo cp 95-workplace-usb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Rebrancher la clé : elle doit apparaître montée sur `/mnt/sauvegarde-usb` sans action
manuelle (`mount | grep sauvegarde-usb` pour vérifier).

## 3. Utilisation

Une fois la clé branchée (montée automatiquement), demander à l'assistant « sauvegarde sur
la clé » ou utiliser le bouton du dashboard (⚙ → Sauvegarde). Pour restaurer sur une autre
machine, voir `docs/INSTALLATION-MACHINE-NEUVE.md`.
```

- [ ] **Step 3: Écrire le guide d'installation machine neuve**

```markdown
# docs/INSTALLATION-MACHINE-NEUVE.md

# Installer Workplace sur un PC neuf, avec les données d'une clé de sauvegarde

Destiné à être suivi par un agent de code (Claude Code, OpenCode…) à qui on demande
« installe Workplace ici » — sur le modèle de `MIGRATION-HP.md`, mais pour un PC personnel
plutôt que le HP, et avec restauration depuis une clé USB plutôt qu'un déploiement neuf.

## Ce qui voyage — et ce qui ne voyage pas

- Le CODE voyage par `git clone` (dépôt public/privé GitHub).
- Les SECRETS (`.env`) voyagent par un canal choisi par l'utilisateur (Drive, autre clé…),
  **jamais** par la clé de sauvegarde des bases (cf. spec S233, non-objectifs).
- Les DONNÉES (bases Postgres/SQLite) voyagent par la clé de sauvegarde USB.

## 1. Cloner

```bash
git clone https://github.com/<compte>/workplace.git
cd workplace
```

## 2. Poser le `.env`

Récupérer le fichier `.env` (fourni séparément par l'utilisateur, via le bouton « Exporter le
.env » du dashboard sur l'ancienne machine) et le placer à la racine du dépôt cloné.

## 3. Démarrer le Cœur (et les briques dont on veut restaurer les données)

```bash
cd core && docker compose up -d --build
```

Démarrer aussi, AVANT de demander la restauration, les briques dont on veut récupérer les
données (au minimum leurs conteneurs de base doivent être démarrés pour que la restauration
trouve une cible — cf. `core/sauvegarde_usb.py::decouvrir_conteneurs_par_brique`, Task 5) :

```bash
cd ../briques/<brique> && docker compose up -d --build
```

## 4. Restaurer les données depuis la clé

Brancher la clé de sauvegarde sur CE PC. Le point de montage automatique (règle udev) est
propre au HP — sur un PC personnel, monter manuellement (ou adapter la règle, cf.
`outils/sauvegarde-usb/README.md`) et définir `SAUVEGARDE_USB_MONTAGE` dans le `.env` local
si le point de montage diffère de `/mnt/sauvegarde-usb`.

Une fois le Cœur démarré et la clé montée, demander à l'assistant (dashboard `/dashboard`,
onglet Assistant) : **« restaure depuis la clé »** — ou utiliser le bouton « Restaurer depuis
la clé » du panneau ⚙ Sauvegarde.
```

- [ ] **Step 4: Commit**

```bash
git add outils/sauvegarde-usb/ docs/INSTALLATION-MACHINE-NEUVE.md
git commit -m "docs(sauvegarde-usb): règle udev + guide d'installation machine neuve"
```

---

### Task 11: Preuve LIVE HP (bout-en-bout, régime habituel du projet)

**Files:** aucun (validation, pas de code).

**Interfaces:** aucune.

- [ ] **Step 1: Déployer sur le HP**

```bash
ssh debian@192.168.1.89 'cd ~/workplace && git pull --ff-only'
ssh debian@192.168.1.89 '(cd ~/workplace/core && docker compose up -d --build)'
```

Poser `NOYAU_KEY` (générée via `openssl rand -hex 32`) et `SAUVEGARDE_USB_MONTAGE` dans le
`.env` du HP (même méthode que pour `JEU_FACTIONS_PUBLIC_SECRET`, cf. historique récent de ce
dépôt), puis relancer `core` pour qu'il relise l'env.

- [ ] **Step 2: Installer la règle udev et préparer une vraie clé USB**

Suivre `outils/sauvegarde-usb/README.md` avec une clé USB physique branchée sur le HP.

- [ ] **Step 3: Prouver la sauvegarde**

Demander à l'assistant « sauvegarde sur la clé » (ou bouton dashboard). Vérifier sur la clé :

```bash
ssh debian@192.168.1.89 'ls /mnt/sauvegarde-usb/ && cat /mnt/sauvegarde-usb/manifest.json'
```

Attendu : un `manifest.json` listant les ~28 sources réelles du HP (6 Postgres, ~22 SQLite),
`ignore: false` pour toutes celles dont le conteneur tournait.

- [ ] **Step 4: Prouver la restauration (sur une brique de test, sans casser la prod)**

Choisir UNE brique SQLite à faible enjeu (ex. `veille-info`), noter le contenu actuel d'une
ligne connue, la modifier volontairement, puis restaurer depuis la clé et vérifier que
l'ancienne valeur est revenue :

```bash
ssh debian@192.168.1.89 'docker exec workplace_veille_info sqlite3 /data/veille_info.db "SELECT count(*) FROM sqlite_master;"'
# demander à l'assistant « restaure depuis la clé »
ssh debian@192.168.1.89 'docker exec workplace_veille_info sqlite3 /data/veille_info.db "SELECT count(*) FROM sqlite_master;"'
```

- [ ] **Step 5: Prouver l'export .env**

Cliquer « Exporter le .env » dans le dashboard, vérifier que le fichier téléchargé correspond
bien au `.env` du HP (mêmes clés, mêmes valeurs).

- [ ] **Step 6: Documenter le résultat**

Noter dans une mémoire (auto-memory) le statut LIVE HP réel de ce sprint (comme pour les
sprints précédents), y compris toute limite découverte pendant la preuve.

---

## Self-Review

**Couverture du spec** :
- Découverte dynamique (pas de liste figée) → Task 2. ✅
- Sauvegarde (sentinelle, espace, dump SQLite/Postgres, manifest, écrasement) → Tasks 3-4. ✅
- Restauration symétrique → Task 5. ✅
- Export `.env` séparé, pas d'intégration Drive → Task 6. ✅
- Capacités assistant + gate S222 → Task 8 (le gate lui-même n'est PAS réimplémenté, juste
  déclaré via `"action": true`, cf. `core/outils_communs.py::_appel_dynamique` et
  `core/accord_action.py` déjà lus pendant le cadrage). ✅
- Montage USB automatique (udev) → Task 10. ✅
- Bootstrap machine neuve documenté → Task 10. ✅
- Dashboard → Task 9. ✅
- Tests sans vraie clé USB (dossier temporaire) + preuve LIVE HP → Tasks 1-9 (unitaires) +
  Task 11 (LIVE). ✅

**Points ouverts du spec, tranchés pendant ce plan** :
- Mécanisme d'enregistrement d'une capacité « noyau » → élucidé : champ `capacites` du
  manifest `briques/noyau/manifest.json`, dispatch générique déjà existant
  (`core/catalogue.py` + `core/outils_communs.py::_appel_dynamique`), gate S222 automatique.
  Rien à coder pour le gate lui-même.
- Détection Postgres par image → tranché : motif `postgres|-walg|patroni` (couvre les 6 bases
  réelles du HP).
- Emplacement du point de montage → `/mnt/sauvegarde-usb`, configurable via
  `SAUVEGARDE_USB_MONTAGE`.

**Type consistency** : `sauvegarder(destination: Path) -> dict`,
`restaurer(source: Path) -> dict`, `lire_env() -> str` — signatures identiques entre leur
définition (Tasks 4-6) et leur usage dans le routeur (Task 7) et les tests (Task 7).
`decouvrir_sources`/`decouvrir_conteneurs_par_brique` définis Task 2, consommés Tasks 4-5 sans
changement de signature.
