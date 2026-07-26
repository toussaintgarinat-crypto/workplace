# S195 — Brique audit-fichiers (scan antivirus ClamAV) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une brique autonome `briques/audit-fichiers/` (port **6170**) qui scanne un fichier via ClamAV (protocole clamd) AVANT qu'une autre brique n'accepte ce fichier — vendoring simplifié, MIT, du service `suitenumerique/file-scanner` (ANCT/DINUM), adapté au contexte mono-tenant/famille de Workplace.

**Architecture:** FastAPI + un conteneur sidecar `clamav/clamav:1.4` (le même moteur que l'amont). Notre service parle le protocole **clamd/INSTREAM** via la lib `clamd` (comme `scanners/clamav.py` amont) et expose un seul endpoint utile, **synchrone**, `POST /scanner` (multipart) + `GET /sante`. Auth **API_KEYS** standard Workplace (pas de JWT Ed25519 multi-émetteur amont — YAGNI, voir Risques R1). Câblé en **serveur-à-serveur** dans les deux briques qui acceptent RÉELLEMENT des fichiers uploadés aujourd'hui : `vision` (`/extraire`) et `peertube` (`/videos/upload`) — voir Risque R5 sur pourquoi `mail` et `atelier-images-video`, les deux cibles citées dans le brief, sont re-scopées.

**Tech Stack:** Python 3.12, FastAPI, `clamd==1.0.2` (client Python pur, aucune dépendance native), ClamAV 1.4 (image officielle Docker, sidecar).

---

## Risques / Décisions à trancher (à lire avant d'exécuter)

### R1 — JWT Ed25519 multi-émetteur amont → API_KEYS Workplace (DÉCIDÉ : simplifier)
L'amont authentifie chaque appelant par une paire de clés Ed25519 propre (`iss` dans le JWT, lié à la requête — méthode+cible+corps). C'est nécessaire pour eux : plusieurs organisations indépendantes (La Suite numérique) appellent le même service partagé, sans confiance mutuelle a priori. Workplace est **mono-tenant/famille** : les seuls appelants sont **d'autres briques du même monorepo**, sur la même machine/mesh, qui partagent déjà le motif `API_KEYS` (CSV) + header `X-API-Key` partout (`GUIDE-ajouter-une-brique.md`, vu dans mail/vision/export/video…). Réinventer une paire de clés Ed25519 par appelant serait de la dette : aucun bénéfice de sécurité supplémentaire dans ce contexte (un secret partagé suffit à distinguer « une brique du foyer » d'« un tiers sur Internet »), et un vrai coût (génération/rotation de clés, code de vérification de signature qu'aucune autre brique Workplace n'a). **Décision : `API_KEYS` + `X-API-Key`, clé dédiée `AUDIT_FICHIERS_KEY`** (même convention que `STUDIO_KEY`/`MAIL_KEY`/`ATELIER_IMAGES_VIDEO_KEY`).

### R2 — dramatiq/Redis (scan async + webhook) → tout SYNCHRONE (DÉCIDÉ : simplifier)
L'amont propose un mode async (`POST /scan-async` + file d'attente Redis/dramatiq + webhook signé) pour scanner des fichiers énormes (jusqu'à 2 Gio, récupérés par URL) sans bloquer l'appelant. Le volume attendu chez Workplace est faible (pièces jointes/uploads d'un foyer, pas une plateforme SaaS), et chaque appelant (vision, peertube…) fait déjà un appel HTTP synchrone bloquant pour SON propre traitement (OCR, upload PeerTube) — ajouter un aller-retour async + Redis en plus n'apporte rien ici et ajoute un service (Redis) + une dépendance (dramatiq) à opérer/monitorer. **Décision : `POST /scanner` synchrone uniquement**, timeout HTTP raisonnable côté appelant (30s), taille plafonnée (`AUDIT_FICHIERS_MAX_OCTETS`, défaut 100 Mio — repris tel quel du défaut amont `MAX_UPLOAD_SIZE`, déjà un choix réfléchi côté file-scanner). Si un vrai besoin de fichiers > 100 Mio apparaît (ex. vidéos PeerTube longues), c'est un futur sprint avec de vraies données de volumétrie, pas une anticipation YAGNI.

### R3 — Empreinte mémoire/CPU de ClamAV (RISQUE RÉEL, non résolu par ce plan)
`clamd` charge en RAM l'intégralité de sa base de signatures pour scanner — la doc amont ClamAV documente couramment **1 à 2 Gio de RAM** pour le process `clamd` selon la version des bases (`daily.cvd`/`main.cvd`/`bytecode.cvd`), et un **premier démarrage** qui télécharge ~200-400 Mo de signatures via `freshclam` avant que `clamdscan --ping` ne réponde (d'où le `start_period: 120s` dans le `docker-compose.yml` amont — repris à 180s ici par prudence). Sur une machine de dev qui fait déjà tourner ~30 conteneurs Workplace en parallèle (cf. mémoire `hp-stack-deploye-ssh`), ou sur un Raspberry Pi/mesh, c'est un coût non négligeable. **Ce plan ne le résout pas** — il documente le coût et laisse `clamav_data` en volume persistant pour n'encaisser le téléchargement des signatures qu'une fois. Si la RAM devient un problème réel sur le HP (Debian, `debian@192.168.1.89`) ou sur le Mac de dev, **piste de secours notée mais non implémentée dans ce sprint** : scanner-only-on-demand avec `docker compose --profile` (démarré à la demande, cf. mémoire `sprint-sablier-demarrage-a-la-demande`, actuellement bloquée sur l'accès au socket Docker) plutôt qu'un service `restart: unless-stopped` permanent.

### R4 — image `clamav/clamav:1.4` publiée UNIQUEMENT en `amd64` (RISQUE CONDITIONNEL)
Vérifié sur cette machine : `uname -m` → `x86_64` (ce Mac de dev est Intel, pas Apple Silicon) — l'image tourne donc **nativement** ici. **Mais** si ce plan est exécuté depuis un Mac Apple Silicon (M1/M2/M3/M4, `arm64`), l'image `clamav/clamav:1.4` (comme le confirme le commentaire du `docker-compose.yml` amont : *"clamav publishes amd64 only"*) tournera **sous émulation QEMU** — plus lente, RAM majorée, et nécessite `docker run --privileged --rm tonistiigi/binfmt --install amd64` au préalable (motif exact de l'amont). Le HP (Debian x86_64) n'a pas ce problème. **Décision : documenter la contrainte `platform: linux/amd64` dans le `docker-compose.yml` (comme l'amont), ne pas la lever ici** — pas d'image ClamAV `arm64` officielle maintenue à ce jour à réévaluer si un jour le Mac de dev change d'architecture.

### R5 — Les deux cibles citées dans le brief (mail, atelier-images-video) n'ont PAS de code d'upload aujourd'hui (DÉCOUVERTE, re-scope)
Lecture du code réel (pas juste la doc) :
- **`briques/mail/fournisseurs.py:149`** ignore EXPLICITEMENT les pièces jointes lors du parsing IMAP (`if "attachment" in str(part.get("Content-Disposition") or ""): continue` — commentaire du code : *"Les pièces jointes sont ignorées."*). Il n'existe **aucun** endpoint de téléchargement de pièce jointe, aucun stockage de ses octets. Brancher un scan « avant acceptation d'une pièce jointe » supposerait d'abord un sprint **antérieur** (hors périmètre ici) qui télécharge et stocke les pièces jointes — sans ça, il n'y a rien à scanner.
- **`briques/atelier-images-video/main.py`** ne reçoit AUCUN fichier de l'utilisateur : c'est un pur relais vers `images`/`video` (génération IA à partir d'un `prompt` texte) et `studio`/`memoire` (JSON). Le champ `image_url` (`front.html:101`) référence un fichier **déjà généré** par la brique `images` (chemin de sortie), pas un upload. Il n'y a, là non plus, rien à scanner.

**Décision : re-scoper le câblage sur les DEUX vrais points d'upload actifs aujourd'hui dans Workplace** (identifiés par `grep UploadFile briques/*/main.py`) : `briques/vision/main.py` (`POST /extraire`, ligne 103) et `briques/peertube/main.py` (`POST /videos/upload`, ligne 95) — Task 4 les câble avec du code littéral et des tests. Les autres points d'upload existants (`transcription` `/transcrire` + `/notes`, `voix` `/voix/clones`, `synopsis` `/resumer-fichier`, `etl` `/ingerer`) suivent EXACTEMENT le même motif — listés en fin de Task 4 comme extension immédiate de suivi (même fonction `_verifier_antivirus`, même 3 lignes à coller), volontairement laissés **hors de ce sprint** pour ne pas gonfler sa taille, mais ce ne sont pas des inconnues : le motif est prouvé sur 2 briques, copier-coller sur les 4 autres.
`mail` et `atelier-images-video` restent dans ce document comme **travail futur documenté** (fin de Task 4), pas implémentés : inventer un faux point de branchement serait mentir sur ce qui a été fait.

### R6 — Panne ClamAV : fail-closed (refuser) ou fail-open (laisser passer) ? (DÉCIDÉ : fail-closed)
Philosophie amont reprise telle quelle : une erreur clamd (`ERROR`, ou démon injoignable) signifie que le fichier n'a **pas** été scanné en entier → **jamais** annoncé propre. Traduit ici en **503** côté `audit-fichiers` (`MoteurIndisponible`) puis en **503** côté l'appelant (vision/peertube), qui refuse le fichier. C'est cohérent avec la convention Workplace « jamais un mensonge » (cf. mémoire `mail` : *« Le cache n'est mis à jour QU'APRÈS le succès serveur »*). Contrepartie assumée : si le conteneur `clamav` tombe, plus aucun upload n'est accepté ailleurs tant qu'il n'est pas remonté — acceptable pour un usage familial (mieux vaut un upload bloqué qu'un malware accepté), documenté explicitement plutôt que laissé implicite.

### R7 — Catégories (malware/nsfw) et moteur `exav`/`jcop` (DÉCIDÉ : hors périmètre v1)
L'amont supporte plusieurs axes (`malware` via ClamAV/exav, `nsfw` via jcop) et une sélection `?categories=`/`?scanners=`. Aucun besoin identifié aujourd'hui chez Workplace pour un axe autre que **malware** (les briques concernées traitent des documents/PDF/vidéos d'un foyer, pas de la modération de contenu à grande échelle). **Décision : un seul moteur (ClamAV), pas de paramètre de sélection** — le jour où un besoin `nsfw` apparaît (ex. modération sur `peertube`), c'est un futur sprint avec son propre moteur (jcop nécessite une clé cyber.gouv.fr), pas une anticipation.

---

## Global Constraints

- Port **6170** — vérifié libre en relisant tous les `briques/*/manifest.json` au moment de l'écriture de ce plan (le port le plus élevé actuellement utilisé est 6160, `atelier-images-video`).
- Nom de brique **`audit-fichiers`** — vérifié sans collision (`briques/audit/` existe déjà mais couvre l'audit d'ENTREPRISE — DDD/VSM/Ishikawa/OKRs — un domaine sans rapport ; `grep -rn "\"nom\"" briques/*/manifest.json` ne montre aucun `scan`/`virus`/`antivir`/`malware`/`audit-fichiers` existant).
- Licence amont MIT (`Copyright (c) 2026 ANCT ... 2017 Department for International Trade`) — réutilisation/adaptation libre, à créditer dans les docstrings (fait ci-dessous), pas besoin de fichier LICENSE séparé pour un vendoring partiel/réécrit (pas de copie verbatim de fichiers amont, seulement de la logique de protocole clamd réécrite en français).
- Pas d'import de `shared/` → build-context **local** (`build: .`), comme `export`/`video` (cf. `GUIDE-ajouter-une-brique.md` §3).
- Manifest : `couche: "backend"` ⇒ `port`+`url_sante` obligatoires (`url_sante` doit contenir `6170`), `statut: "a_tester"`, `capacites[].nom` obligatoire — validé par `tests/test_briques_smoke.py`.
- Toute capacité qui **écrit** doit porter `action: true` (`GUIDE-ajouter-une-brique.md` §2). `audit_fichiers_etat` est une LECTURE pure (santé du moteur) ⇒ `action: false`, niveau 0 — même statut que `vision_lire`/`video_fournisseurs`. Le scan lui-même (`/scanner`) n'est PAS déclaré comme capacité LLM : c'est un flux binaire (multipart), et le contrat déclaratif du Cœur ne sait que le JSON (`GUIDE-ajouter-un-outil.md` : *"Un flux binaire (audio, multipart, image) reste appelé en direct par son client"*) — motif identique à `vision_extraire`/`peertube_upload_video`, qui ne sont PAS non plus des capacités LLM.
- Auth : `API_KEYS` (CSV) + `CORS_ORIGINS` (CSV) lus depuis le `.env` racine partagé via `env_file`, motif `video`/`export`. Clé dédiée de service `AUDIT_FICHIERS_KEY` (motif `STUDIO_KEY`/`MAIL_KEY`) que les briques appelantes (vision, peertube…) présentent en `X-API-Key`.
- Commit policy : commit par tâche (motif actuel du dépôt, confirmé par `git log` — S194/S193/atelier-veille montrent tous un commit par tâche, jamais un squash de sprint).

---

### Task 1 : Scaffold — manifest, ClamAV sidecar, Dockerfile, `/sante`

**Files:**
- Create: `briques/audit-fichiers/manifest.json`
- Create: `briques/audit-fichiers/requirements.txt`
- Create: `briques/audit-fichiers/Dockerfile`
- Create: `briques/audit-fichiers/docker-compose.yml`
- Create: `briques/audit-fichiers/conftest.py`
- Create: `briques/audit-fichiers/main.py` (scaffold — `/sante` seulement, `/scanner` en Task 3)
- Test: `briques/audit-fichiers/test_api.py` (santé seulement — étendu en Task 3)

**Interfaces:**
- Produces: `app` FastAPI dans `main.py`, `cle_api()` (même signature que `export`/`vision`), `API_KEYS: set[str]`, `MAX_OCTETS: int`, `GET /sante`. Consommés tels quels par Task 3.

- [ ] **Step 1: Create `briques/audit-fichiers/requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.9
clamd==1.0.2
```

- [ ] **Step 2: Create `briques/audit-fichiers/manifest.json`** (`capacites` ajoutées en Task 5 — vide pour l'instant)

```json
{
  "nom": "audit-fichiers",
  "famille": "securite",
  "version": "0.1.0",
  "description": "Scan antivirus (ClamAV, protocole clamd) d'un fichier AVANT qu'une autre brique ne l'accepte — malware par signatures connues. Service générique appelé en serveur-à-serveur (vision /extraire, peertube /videos/upload...). Adapté (MIT) de suitenumerique/file-scanner (ANCT/DINUM), simplifié pour un contexte mono-tenant/famille : pas de JWT Ed25519 multi-émetteur (auth API_KEYS standard Workplace), pas de file d'attente dramatiq/Redis (scan synchrone uniquement) — S195.",
  "role": "audit-fichiers",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/audit-fichiers",
  "port": 6170,
  "url_sante": "http://host.docker.internal:6170/sante",
  "depends_on": [],
  "offre": ["scan_malware_clamav"],
  "besoin": [],
  "capacites": [],
  "taches": []
}
```

- [ ] **Step 3: Create `briques/audit-fichiers/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Aucune lib native ClamAV ici : ce service parle le protocole clamd (INSTREAM) au
# conteneur sidecar `audit-fichiers-clamav` du docker-compose.yml — clamd lui-même
# n'est jamais installé dans CETTE image (cf. scanners/clamav.py amont, même séparation).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6170"]
```

- [ ] **Step 4: Create `briques/audit-fichiers/docker-compose.yml`**

```yaml
services:
  # Moteur ClamAV — sidecar officiel, même image que l'amont suitenumerique/file-scanner.
  # RISQUE R3/R4 du plan (docs/superpowers/plans/2026-07-25-s195-...) : 1ère synchro
  # freshclam ~200-400 Mo (start_period généreux) ; image amd64 uniquement (émulation
  # QEMU nécessaire sur Mac Apple Silicon, cf. R4).
  audit-fichiers-clamav:
    image: clamav/clamav:1.4
    container_name: workplace_audit_fichiers_clamav
    platform: linux/amd64
    volumes:
      - audit_fichiers_clamav_data:/var/lib/clamav   # base de signatures persistée
    healthcheck:
      test: ["CMD", "clamdscan", "--ping", "1"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 180s
    restart: unless-stopped

  audit-fichiers:
    build: .
    container_name: workplace_audit_fichiers
    image: workplace/audit-fichiers:0.1.0          # tag épinglé (pas de :latest flottant)
    env_file:
      # Réglages partagés à la racine (API_KEYS, CORS_ORIGINS, AUDIT_FICHIERS_KEY). Facultatif.
      - path: ../../.env
        required: false
    ports:
      - "6170:6170"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # joindre les services hôtes sous Linux
    environment:
      - CLAMAV_HOSTS=audit-fichiers-clamav:3310
      # Plafond de taille scannée — repris du défaut amont MAX_UPLOAD_SIZE (100 Mio, déjà
      # un choix réfléchi côté file-scanner). Voir Risque R2 du plan.
      - AUDIT_FICHIERS_MAX_OCTETS=${AUDIT_FICHIERS_MAX_OCTETS:-104857600}
    depends_on:
      audit-fichiers-clamav:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6170/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

volumes:
  audit_fichiers_clamav_data:
```

- [ ] **Step 5: Create `briques/audit-fichiers/conftest.py`**

```python
"""Config de test : mode API ouvert (déterministe), aucune dépendance réseau réelle
à ClamAV (le protocole clamd est mocké dans test_moteur_clamav.py/test_api.py)."""
import os

os.environ["API_KEYS"] = ""
os.environ["CLAMAV_HOSTS"] = "localhost:9999"   # jamais réellement contacté en test
```

- [ ] **Step 6: Create `briques/audit-fichiers/main.py`** (scaffold : santé + CORS/auth seulement)

```python
"""Brique « audit-fichiers » — scan antivirus (ClamAV/clamd) avant acceptation d'un fichier.

Service autonome, appelé SERVEUR-À-SERVEUR par une autre brique juste avant qu'elle
n'accepte un fichier envoyé par un utilisateur (vision /extraire, peertube
/videos/upload...). Adapté (licence MIT) du projet suitenumerique/file-scanner
(ANCT/DINUM), simplifié pour Workplace : un seul moteur (ClamAV, pas de sélection
catégories/nsfw/exav/jcop), scan SYNCHRONE uniquement (pas de file d'attente
dramatiq/Redis), auth API_KEYS standard Workplace (pas de JWT Ed25519 multi-émetteur)
— voir docs/superpowers/plans/2026-07-25-s195-brique-audit-fichiers-antivirus.md
pour la justification de chaque simplification.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Audit fichiers — scan antivirus (ClamAV)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
MAX_OCTETS = int(os.getenv("AUDIT_FICHIERS_MAX_OCTETS", str(100 * 1024 * 1024)))


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True, "brique": "audit-fichiers", "clamav_joignable": False}
```

- [ ] **Step 7: Write the failing test — `briques/audit-fichiers/test_api.py`**

```python
"""Tests — API de la brique audit-fichiers."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["brique"] == "audit-fichiers"
```

- [ ] **Step 8: Run the tests**

```bash
cd briques/audit-fichiers && python3 -m pip install -r requirements.txt -q && python3 -m pytest -q
```
Expected: 1 passed.

- [ ] **Step 9: Validate the manifest against the smoke test**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke
```
Expected: all pass, including the new `briques/audit-fichiers` entries (`test_manifest_est_un_json_valide`, `test_manifest_porte_les_champs_requis`, `test_brique_backend_porte_le_contrat_reseau`, `test_statut_est_connu`, `test_url_sante_contient_le_port`, `test_noms_de_briques_uniques`, `test_aucune_collision_de_port`).

- [ ] **Step 10: Commit**

```bash
git add briques/audit-fichiers
git commit -m "feat(audit-fichiers): scaffold — manifest, ClamAV sidecar, Dockerfile, /sante (S195)"
```

---

### Task 2 : `moteur_clamav.py` — protocole clamd simplifié (un seul moteur)

**Files:**
- Create: `briques/audit-fichiers/moteur_clamav.py`
- Test: `briques/audit-fichiers/test_moteur_clamav.py`

**Interfaces:**
- Produces: `class Verdict` (`propre: bool`, `raison: str | None`), `class MoteurIndisponible(Exception)`, `def ping() -> bool`, `def scanner(fileobj) -> Verdict` (lève `MoteurIndisponible`). Consommés par `main.py` en Task 3.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests — moteur_clamav.py.

Le protocole clamd (INSTREAM) amont (scanners/clamav.py de suitenumerique/file-scanner,
MIT) est mocké ici au niveau du client — comme rendu_pdf.py mocke WeasyPrint (cf. plan
S194) : ces tests tournent OFFLINE, sans démon ClamAV réel."""
import io

import pytest

import moteur_clamav as M


class _FauxClientPropre:
    def instream(self, fileobj):
        return {"stream": ("OK", None)}

    def ping(self):
        return "PONG"


class _FauxClientMalware:
    def instream(self, fileobj):
        return {"stream": ("FOUND", "Eicar-Test-Signature")}


class _FauxClientErreur:
    def instream(self, fileobj):
        return {"stream": ("ERROR", "Memory allocation failed")}


class _FauxClientInjoignable:
    def instream(self, fileobj):
        raise ConnectionRefusedError("connexion refusée")

    def ping(self):
        raise ConnectionRefusedError("connexion refusée")


def test_scanner_fichier_propre(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientPropre())
    verdict = M.scanner(io.BytesIO(b"contenu inoffensif"))
    assert verdict.propre is True
    assert verdict.raison is None


def test_scanner_detecte_malware(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientMalware())
    verdict = M.scanner(io.BytesIO(b"faux malware"))
    assert verdict.propre is False
    assert verdict.raison == "Eicar-Test-Signature"


def test_scanner_erreur_clamd_leve_indisponible(monkeypatch):
    # Un ERROR clamd = fichier NON scanné en entier -> jamais "propre" (fail-closed, R6)
    monkeypatch.setattr(M, "_client", lambda: _FauxClientErreur())
    with pytest.raises(M.MoteurIndisponible):
        M.scanner(io.BytesIO(b"x"))


def test_scanner_connexion_refusee_leve_indisponible(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientInjoignable())
    with pytest.raises(M.MoteurIndisponible):
        M.scanner(io.BytesIO(b"x"))


def test_ping_ok(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientPropre())
    assert M.ping() is True


def test_ping_ko_si_injoignable(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientInjoignable())
    assert M.ping() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/audit-fichiers && python3 -m pytest test_moteur_clamav.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'moteur_clamav'`.

- [ ] **Step 3: Implement `briques/audit-fichiers/moteur_clamav.py`**

```python
"""Moteur antivirus — parle le protocole clamd (INSTREAM) à un démon ClamAV externe.

Logique adaptée de scanners/clamav.py (suitenumerique/file-scanner, MIT, ANCT/DINUM) :
même protocole, même philosophie de verdict (« jamais propre si le fichier n'a pas été
scanné en entier » — un ERROR clamd n'est PAS un verdict propre). Simplifié pour
Workplace : un seul moteur (ClamAV), pas de pool multi-hôtes ni de sélection
catégories/exav/jcop (YAGNI mono-tenant, cf. plan S195 Risque R7)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import clamd

CLAMAV_HOSTS = os.getenv("CLAMAV_HOSTS", "localhost:3310")
CLAMAV_TIMEOUT = int(os.getenv("CLAMAV_TIMEOUT", "60"))

# Fragments d'erreur clamd/OS génuinement transitoires (retry utile côté appelant) —
# repris tel quel de _TRANSIENT_HINTS amont, mais ici on ne retente jamais nous-mêmes
# (scan synchrone, pas de file d'attente, cf. Risque R2) : on remonte MoteurIndisponible
# dans tous les cas, l'appelant décide s'il redemande.


class MoteurIndisponible(Exception):
    """Le démon ClamAV est injoignable, ou n'a pas pu scanner le fichier en entier."""


@dataclass
class Verdict:
    propre: bool
    raison: str | None = None


def _client():
    """Un client clamd frais (pas de pool multi-hôtes — un seul hôte configuré,
    contrairement à l'amont qui équilibre entre plusieurs)."""
    host, _, port = CLAMAV_HOSTS.split(",")[0].strip().partition(":")
    return clamd.ClamdNetworkSocket(host=host, port=int(port or 3310), timeout=CLAMAV_TIMEOUT)


def ping() -> bool:
    try:
        return _client().ping() == "PONG"
    except Exception:
        return False


def scanner(fileobj) -> Verdict:
    """Scanne un flux binaire. Lève MoteurIndisponible si le démon est injoignable ou
    si le scan n'a pas pu être mené à terme — jamais un verdict "propre" dans ce cas
    (fail-closed, cf. plan S195 Risque R6)."""
    try:
        resultat = _client().instream(fileobj)
    except (clamd.ConnectionError, ConnectionRefusedError, OSError) as exc:
        raise MoteurIndisponible(f"ClamAV injoignable : {exc}") from exc
    statut, raison = resultat["stream"]
    if statut == "OK":
        return Verdict(propre=True)
    if statut == "ERROR":
        raise MoteurIndisponible(f"scan non mené à terme : {raison}")
    return Verdict(propre=False, raison=raison)   # FOUND (détection)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/audit-fichiers && python3 -m pytest test_moteur_clamav.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add briques/audit-fichiers/moteur_clamav.py briques/audit-fichiers/test_moteur_clamav.py
git commit -m "feat(audit-fichiers): moteur_clamav.py — protocole clamd simplifié, fail-closed (S195)"
```

---

### Task 3 : Wire `main.py` — `POST /scanner`

**Files:**
- Modify: `briques/audit-fichiers/main.py`
- Modify: `briques/audit-fichiers/test_api.py`

**Interfaces:**
- Consumes: `moteur_clamav.ping() -> bool`, `moteur_clamav.scanner(fileobj) -> Verdict`, `moteur_clamav.MoteurIndisponible` (Task 2) ; `cle_api`, `API_KEYS`, `MAX_OCTETS` (Task 1).
- Produces: `POST /scanner` — réponse `{"ok": true, "propre": bool, "raison": str|None, "scanner": "clamav"}`. Consommé par Task 4.

- [ ] **Step 1: Write the failing tests — append to `briques/audit-fichiers/test_api.py`**

```python
import moteur_clamav as moteur


def test_sante_annonce_clamav_joignable(monkeypatch):
    monkeypatch.setattr(moteur, "ping", lambda: True)
    r = c.get("/sante")
    assert r.json()["clamav_joignable"] is True


def test_sante_annonce_clamav_injoignable(monkeypatch):
    monkeypatch.setattr(moteur, "ping", lambda: False)
    r = c.get("/sante")
    assert r.json()["clamav_joignable"] is False


def test_scanner_refuse_fichier_vide():
    r = c.post("/scanner", files={"fichier": ("vide.txt", b"", "text/plain")})
    assert r.status_code == 422


def test_scanner_refuse_fichier_trop_gros(monkeypatch):
    monkeypatch.setattr(main, "MAX_OCTETS", 10)
    r = c.post("/scanner", files={"fichier": ("gros.bin", b"x" * 100, "application/octet-stream")})
    assert r.status_code == 413


def test_scanner_fichier_propre(monkeypatch):
    monkeypatch.setattr(moteur, "scanner", lambda fileobj: moteur.Verdict(propre=True))
    r = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu inoffensif", "application/pdf")})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "propre": True, "raison": None, "scanner": "clamav"}


def test_scanner_detecte_malware(monkeypatch):
    monkeypatch.setattr(moteur, "scanner",
                         lambda fileobj: moteur.Verdict(propre=False, raison="Eicar-Test-Signature"))
    r = c.post("/scanner", files={"fichier": ("virus.exe", b"faux virus", "application/octet-stream")})
    assert r.status_code == 200
    d = r.json()
    assert d["propre"] is False
    assert d["raison"] == "Eicar-Test-Signature"


def test_scanner_clamav_indisponible_refuse_par_precaution(monkeypatch):
    def _leve(fileobj):
        raise moteur.MoteurIndisponible("ClamAV injoignable : connexion refusée")
    monkeypatch.setattr(moteur, "scanner", _leve)
    r = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")})
    assert r.status_code == 503


def test_scanner_exige_cle_api_si_definie(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"secret123"})
    monkeypatch.setattr(moteur, "scanner", lambda fileobj: moteur.Verdict(propre=True))
    r = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")})
    assert r.status_code == 401
    r2 = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")},
                headers={"X-API-Key": "secret123"})
    assert r2.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/audit-fichiers && python3 -m pytest test_api.py -v
```
Expected: FAIL — `404` sur `POST /scanner` (route absente), `clamav_joignable` toujours `False` (pas encore branché sur `moteur.ping()`).

- [ ] **Step 3: Modify `briques/audit-fichiers/main.py`** — remplace le corps de `sante()` et ajoute `/scanner`. Fichier complet résultant :

```python
"""Brique « audit-fichiers » — scan antivirus (ClamAV/clamd) avant acceptation d'un fichier.

Service autonome, appelé SERVEUR-À-SERVEUR par une autre brique juste avant qu'elle
n'accepte un fichier envoyé par un utilisateur (vision /extraire, peertube
/videos/upload...). Adapté (licence MIT) du projet suitenumerique/file-scanner
(ANCT/DINUM), simplifié pour Workplace : un seul moteur (ClamAV, pas de sélection
catégories/nsfw/exav/jcop), scan SYNCHRONE uniquement (pas de file d'attente
dramatiq/Redis), auth API_KEYS standard Workplace (pas de JWT Ed25519 multi-émetteur).
FAIL-CLOSED : si ClamAV est injoignable, le fichier est REFUSÉ (jamais annoncé "propre"
sans avoir été scanné en entier) — voir
docs/superpowers/plans/2026-07-25-s195-brique-audit-fichiers-antivirus.md.
"""
from __future__ import annotations

import io
import os
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import moteur_clamav as moteur

app = FastAPI(title="Audit fichiers — scan antivirus (ClamAV)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
MAX_OCTETS = int(os.getenv("AUDIT_FICHIERS_MAX_OCTETS", str(100 * 1024 * 1024)))


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True, "brique": "audit-fichiers", "clamav_joignable": moteur.ping()}


@app.post("/scanner", tags=["scan"])
async def scanner(fichier: UploadFile = File(...), _cle: str = Depends(cle_api)):
    """Scanne un fichier (multipart). Fail-closed : ClamAV injoignable ⇒ 503, le
    fichier est REFUSÉ par précaution (jamais annoncé propre sans scan complet)."""
    data = await fichier.read()
    if not data:
        raise HTTPException(422, "Le fichier est vide.")
    if len(data) > MAX_OCTETS:
        raise HTTPException(413, f"Fichier trop volumineux (> {MAX_OCTETS} octets).")
    try:
        verdict = moteur.scanner(io.BytesIO(data))
    except moteur.MoteurIndisponible as e:
        raise HTTPException(503, f"Moteur antivirus indisponible : fichier refusé "
                                 f"par précaution ({e}).") from e
    return {"ok": True, "propre": verdict.propre, "raison": verdict.raison, "scanner": "clamav"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/audit-fichiers && python3 -m pytest -v
```
Expected: all tests pass (1 + 6 + 8 = 15 total across `test_api.py`/`test_moteur_clamav.py`).

- [ ] **Step 5: Commit**

```bash
git add briques/audit-fichiers/main.py briques/audit-fichiers/test_api.py
git commit -m "feat(audit-fichiers): endpoint POST /scanner, fail-closed si ClamAV injoignable (S195)"
```

---

### Task 4 : Câblage inter-briques — `vision` (`/extraire`) et `peertube` (`/videos/upload`)

**Files:**
- Modify: `briques/vision/main.py:1-40` (imports + config), `briques/vision/main.py:103-113` (`/extraire`)
- Modify: `briques/vision/conftest.py`
- Modify: `briques/vision/test_api.py`
- Modify: `briques/peertube/main.py` (imports + config + `/videos/upload`)
- Modify: `briques/peertube/conftest.py`
- Modify: `briques/peertube/test_peertube.py`

**Interfaces:**
- Consumes: `POST {AUDIT_FICHIERS_URL}/scanner` (Task 3) — contrat HTTP externe, pas d'import Python.
- Produces: `_verifier_antivirus(data: bytes, nom_fichier: str) -> None` (répliquée à l'identique dans `vision/main.py` ET `peertube/main.py` — même motif que la duplication existante des helpers `cle_api`/CORS entre briques, pas de `shared/` importé pour une fonction de 12 lignes, cf. `GUIDE-ajouter-une-brique.md` §3 : *"N'adopte le contexte racine que sur besoin réel"*).

**Pourquoi ces deux briques et pas mail/atelier-images-video : voir Risque R5 en tête de ce document.**

- [ ] **Step 1 : Ajouter la config + le helper dans `briques/vision/main.py`** — juste après la ligne existante `MAX_OCTETS = int(os.getenv("VISION_MAX_OCTETS", str(25 * 1024 * 1024)))` (ligne 33), insérer :

```python
AUDIT_FICHIERS_URL = os.getenv("AUDIT_FICHIERS_URL", "http://host.docker.internal:6170")
AUDIT_FICHIERS_KEY = os.getenv("AUDIT_FICHIERS_KEY", "")


async def _verifier_antivirus(data: bytes, nom_fichier: str) -> None:
    """Refuse la requête (400) si le fichier est détecté malveillant, ou (503) si
    l'antivirus est injoignable — FAIL-CLOSED : jamais accepté sans scan complet (cf.
    plan S195 Risque R6). No-op SEULEMENT si AUDIT_FICHIERS_URL est explicitement
    vide (tests offline, cf. conftest.py) — en usage réel, une panne réseau ferme
    l'accès plutôt que de l'ouvrir silencieusement."""
    if not AUDIT_FICHIERS_URL:
        return
    entetes = {"X-API-Key": AUDIT_FICHIERS_KEY} if AUDIT_FICHIERS_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{AUDIT_FICHIERS_URL}/scanner", headers=entetes,
                                  files={"fichier": (nom_fichier or "fichier", data)})
    except Exception as e:  # noqa: BLE001 — antivirus injoignable = refus par précaution
        raise HTTPException(503, f"Antivirus injoignable, fichier refusé par "
                                 f"précaution : {str(e)[:150]}") from e
    if r.status_code != 200:
        detail = r.json().get("detail", "Scan antivirus refusé.") if r.headers.get(
            "content-type", "").startswith("application/json") else "Scan antivirus refusé."
        raise HTTPException(r.status_code, detail)
    verdict = r.json()
    if not verdict.get("propre", False):
        raise HTTPException(400, f"Fichier refusé : détecté malveillant "
                                 f"({verdict.get('raison') or 'signature inconnue'}).")
```

- [ ] **Step 2 : Appeler le scan dans `/extraire` — `briques/vision/main.py:103-113`**, insérer l'appel juste après la vérification de taille (avant `mime = _mime_devine(...)`) :

```python
@app.post("/extraire", tags=["vision"])
async def extraire(fichier: UploadFile = File(...), fournisseur: Optional[str] = None,
                   _cle: str = Depends(cle_api)):
    """Un fichier en multipart (PDF/image/Office…) → texte extrait par la cascade OCR."""
    data = await fichier.read()
    if not data:
        raise HTTPException(422, "Le fichier est vide.")
    if len(data) > MAX_OCTETS:
        raise HTTPException(413, f"Fichier trop volumineux (> {MAX_OCTETS} octets).")
    await _verifier_antivirus(data, fichier.filename or "")
    mime = _mime_devine(fichier.filename or "", fichier.content_type or "")
    return await moteur.extraire(data, fichier.filename or "", mime, fournisseur=fournisseur)
```

- [ ] **Step 3 : Neutraliser l'appel réseau dans les tests offline — `briques/vision/conftest.py`**, ajouter une ligne :

```python
os.environ["AUDIT_FICHIERS_URL"] = ""   # no-op en test : pas de dépendance réseau (S195)
```

- [ ] **Step 4 : Écrire les nouveaux tests — ajouter à `briques/vision/test_api.py`**

```python
import httpx
import respx


@respx.mock
def test_extraire_refuse_un_fichier_detecte_malveillant(monkeypatch):
    monkeypatch.setattr(main, "AUDIT_FICHIERS_URL", "http://audit-test:6170")
    respx.post("http://audit-test:6170/scanner").mock(
        return_value=httpx.Response(200, json={"ok": True, "propre": False,
                                                "raison": "Eicar-Test-Signature",
                                                "scanner": "clamav"}))
    r = c.post("/extraire", files={"fichier": ("virus.pdf", b"faux virus", "application/pdf")})
    assert r.status_code == 400
    assert "Eicar-Test-Signature" in r.json()["detail"]


@respx.mock
def test_extraire_refuse_par_precaution_si_antivirus_injoignable(monkeypatch):
    monkeypatch.setattr(main, "AUDIT_FICHIERS_URL", "http://audit-test:6170")
    respx.post("http://audit-test:6170/scanner").mock(side_effect=httpx.ConnectError("refus"))
    r = c.post("/extraire", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")})
    assert r.status_code == 503


@respx.mock
def test_extraire_accepte_un_fichier_propre(monkeypatch):
    monkeypatch.setattr(main, "AUDIT_FICHIERS_URL", "http://audit-test:6170")
    respx.post("http://audit-test:6170/scanner").mock(
        return_value=httpx.Response(200, json={"ok": True, "propre": True,
                                                "raison": None, "scanner": "clamav"}))
    r = c.post("/extraire", files={"fichier": ("scan.png", b"\x89PNG\r\n", "image/png")})
    assert r.status_code == 200   # repli honnête habituel (aucun moteur OCR en test)
```

Note : `respx` doit être disponible pour les tests `vision` — vérifier `briques/vision/requirements.txt` ; si absent, l'ajouter en dépendance de test (`respx==0.21.1`, déjà utilisée par `briques/peertube/test_peertube.py`, donc une version déjà éprouvée dans ce monorepo).

- [ ] **Step 5 : Run tests**

```bash
cd briques/vision && python3 -m pytest test_api.py -v
```
Expected: tests existants + 3 nouveaux tous verts (le mock `AUDIT_FICHIERS_URL=""` par défaut du `conftest.py` protège les tests préexistants qui ne mockent pas l'antivirus).

- [ ] **Step 6 : Commit**

```bash
git add briques/vision/main.py briques/vision/conftest.py briques/vision/test_api.py
git commit -m "feat(vision): scan antivirus avant /extraire, fail-closed (S195)"
```

- [ ] **Step 7 : Même câblage sur `briques/peertube/main.py`** — coller le même helper `_verifier_antivirus` (imports `httpx`/`HTTPException` déjà présents dans ce fichier) juste après le bloc de config existant, puis l'appeler dans `/videos/upload` :

```python
@app.post("/videos/upload")
async def upload_video(
    nom: str = Form(...),
    description: str = Form(""),
    fichier: UploadFile = File(...),
    _: str = Depends(_cle_api),
):
    contenu = await fichier.read()
    await _verifier_antivirus(contenu, fichier.filename or "video.mp4")
    try:
        result = await _peertube.uploader_video(nom, description, contenu, fichier.filename or "video.mp4")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Échec upload PeerTube")
    return {
        "uuid": result["uuid"],
        "watchUrl": result.get("url") or f"{PEERTUBE_URL}/videos/watch/{result['uuid']}",
    }
```

- [ ] **Step 8 : Neutraliser l'appel réseau dans les tests offline — `briques/peertube/conftest.py`**, fichier complet :

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["AUDIT_FICHIERS_URL"] = ""   # no-op en test : pas de dépendance réseau (S195)
```

- [ ] **Step 9 : Écrire les nouveaux tests — ajouter à `briques/peertube/test_peertube.py`**

```python
def test_upload_video_refuse_un_fichier_malveillant():
    from main import app
    import main as m
    with patch("main._peertube") as mock_pt, \
         patch.object(m, "AUDIT_FICHIERS_URL", "http://audit-test:6170"), \
         respx.mock:
        respx.post("http://audit-test:6170/scanner").mock(
            return_value=httpx.Response(200, json={"ok": True, "propre": False,
                                                    "raison": "Eicar-Test-Signature",
                                                    "scanner": "clamav"}))
        client = TestClient(app)
        resp = client.post("/videos/upload", data={"nom": "Vidéo", "description": ""},
                           files={"fichier": ("v.mp4", io.BytesIO(b"faux virus"), "video/mp4")})
        assert resp.status_code == 400
        mock_pt.uploader_video.assert_not_called()


def test_upload_video_refuse_par_precaution_si_antivirus_injoignable():
    from main import app
    import main as m
    with patch("main._peertube") as mock_pt, \
         patch.object(m, "AUDIT_FICHIERS_URL", "http://audit-test:6170"), \
         respx.mock:
        respx.post("http://audit-test:6170/scanner").mock(side_effect=httpx.ConnectError("refus"))
        client = TestClient(app)
        resp = client.post("/videos/upload", data={"nom": "Vidéo", "description": ""},
                           files={"fichier": ("v.mp4", io.BytesIO(b"contenu"), "video/mp4")})
        assert resp.status_code == 503
        mock_pt.uploader_video.assert_not_called()
```

- [ ] **Step 10 : Run tests**

```bash
cd briques/peertube && python3 -m pytest test_peertube.py -v
```
Expected: tous les tests existants (dont `test_upload_video`, protégé par `AUDIT_FICHIERS_URL=""` du `conftest.py`) + les 2 nouveaux, tous verts.

- [ ] **Step 11 : Commit**

```bash
git add briques/peertube/main.py briques/peertube/conftest.py briques/peertube/test_peertube.py
git commit -m "feat(peertube): scan antivirus avant /videos/upload, fail-closed (S195)"
```

**Travail futur documenté (hors périmètre de ce sprint — voir Risque R5) :**

| Brique | Point d'upload réel | Statut |
|---|---|---|
| `transcription` | `POST /transcrire` (`main.py:187`), `POST /notes` (`main.py:236`) | même motif exact, non câblé ce sprint |
| `voix` | `POST /voix/clones` (`main.py:289`) | même motif exact, non câblé ce sprint |
| `synopsis` | `POST /resumer-fichier` (`main.py:219`) | même motif exact, non câblé ce sprint |
| `etl` | `POST /ingerer` (`main.py:62`) | même motif exact, non câblé ce sprint |
| `mail` | AUCUN — pièces jointes explicitement ignorées (`fournisseurs.py:149`) | prérequis manquant : sprint de téléchargement/stockage des pièces jointes d'abord |
| `atelier-images-video` | AUCUN — pas d'upload utilisateur, seulement génération IA depuis un prompt texte | pas de fichier à scanner ; non pertinent tel que la brique existe |

---

### Task 5 : Enregistrement au Cœur — capacité, launcher, `.env.example`, vérification finale

**Files:**
- Modify: `briques/audit-fichiers/manifest.json` (ajoute `capacites`)
- Modify: `Lancer Workplace.command`
- Modify: `.env.example`

- [ ] **Step 1 : Ajouter la capacité dans `briques/audit-fichiers/manifest.json`** — remplacer `"capacites": [],` par :

```json
  "capacites": [
    {
      "nom": "audit_fichiers_etat",
      "description": "Vérifie si le moteur antivirus (ClamAV) est joignable et opérationnel. À appeler quand l'utilisateur demande si l'antivirus / le scan de fichiers fonctionne. Lecture seule.",
      "methode": "GET",
      "chemin": "/sante",
      "params": {},
      "action": false,
      "niveau": 0
    }
  ],
```

Note : `POST /scanner` n'est **volontairement pas** déclaré ici — c'est un flux binaire multipart, hors du contrat JSON déclaratif (`GUIDE-ajouter-un-outil.md` : *"Un flux binaire ... reste appelé en direct par son client"*), exactement comme `vision_extraire`/`peertube` upload ne sont pas des capacités.

- [ ] **Step 2 : Re-run the smoke test**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke
```
Expected: all pass, including `test_capacites_et_taches_bien_formees` pour `audit-fichiers`.

- [ ] **Step 3 : Ajouter l'entrée launcher dans `Lancer Workplace.command`**

Trouver la ligne `"export|$RACINE/briques/export|http://localhost:6150/sante"` (ligne 78) et ajouter juste après (**avant** le Cœur, pour qu'il la découvre au démarrage — `vision`/`peertube` doivent pouvoir l'appeler dès qu'elles démarrent) :

```
  "audit-fichiers|$RACINE/briques/audit-fichiers|http://localhost:6170/sante"
```

- [ ] **Step 4 : Documenter les secrets dans `.env.example`**

Remplacer le bloc existant :
```
# Clés d'API acceptées par les briques autonomes (calcul, images, personnages,
# studio, transcription, video, vision, connexion, export) — CSV, en-tête X-API-Key.
```
par :
```
# Clés d'API acceptées par les briques autonomes (calcul, images, personnages,
# studio, transcription, video, vision, connexion, export, audit-fichiers) — CSV,
# en-tête X-API-Key.
```

Puis, après le bloc `ATELIER_IMAGES_VIDEO_KEY=` (autour de la ligne 403), ajouter :
```

# Brique « audit-fichiers » (scan antivirus ClamAV, port 6170, S195) — scan un fichier
# AVANT qu'une autre brique (vision, peertube...) ne l'accepte. Clé de service DÉDIÉE
# (motif STUDIO_KEY/MAIL_KEY) que les briques APPELANTES présentent en X-API-Key.
# Vide = mode ouvert (dev mono-tenant). Fail-closed (API_KEYS non vide côté
# audit-fichiers) : lister aussi cette clé dans l'API_KEYS de la brique audit-fichiers.
# Génère une clé : `openssl rand -hex 32`.
AUDIT_FICHIERS_KEY=
# URL vue par vision/peertube (et toute future brique câblée, cf. plan S195 Task 4) pour
# joindre le scanner. Vide = DÉSACTIVE le scan (no-op, mode dégradé explicite — utile en
# test/dev sans le conteneur ClamAV monté). Défaut réel (posé dans le code, pas ici) :
# http://host.docker.internal:6170.
AUDIT_FICHIERS_URL=http://host.docker.internal:6170
```

- [ ] **Step 5 : Run the full offline test suite one more time**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke \
  && cd briques/audit-fichiers && python3 -m pytest -v \
  && cd ../vision && python3 -m pytest -v \
  && cd ../peertube && python3 -m pytest test_peertube.py -v
```
Expected: everything green.

- [ ] **Step 6 : Manual Docker verification (requires Docker running — HP ou Docker Desktop local ; régime de preuve différé du projet)**

```bash
cd briques/audit-fichiers
docker compose up -d --build
# Attendre la fin de la 1ère synchro freshclam (peut prendre plusieurs minutes, cf. Risque R3) :
docker compose logs -f audit-fichiers-clamav | grep -m1 "clamd started"
curl http://localhost:6170/sante
# → {"ok": true, "brique": "audit-fichiers", "clamav_joignable": true}

# Fichier EICAR (signature de test standard, inoffensive, reconnue par TOUS les antivirus) :
curl -s -o /tmp/eicar.txt https://secure.eicar.org/eicar.com.txt || \
  printf 'X5O!P%%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /tmp/eicar.txt
curl -X POST http://localhost:6170/scanner -F "fichier=@/tmp/eicar.txt"
# → {"ok": true, "propre": false, "raison": "Win.Test.EICAR_HDB-1", "scanner": "clamav"}

curl -X POST http://localhost:6170/scanner -F "fichier=@briques/audit-fichiers/requirements.txt"
# → {"ok": true, "propre": true, "raison": null, "scanner": "clamav"}
```
Expected: le fichier EICAR est détecté (`propre: false`), un fichier texte inoffensif passe (`propre: true`) — preuve que le protocole clamd simplifié fonctionne pour de vrai (rien dans la suite offline ne le vérifie, `moteur_clamav._client` y est mocké).

- [ ] **Step 7 : Commit**

```bash
git add briques/audit-fichiers/manifest.json "Lancer Workplace.command" .env.example
git commit -m "$(cat <<'EOF'
feat(audit-fichiers): câble la brique au Cœur — capacité, launcher, secrets (S195)

audit_fichiers_etat exposée au LLM (action:false, niveau 0 — lecture seule).
POST /scanner reste hors capacités déclaratives (flux multipart, cf.
GUIDE-ajouter-un-outil.md). Entrée launcher avant le Cœur. AUDIT_FICHIERS_KEY/
AUDIT_FICHIERS_URL documentés. Issu d'une veille du dépôt MIT
suitenumerique/file-scanner (ANCT/DINUM).
EOF
)"
git status
```

---

## Self-Review Notes

- **Spec coverage** (brief S195) : (1) scaffold manifest/Dockerfile/docker-compose/`/sante` → Task 1 ; (2) intégration du scan (vendoring adapté, pas de copie verbatim) → Task 2-3 ; (3) câblage `mail`/`atelier-images-video` → **re-scopé avec justification factuelle** (Risque R5) sur `vision`/`peertube`, les deux vrais points d'upload existants, avec la liste explicite des 4 autres candidats + des 2 briques sans code d'upload → Task 4 ; (4) tests TDD offline → Task 2/3/4 (mock du protocole clamd + mock httpx, motif `respx` déjà utilisé par `peertube`) ; (5) enregistrement au Cœur (capacités/launcher/`.env.example`) → Task 5.
- **Placeholder scan** : aucun TBD/TODO — chaque étape a du code littéral ou une commande exacte avec sortie attendue. Le tableau de Task 4 documente explicitement les briques NON câblées comme un choix de périmètre assumé, pas un oubli.
- **Type consistency** : `moteur_clamav.scanner(fileobj) -> Verdict` (Task 2) correspond à l'appel dans `main.py::scanner()` (Task 3) ; `Verdict(propre, raison)` est le même type dans les tests Task 2/3 ; `POST /scanner` retourne `{"propre", "raison", "scanner"}` — même clés consommées côté `vision`/`peertube` dans `_verifier_antivirus` (Task 4) ; `AUDIT_FICHIERS_URL`/`AUDIT_FICHIERS_KEY` nommés identiquement dans le code (Task 4) et `.env.example` (Task 5).
- **Risques non résolus, assumés explicitement** : empreinte RAM ClamAV (R3), image amd64-only (R4), fail-closed qui bloque tout upload si ClamAV tombe (R6) — documentés en tête plutôt que découverts en prod.
