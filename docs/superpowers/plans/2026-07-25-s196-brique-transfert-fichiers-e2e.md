# S196 — Brique transfert de fichiers chiffrés bout-en-bout (E2E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new autonomous brique `briques/transferts/` (port 6180) qui permet d'envoyer un gros fichier (jusqu'à ~20 Gio, borne configurable) via un lien à expiration, **chiffré bout-en-bout dans le navigateur** (AES-256-GCM/WebCrypto) — la clé ne transite jamais par le serveur, un Service Worker chez le destinataire déchiffre en streaming direct vers le téléchargement (jamais de blob en RAM, jamais de clair sur le serveur).

**Architecture:** FastAPI + SQLite (mêmes conventions que `briques/mail/` et `briques/export/`), stockage sur volume Docker local (pas de S3/MinIO — voir arbitrage ci-dessous). Le mécanisme crypto de `suitenumerique/transfers` est **réimplémenté à la main** (vendoring léger, pas d'import de code Django) en JS vanilla : `static/chiffrement.js` (primitives WebCrypto testables offline via Node) + `static/sw.js` (Service Worker qui reprend le design de l'upstream mais pointe vers notre propre endpoint de streaming au lieu d'une URL S3 présignée — un seul hop au lieu de deux, puisqu'il n'y a pas de S3). Purge des transferts expirés câblée sur `core/horloge.py` (le mécanisme de tâche planifiée déjà utilisé par `veille-info`), pas de nouveau scheduler.

**Tech Stack:** Python 3.12, FastAPI, SQLite (stdlib), aucune lib crypto côté serveur (le serveur ne voit jamais le clair — zéro crypto server-side, c'est la propriété qu'on vend). JS : Web Crypto API native (aucune dépendance npm), Node ≥19 pour les tests offline du module crypto (`globalThis.crypto.subtle` et `TransformStream` sont natifs depuis Node 16.5/19 — vérifié sur cette machine : `node --version` → v25.6.1, `typeof globalThis.crypto.subtle` → `object`, `typeof globalThis.TransformStream` → `function`).

---

## Risques / Décisions à trancher (arbitrage obligatoire)

### Arbitrage Option A vs Option B : **Option A — Vendoring léger**, tranché

**Décision : Option A.** On ne prend QUE le mécanisme de chiffrement E2E (le design WebCrypto + Service Worker), réimplémenté à la main en JS vanilla dans une brique FastAPI native. On ne fork PAS l'application Django complète.

**Justification, avec preuves tirées du repo réel :**

1. **Aucune brique Workplace n'utilise S3/MinIO.** `grep -ril minio briques/ shared/` et `grep -ril "boto3\|S3_ENDPOINT" briques/ shared/` ne remontent **rien** de pertinent (seuls des faux positifs dans des `node_modules`/`.venv` non liés). Toutes les briques qui stockent des fichiers (`export` :6150, `video` :5970, `mail` :6030) le font sur **volume Docker local + SQLite**, jamais sur un object store. Forker `transfers` tel quel imposerait d'introduire MinIO (ou un vrai S3) dans le stack Workplace **pour cette seule brique** — rupture de convention, coût d'infra (un service de plus à surveiller/sauvegarder) sans bénéfice pour un usage familial/petite équipe.

2. **`transfers` est une appli Django multi-services** (Postgres, Celery, Redis, Keycloak OIDC, React/Vite/TanStack Router, ClamAV) — chacune des briques Workplace existantes (`mail`, `export`, `video`, `veille-info`…) est **un seul conteneur FastAPI + SQLite**, zéro dépendance externe lourde. Faire cohabiter un sous-système à 5 conteneurs pour une seule fonctionnalité (transfert de fichier) casserait la promesse d'autonomie légère du `GUIDE-ajouter-une-brique.md` (« une brique = un dossier, son `docker-compose`, sa santé ») et doublerait la surface d'exploitation (encore un Postgres, encore un Redis à sauvegarder/monitorer sur le HP).

3. **La feature qu'on veut vraiment, c'est le chiffrement E2E** — pas l'antivirus ClamAV, pas l'import Google Drive, pas Keycloak OIDC (Workplace a déjà son propre Keycloak mesh, cf. mémoire `sprint-s181-acces-distant-cercle-prive`), pas le multi-tenant Django. Le mécanisme crypto (`encryption.ts` + `sw.js`, lu en détail ci-dessous) est **~400 lignes de JS pur, sans dépendance**, entièrement portable. C'est un candidat idéal au vendoring : on recopie le *design*, pas le code Python/Django qui l'entoure.

4. **Coût de maintenance** : Option B nous engagerait à suivre les migrations Django du fork, régler les CVE de Celery/Postgres/ClamAV, et gérer un onboarding Keycloak dédié — pour un produit dont Workplace n'a besoin que d'une fraction. Option A donne un service ~600 lignes Python+JS, dans le langage et le patron déjà maîtrisés par toutes les autres briques.

**Conséquence acceptée** : on **perd** certaines features de l'upstream — antivirus ClamAV, import direct Google Drive, mode "normal" (clé détenue par le serveur), auth Keycloak dédiée par destinataire, chunking S3 multipart avec vraies URLs présignées parallélisées. Toutes sont documentées comme hors-périmètre v1 ci-dessous (YAGNI), pas oubliées.

### Autres décisions tranchées dans ce plan (à ne pas rouvrir sans raison)

- **v1 = TOUJOURS confidentiel (E2E pur), pas de mode "normal".** L'upstream a un flag `confidential` : en mode "normal" la clé est postée au backend et stockée en DB (protège seulement contre une fuite S3-only). Ce mode n'a aucun intérêt pour Workplace — l'objectif du sprint est justement de ne **jamais** voir le clair, et une brique qui propose les deux modes double la surface de test et de bug pour une fonctionnalité qu'on ne veut pas vendre. **Décision : la clé ne transite JAMAIS par le serveur**, point final. Ça simplifie aussi radicalement le schéma (pas de colonne `cle_chiffrement`, pas de logique de toggle) et le protocole de finalisation (pas de body sur `POST /finaliser`).
- **Pas de vrai "S3 multipart"** : sans S3, chaque partie chiffrée (un "crypto chunk" de l'upstream) est un `PUT` HTTP direct vers notre propre FastAPI (pas une URL présignée vers un tiers), écrite sur disque sous forme de fichier `.partN`, puis concaténée à la finalisation. Le format sur le fil (`IV(12) | ciphertext | tag(16)` par partie, AAD `id_fichier:numero:nb_parties`) est **identique bit-à-bit** au design upstream — seul le transport (notre endpoint au lieu de S3) change. Le téléchargement fait donc **un seul hop** (le Service Worker interroge directement notre endpoint de streaming) au lieu du double hop *backend-JSON puis S3-anonyme* de l'upstream (ce double hop existe chez eux uniquement pour contourner les particularités CORS/cookies d'un fetch vers S3, qui ne s'appliquent pas ici puisque tout est même origine).
- **Pas d'antivirus, pas d'import Drive** : hors périmètre v1 (YAGNI) — le serveur ne voit que du ciphertext opaque de toute façon, un ClamAV serait aveugle comme chez l'upstream (`complete_upload` marque les fichiers chiffrés `SKIPPED`, cf. `docs/ENCRYPTION.md` de l'upstream) donc l'intérêt est déjà nul même côté source.
- **Auth à deux vitesses, mirroring `briques/restaurant`** (accès public par QR, sans clé d'API) : `API_KEYS`/`X-API-Key` ne gate QUE la création d'un transfert (`POST /transferts`) et les deux capacités du Cœur (`transferts_lister`, `transferts_revoquer`). Les routes d'upload de parties, de finalisation, de métadonnées publiques et de streaming du ciphertext ne sont **volontairement pas gatées par API_KEYS** : un destinataire hors du foyer doit pouvoir ouvrir un lien de partage sans détenir de clé d'API Workplace. Leur protection vient de jetons non devinables : `jeton_upload` (32 octets aléatoires, contrôle qui peut écrire des parties/finaliser un brouillon donné) et `jeton_public` + fragment de clé dans l'URL (contrôle qui peut télécharger). C'est exactement le motif déjà en place pour les QR de table du restaurant (6010).
- **Isolation multi-utilisateur légère** : chaque transfert porte un `proprietaire` dérivé de `X-User-Id` (défaut `"perso"`), dans l'esprit S182/S183 (mémoire : `sprint-s182-s183-multiutilisateur-espaces`), mais **sans** le hachage de clé d'API multi-tenant complet de `veille-info` — un transfert est de toute façon partagé hors du foyer via son lien, l'isolement stricte tenant-par-tenant n'a pas la même valeur ici. `transferts_lister` ne renvoie que les transferts du `proprietaire` courant.
- **Port 6180** — reconfirmé libre en lisant `port` dans les 33 `briques/*/manifest.json` existants au moment de l'écriture (liste : 4001, 5100, 5200, 5300, 5400, 5500, 5600, 5700, 5800, 5870, 5900, 5950, 5955, 5960, 5970, 5980, 5985, 5990, 6010, 6020, 6030, 6040, 6050, 6060, 6085, 6090, 6100, 6110, 6120, 6130, 6140, 6150, 6160 ; `app-builder` a `port: null`). Rien à 6170 ni 6180.
- **Taille de partie par défaut plus petite que l'upstream** : 16 Mio (`TAILLE_PARTIE_OCTETS`) au lieu des 25 Mio de l'upstream — choix arbitraire mais documenté : réduit la RAM par partie côté client ET côté serveur (le serveur bufferise une partie entière en RAM le temps d'une requête, comme WebCrypto le fait côté navigateur pour `subtle.encrypt`), sur du matériel de foyer (HP domestique, pas un cluster). Reste largement suffisant pour un fichier de plusieurs Gio (un fichier de 20 Gio fait ~1250 parties).

---

## Global Constraints

- Spec de référence pour le mécanisme crypto : `docs/ENCRYPTION.md`, `src/frontend/src/features/transfers/upload/encryption.ts`, `src/frontend/src/features/transfers/upload/encryptionServiceWorker.ts`, `src/frontend/public/sw.js` du dépôt `suitenumerique/transfers` (cloné en lecture seule dans `/tmp/transfers-research`, PAS committé dans Workplace).
- Port **6180** (vérifié libre, voir ci-dessus).
- Pas d'import de `shared/` → build-context **local** (`build: .`), per `GUIDE-ajouter-une-brique.md` §3.
- Auth : `API_KEYS` (CSV) + `CORS_ORIGINS` (CSV) lues depuis le `.env` racine via `env_file`, MAIS seules les routes de gestion (`POST /transferts`, `GET /transferts`, `POST /transferts/{id}/revoquer`) sont derrière `cle_api()` — voir arbitrage ci-dessus pour pourquoi les routes d'upload/download publiques ne le sont pas.
- `TRANSFERTS_KEY` : jeton partagé dédié pour l'horloge (`verifier_cle_horloge`, motif identique à `VEILLE_INFO_KEY` dans `briques/veille-info/main.py`), distinct de `API_KEYS`.
- Toute capacité qui écrit/détruit doit avoir `"action": true` (per `GUIDE-ajouter-une-brique.md` §2 et le précédent réel `video_carte_titre`) : `transferts_revoquer` est `action:true`. `transferts_lister` est `action:false` (lecture).
- Aucun flux binaire (upload de partie, streaming de ciphertext) n'est déclaré comme capacité JSON — per `GUIDE-ajouter-une-brique.md` §2 : « Un flux binaire … reste appelé en direct par son client, pas déclaré comme outil texte. » Ces routes existent mais ne sont dans AUCUNE entrée `capacites`.
- Manifest doit satisfaire `tests/test_briques_smoke.py` : `statut: "a_tester"`, `couche: "backend"` ⇒ `port`+`url_sante` requis et `url_sante` doit contenir les chiffres du port, `capacites[].nom`/`chemin` requis, `taches[].nom`/`chemin` requis (contrat `core/horloge.py::_CHAMPS_REQUIS`), pas de collision de port, pas de nom de brique dupliqué.
- **Commit policy : un commit par tâche**, chaque tâche se termine par son propre commit une fois ses tests verts (motif standard du repo, cf. plan S194 §Global Constraints — pas de squash fin de sprint).
- **Tests offline uniquement pour la logique pure** : le module crypto (`static/chiffrement.js`) est testé via `node --test` (Node ≥19, vérifié disponible : v25.6.1) — AES-GCM/WebCrypto et `TransformStream` sont natifs, zéro dépendance npm à installer. `sw.js` lui-même (scope Service Worker : `self`, `clients.claim()`, `fetch` event) n'est PAS unit-testable hors navigateur — son algorithme de déchiffrement en flux est une quasi-copie de celui déjà testé dans `chiffrement.js` (documenté explicitement en Task 5, même duplication assumée que l'upstream entre `encryption.ts` et `sw.js`) ; la preuve réelle bout-en-bout se fait au navigateur en Task 7 (régime de preuve Docker différé, cf. mémoire `regime-preuve-docker-differe`).

---

### Task 1: Scaffold la brique — manifest, Dockerfile, docker-compose, endpoint santé

**Files:**
- Create: `briques/transferts/manifest.json`
- Create: `briques/transferts/requirements.txt`
- Create: `briques/transferts/Dockerfile`
- Create: `briques/transferts/docker-compose.yml`
- Create: `briques/transferts/conftest.py`
- Create: `briques/transferts/main.py` (santé/scaffold uniquement — reste ajouté en Task 4)
- Test: `briques/transferts/test_api.py` (santé uniquement — étendu en Task 4)

**Interfaces:**
- Produces: FastAPI `app` dans `main.py`, `cle_api()` (même signature que `briques/export/main.py`), `GET /sante`, `GET /` — consommés tels quels par Task 4.

- [ ] **Step 1: Create `briques/transferts/requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
```

(Aucune lib crypto : le serveur ne chiffre/déchiffre jamais, c'est tout l'intérêt du modèle E2E — voir arbitrage.)

- [ ] **Step 2: Create `briques/transferts/manifest.json`** (`capacites`/`taches` vides pour l'instant, ajoutées en Task 6)

```json
{
  "nom": "transferts",
  "famille": "media",
  "version": "0.1.0",
  "description": "Transfert de gros fichiers (jusqu'à ~20 Gio) via un lien à expiration, chiffré bout-en-bout dans le navigateur (AES-256-GCM/WebCrypto) : la clé ne transite jamais par le serveur (fragment d'URL), le Service Worker du destinataire déchiffre en streaming direct vers le téléchargement. Vendoring léger du design crypto de suitenumerique/transfers (S196), pas de fork Django.",
  "role": "transferts",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/transferts",
  "port": 6180,
  "url_sante": "http://host.docker.internal:6180/sante",
  "depends_on": [],
  "offre": ["transfert_fichier_e2e", "lien_expirant", "purge_automatique"],
  "besoin": [],
  "capacites": [],
  "taches": []
}
```

- [ ] **Step 3: Create `briques/transferts/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6180"]
```

- [ ] **Step 4: Create `briques/transferts/docker-compose.yml`**

```yaml
services:
  transferts:
    build: .
    container_name: workplace_transferts
    image: workplace/transferts:0.1.0
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6180:6180"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TRANSFERTS_DIR=/data/fichiers
      - TRANSFERTS_DB=/data/transferts.db
      - TAILLE_PARTIE_OCTETS=16777216
      - TAILLE_MAX_OCTETS=21474836480
      - EXPIRATION_MAX_HEURES=168
      - EXPIRATION_DEFAUT_HEURES=72
    volumes:
      - transferts_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6180/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  transferts_data:
```

- [ ] **Step 5: Create `briques/transferts/conftest.py`**

```python
"""Config de test : stockage temporaire, mode API ouvert (déterministe)."""
import os
import tempfile

_DIR = os.path.join(tempfile.gettempdir(), "transferts_brique_test")
os.environ["TRANSFERTS_DIR"] = _DIR
os.environ["TRANSFERTS_DB"] = os.path.join(_DIR, "transferts.db")
os.environ["API_KEYS"] = ""       # mode ouvert : tests n'ont pas à fournir de clé
os.environ["TRANSFERTS_KEY"] = "" # idem pour la route horloge
os.environ.setdefault("TAILLE_PARTIE_OCTETS", "16")   # petites parties : tests rapides
os.environ.setdefault("TAILLE_MAX_OCTETS", "1000000")
os.environ.setdefault("EXPIRATION_MAX_HEURES", "168")
os.environ.setdefault("EXPIRATION_DEFAUT_HEURES", "72")
```

- [ ] **Step 6: Create `briques/transferts/main.py`** (scaffold : santé + CORS/auth uniquement)

```python
"""Brique « transferts » — transfert de gros fichiers chiffrés bout-en-bout (S196).

Le serveur ne voit JAMAIS le clair : chaque fichier est chiffré (AES-256-GCM)
dans le navigateur de l'expéditeur AVANT l'upload, la clé vit uniquement dans
le fragment `#` de l'URL de partage (jamais envoyée au serveur, cf.
docs/ENCRYPTION.md du dépôt suitenumerique/transfers, vendoring du design en
S196). Ce fichier ne contient donc AUCUNE ligne de crypto : c'est un simple
stockage de blobs opaques + métadonnées + expiration.
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(title="Transferts — fichiers chiffrés bout-en-bout", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Gate des routes de GESTION uniquement (créer/lister/révoquer) — PAS des
    routes publiques d'upload/téléchargement, cf. arbitrage du plan S196."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


TRANSFERTS_DIR = Path(os.getenv("TRANSFERTS_DIR", "/data/fichiers"))
TRANSFERTS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return "<h1>📦 Brique transferts</h1><p>Transfert de fichiers chiffré bout-en-bout. Voir <a href='/docs'>/docs</a>.</p>"


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True}
```

- [ ] **Step 7: Write the failing test — `briques/transferts/test_api.py`**

```python
"""Tests — API de la brique transferts."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

- [ ] **Step 8: Run the tests**

```bash
cd briques/transferts && python3 -m pip install -r requirements.txt -q && python3 -m pytest -q
```
Expected: 1 passed.

- [ ] **Step 9: Validate the manifest against the smoke test**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke
```
Expected: all pass, including new `briques/transferts` entries (`test_manifest_est_un_json_valide`, `test_manifest_porte_les_champs_requis`, `test_brique_backend_porte_le_contrat_reseau`, `test_statut_est_connu`, `test_url_sante_contient_le_port`, `test_noms_de_briques_uniques`, `test_aucune_collision_de_port`).

- [ ] **Step 10: Commit**

```bash
git add briques/transferts
git commit -m "feat(transferts): scaffold — manifest, Dockerfile, docker-compose, /sante (S196)"
```

---

### Task 2: `stockage.py` — persistance SQLite (transferts, fichiers, parties) + purge

**Files:**
- Create: `briques/transferts/stockage.py`
- Test: `briques/transferts/test_stockage.py`

**Interfaces:**
- Produces: `init_db() -> None`; `creer_transfert(proprietaire: str, expiration_heures: int) -> dict` (`{id, jeton_upload, expire_le}`); `ajouter_fichier(transfert_id: str, jeton_upload: str, nom: str, type_mime: str, taille_clair: int, taille_partie: int) -> dict` (`{id, nb_parties}`), raises `ValueError` si jeton invalide/transfert introuvable/pas en brouillon/taille excessive; `ecrire_partie(transfert_id: str, fichier_id: str, jeton_upload: str, numero: int, donnees: bytes) -> dict` (`{parties_recues, nb_parties, complet}`); `finaliser_transfert(transfert_id: str, jeton_upload: str) -> dict` (`{jeton_public}`), raises `ValueError` si un fichier n'est pas complet; `lire_transfert_public(jeton_public: str) -> dict | None` (`{id, statut, expire_le, fichiers: [...]}`, `None` si introuvable, statut `"expire"` si `expire_le` dépassé); `chemin_ciphertext(transfert_id: str, fichier_id: str) -> Path`; `enregistrer_telechargement(transfert_id: str) -> None`; `lister_transferts(proprietaire: str) -> list[dict]`; `revoquer(transfert_id: str, proprietaire: str) -> bool` (False si introuvable/pas le propriétaire); `purger_expires() -> int` (nombre de transferts purgés). Consommé par `main.py` en Task 4.

- [ ] **Step 1: Write the failing tests — `briques/transferts/test_stockage.py`**

```python
"""Tests — stockage.py (SQLite + fichiers sur disque, tout est réel, rien n'est mocké :
c'est juste du I/O local, pas de dépendance externe)."""
import time
from pathlib import Path

import pytest

import stockage


@pytest.fixture(autouse=True)
def _base_propre(tmp_path, monkeypatch):
    monkeypatch.setattr(stockage, "DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(stockage, "DIR", tmp_path / "fichiers")
    stockage.DIR.mkdir(parents=True, exist_ok=True)
    stockage.init_db()


def test_creer_transfert_genere_un_jeton_upload_et_une_expiration():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    assert t["jeton_upload"]
    assert len(t["jeton_upload"]) >= 32
    assert t["expire_le"] > time.time()


def test_ajouter_fichier_calcule_le_nombre_de_parties():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "photo.jpg", "image/jpeg",
                                  taille_clair=40, taille_partie=16)
    assert f["nb_parties"] == 3   # ceil(40/16) = 3


def test_ajouter_fichier_jeton_invalide_leve():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    with pytest.raises(ValueError, match="jeton"):
        stockage.ajouter_fichier(t["id"], "mauvais-jeton", "x.bin", "application/octet-stream",
                                  taille_clair=10, taille_partie=16)


def test_ecrire_partie_puis_completude():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=20, taille_partie=16)
    # 2 parties attendues : 16 + 4 (clair) => 16+28=44 et 4+28=32 octets chiffrés
    r1 = stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"x" * 44)
    assert r1["complet"] is False
    r2 = stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 1, b"y" * 32)
    assert r2["complet"] is True
    assert r2["parties_recues"] == 2


def test_ecrire_partie_reecriture_idempotente():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=10, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"z" * 38)
    r = stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"z" * 38)  # retry réseau
    assert r["parties_recues"] == 1   # pas doublé


def test_finaliser_avant_completude_leve():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                              taille_clair=20, taille_partie=16)
    with pytest.raises(ValueError, match="complet"):
        stockage.finaliser_transfert(t["id"], t["jeton_upload"])


def test_finaliser_concatene_les_parties_dans_l_ordre():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=20, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 44)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 1, b"B" * 32)
    res = stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    assert res["jeton_public"]
    chemin = stockage.chemin_ciphertext(t["id"], f["id"])
    assert chemin.read_bytes() == b"A" * 44 + b"B" * 32


def test_lire_transfert_public_apres_finalisation():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=20, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 44)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 1, b"B" * 32)
    res = stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    pub = stockage.lire_transfert_public(res["jeton_public"])
    assert pub["statut"] == "actif"
    assert len(pub["fichiers"]) == 1
    assert pub["fichiers"][0]["nom"] == "x.bin"


def test_lire_transfert_public_inconnu_est_none():
    assert stockage.lire_transfert_public("nimporte-quoi") is None


def test_lire_transfert_public_expire():
    t = stockage.creer_transfert("perso", expiration_heures=-1)  # déjà expiré
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=1, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 29)
    res = stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    pub = stockage.lire_transfert_public(res["jeton_public"])
    assert pub["statut"] == "expire"


def test_lister_transferts_scope_par_proprietaire():
    stockage.creer_transfert("alice", expiration_heures=1)
    stockage.creer_transfert("bob", expiration_heures=1)
    assert len(stockage.lister_transferts("alice")) == 1
    assert len(stockage.lister_transferts("bob")) == 1


def test_revoquer_supprime_les_fichiers_sur_disque():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=10, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 38)
    stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    chemin = stockage.chemin_ciphertext(t["id"], f["id"])
    assert chemin.exists()
    assert stockage.revoquer(t["id"], "perso") is True
    assert not chemin.exists()
    assert stockage.lister_transferts("perso") == []


def test_revoquer_mauvais_proprietaire_refuse():
    t = stockage.creer_transfert("alice", expiration_heures=1)
    assert stockage.revoquer(t["id"], "bob") is False


def test_purger_expires_supprime_disque_et_db():
    t = stockage.creer_transfert("perso", expiration_heures=-1)  # déjà expiré
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=1, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 29)
    stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    chemin = stockage.chemin_ciphertext(t["id"], f["id"])
    assert chemin.exists()
    assert stockage.purger_expires() == 1
    assert not chemin.exists()
    assert stockage.lister_transferts("perso") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/transferts && python3 -m pytest test_stockage.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'stockage'`.

- [ ] **Step 3: Implement `briques/transferts/stockage.py`**

```python
"""Persistance de la brique transferts (SQLite + fichiers ciphertext sur disque).

Le serveur ne stocke QUE du binaire opaque (ciphertext) + des métadonnées
(nom, taille, expiration) — jamais de clé, jamais de clair (v1 = toujours
confidentiel/E2E, cf. arbitrage du plan S196 : pas de mode "normal" où le
serveur détiendrait la clé).

Disposition sur disque : FICHIERS_DIR/<transfert_id>/<fichier_id>.partN pendant
l'upload (une partie = un fichier), concaténées en <fichier_id>.bin à la
finalisation (mêmes octets, dans l'ordre — mirrors le "contiguous concatenation
of N chunks" de suitenumerique/transfers, cf. docs/ENCRYPTION.md § What lands
in S3).
"""
from __future__ import annotations

import math
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

DB = os.getenv("TRANSFERTS_DB", "/data/transferts.db")
DIR = Path(os.getenv("TRANSFERTS_DIR", "/data/fichiers"))
TAILLE_MAX_OCTETS = int(os.getenv("TAILLE_MAX_OCTETS", str(20 * 1024 ** 3)))

_SURCOUT_PAR_PARTIE = 28  # IV(12) + tag GCM(16) — même constante que encryption.ts


def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS transferts (
                id TEXT PRIMARY KEY, proprietaire TEXT NOT NULL,
                jeton_upload TEXT NOT NULL, jeton_public TEXT UNIQUE,
                statut TEXT NOT NULL DEFAULT 'brouillon',
                cree_le REAL NOT NULL, expire_le REAL NOT NULL,
                telecharge_fois INTEGER NOT NULL DEFAULT 0)
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_transferts_proprietaire ON transferts(proprietaire)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS fichiers (
                id TEXT PRIMARY KEY, transfert_id TEXT NOT NULL,
                nom TEXT NOT NULL, type_mime TEXT NOT NULL,
                taille_clair INTEGER NOT NULL, taille_partie INTEGER NOT NULL,
                nb_parties INTEGER NOT NULL,
                FOREIGN KEY (transfert_id) REFERENCES transferts(id))
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_fichiers_transfert ON fichiers(transfert_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS parties (
                fichier_id TEXT NOT NULL, numero INTEGER NOT NULL, taille INTEGER NOT NULL,
                PRIMARY KEY (fichier_id, numero))
        """)


def _repertoire_transfert(transfert_id: str) -> Path:
    d = DIR / transfert_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chemin_partie(transfert_id: str, fichier_id: str, numero: int) -> Path:
    return _repertoire_transfert(transfert_id) / f"{fichier_id}.part{numero}"


def chemin_ciphertext(transfert_id: str, fichier_id: str) -> Path:
    return _repertoire_transfert(transfert_id) / f"{fichier_id}.bin"


def creer_transfert(proprietaire: str, expiration_heures: float) -> dict:
    tid = uuid.uuid4().hex
    jeton_upload = secrets.token_urlsafe(32)
    maintenant = time.time()
    expire_le = maintenant + expiration_heures * 3600
    with _conn() as c:
        c.execute(
            "INSERT INTO transferts (id, proprietaire, jeton_upload, statut, cree_le, expire_le) "
            "VALUES (?, ?, ?, 'brouillon', ?, ?)",
            (tid, proprietaire, jeton_upload, maintenant, expire_le),
        )
    return {"id": tid, "jeton_upload": jeton_upload, "expire_le": expire_le}


def _transfert_brouillon(c: sqlite3.Connection, transfert_id: str, jeton_upload: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM transferts WHERE id = ?", (transfert_id,)).fetchone()
    if not row:
        raise ValueError("Transfert introuvable.")
    if row["jeton_upload"] != jeton_upload:
        raise ValueError("jeton d'upload invalide.")
    if row["statut"] != "brouillon":
        raise ValueError(f"Transfert déjà {row['statut']} (plus modifiable).")
    return row


def ajouter_fichier(transfert_id: str, jeton_upload: str, nom: str, type_mime: str,
                     taille_clair: int, taille_partie: int) -> dict:
    if taille_clair > TAILLE_MAX_OCTETS:
        raise ValueError(f"Fichier trop volumineux ({taille_clair} > {TAILLE_MAX_OCTETS} octets).")
    if taille_clair < 0 or taille_partie <= 0:
        raise ValueError("Taille de fichier ou de partie invalide.")
    nb_parties = 1 if taille_clair == 0 else math.ceil(taille_clair / taille_partie)
    with _conn() as c:
        _transfert_brouillon(c, transfert_id, jeton_upload)
        fid = uuid.uuid4().hex
        c.execute(
            "INSERT INTO fichiers (id, transfert_id, nom, type_mime, taille_clair, taille_partie, nb_parties) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fid, transfert_id, nom, type_mime, taille_clair, taille_partie, nb_parties),
        )
    return {"id": fid, "nb_parties": nb_parties}


def ecrire_partie(transfert_id: str, fichier_id: str, jeton_upload: str,
                   numero: int, donnees: bytes) -> dict:
    with _conn() as c:
        _transfert_brouillon(c, transfert_id, jeton_upload)
        f = c.execute("SELECT * FROM fichiers WHERE id = ? AND transfert_id = ?",
                       (fichier_id, transfert_id)).fetchone()
        if not f:
            raise ValueError("Fichier introuvable dans ce transfert.")
        if not (0 <= numero < f["nb_parties"]):
            raise ValueError(f"Numéro de partie hors bornes (0..{f['nb_parties'] - 1}).")
        _chemin_partie(transfert_id, fichier_id, numero).write_bytes(donnees)
        c.execute(
            "INSERT INTO parties (fichier_id, numero, taille) VALUES (?, ?, ?) "
            "ON CONFLICT(fichier_id, numero) DO UPDATE SET taille = excluded.taille",
            (fichier_id, numero, len(donnees)),
        )
        recues = c.execute("SELECT COUNT(*) AS n FROM parties WHERE fichier_id = ?",
                            (fichier_id,)).fetchone()["n"]
    return {"parties_recues": recues, "nb_parties": f["nb_parties"], "complet": recues == f["nb_parties"]}


def finaliser_transfert(transfert_id: str, jeton_upload: str) -> dict:
    with _conn() as c:
        _transfert_brouillon(c, transfert_id, jeton_upload)
        fichiers = c.execute("SELECT * FROM fichiers WHERE transfert_id = ?",
                              (transfert_id,)).fetchall()
        if not fichiers:
            raise ValueError("Aucun fichier ajouté à ce transfert.")
        for f in fichiers:
            recues = c.execute("SELECT COUNT(*) AS n FROM parties WHERE fichier_id = ?",
                                (f["id"],)).fetchone()["n"]
            if recues != f["nb_parties"]:
                raise ValueError(f"Fichier '{f['nom']}' pas complet ({recues}/{f['nb_parties']} parties).")

        for f in fichiers:
            cible = chemin_ciphertext(transfert_id, f["id"])
            with open(cible, "wb") as out:
                for n in range(f["nb_parties"]):
                    partie = _chemin_partie(transfert_id, f["id"], n)
                    out.write(partie.read_bytes())
                    partie.unlink()

        jeton_public = secrets.token_urlsafe(24)
        c.execute("UPDATE transferts SET statut = 'actif', jeton_public = ? WHERE id = ?",
                  (jeton_public, transfert_id))
    return {"jeton_public": jeton_public}


def lire_transfert_public(jeton_public: str) -> dict | None:
    with _conn() as c:
        t = c.execute("SELECT * FROM transferts WHERE jeton_public = ?", (jeton_public,)).fetchone()
        if not t:
            return None
        fichiers = c.execute(
            "SELECT id, nom, type_mime, taille_clair, taille_partie FROM fichiers WHERE transfert_id = ?",
            (t["id"],)).fetchall()
    statut = t["statut"]
    if statut == "actif" and t["expire_le"] <= time.time():
        statut = "expire"
    return {
        "id": t["id"], "statut": statut, "expire_le": t["expire_le"],
        "fichiers": [dict(f) for f in fichiers],
    }


def enregistrer_telechargement(transfert_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE transferts SET telecharge_fois = telecharge_fois + 1 WHERE id = ?",
                  (transfert_id,))


def lister_transferts(proprietaire: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, statut, cree_le, expire_le, telecharge_fois FROM transferts "
            "WHERE proprietaire = ? AND statut != 'revoque' ORDER BY cree_le DESC",
            (proprietaire,)).fetchall()
    return [dict(r) for r in rows]


def _supprimer_disque(transfert_id: str) -> None:
    d = DIR / transfert_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def revoquer(transfert_id: str, proprietaire: str) -> bool:
    with _conn() as c:
        t = c.execute("SELECT * FROM transferts WHERE id = ? AND proprietaire = ?",
                       (transfert_id, proprietaire)).fetchone()
        if not t:
            return False
        c.execute("DELETE FROM parties WHERE fichier_id IN "
                  "(SELECT id FROM fichiers WHERE transfert_id = ?)", (transfert_id,))
        c.execute("DELETE FROM fichiers WHERE transfert_id = ?", (transfert_id,))
        c.execute("DELETE FROM transferts WHERE id = ?", (transfert_id,))
    _supprimer_disque(transfert_id)
    return True


def purger_expires() -> int:
    maintenant = time.time()
    with _conn() as c:
        expires = c.execute(
            "SELECT id FROM transferts WHERE expire_le <= ? OR statut = 'revoque'",
            (maintenant,)).fetchall()
        ids = [r["id"] for r in expires]
        if ids:
            marks = ",".join("?" * len(ids))
            c.execute(f"DELETE FROM parties WHERE fichier_id IN "
                      f"(SELECT id FROM fichiers WHERE transfert_id IN ({marks}))", ids)
            c.execute(f"DELETE FROM fichiers WHERE transfert_id IN ({marks})", ids)
            c.execute(f"DELETE FROM transferts WHERE id IN ({marks})", ids)
    for tid in ids:
        _supprimer_disque(tid)
    return len(ids)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/transferts && python3 -m pytest test_stockage.py -v
```
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add briques/transferts/stockage.py briques/transferts/test_stockage.py
git commit -m "feat(transferts): stockage.py — SQLite + fichiers concaténés, expiration/purge (S196)"
```

---

### Task 3: `static/chiffrement.js` — primitives crypto E2E vendorées (testées offline via Node)

**Files:**
- Create: `briques/transferts/static/chiffrement.js`
- Test: `briques/transferts/static/chiffrement.test.mjs`

**Interfaces:**
- Produces (module ES, importé à la fois par les pages HTML du navigateur en Task 5 et par les tests Node) : `SURCOUT_PAR_PARTIE = 28`; `genererCle(): Promise<{cleCrypto: CryptoKey, fragment: string}>`; `importerCle(fragment: string): Promise<CryptoKey>`; `aadPourPartie(idFichier: string, numero: number, nbParties: number): Uint8Array`; `nbParties(tailleClair: number, taillePartie: number): number`; `tailleChiffree(tailleClair: number, taillePartie: number): number`; `chiffrerPartie(cle: CryptoKey, clair: Uint8Array, aad: Uint8Array): Promise<Uint8Array>`; `dechiffrerPartie(cle: CryptoKey, partieChiffree: Uint8Array, aad: Uint8Array): Promise<Uint8Array>`; `encoderBase64Url(octets: Uint8Array): string`; `decoderBase64Url(s: string): Uint8Array`; `creerFluxDechiffrement(cle: CryptoKey, taillePartie: number, tailleClairTotale: number, idFichier: string): TransformStream`. Consommé par les pages statiques en Task 5 (upload/download) et — algorithme dupliqué à l'identique, cf. note Task 5 — par `static/sw.js`.

- [ ] **Step 1: Write the failing tests — `briques/transferts/static/chiffrement.test.mjs`**

```javascript
// Tests offline du module crypto E2E — Node natif (WebCrypto + TransformStream
// sont globaux depuis Node 16.5/19, aucune dépendance npm). Lancé via
// `node --test`. Vérifie le mécanisme réimplémenté de suitenumerique/transfers
// (encryption.ts) : IV(12)|ciphertext|tag(16) par partie, AAD liant
// fileId:partNumber:parts contre le rejeu/l'échange de parties.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as C from "./chiffrement.js";

test("genererCle produit un fragment base64url de 43 caractères", async () => {
  const { fragment } = await C.genererCle();
  assert.equal(fragment.length, 43);
  assert.doesNotMatch(fragment, /[+/=]/);
});

test("importerCle(fragment) reconstruit la même clé (round-trip chiffrer/déchiffrer)", async () => {
  const { cleCrypto, fragment } = await C.genererCle();
  const cleReimportee = await C.importerCle(fragment);
  const aad = C.aadPourPartie("f1", 0, 1);
  const clair = new TextEncoder().encode("bonjour");
  const chiffre = await C.chiffrerPartie(cleCrypto, clair, aad);
  const dechiffre = await C.dechiffrerPartie(cleReimportee, chiffre, aad);
  assert.equal(new TextDecoder().decode(dechiffre), "bonjour");
});

test("nbParties et tailleChiffree suivent la formule ceil(clair/partie) + surcout", () => {
  assert.equal(C.nbParties(40, 16), 3);
  assert.equal(C.nbParties(0, 16), 1);          // fichier vide : 1 partie authentifiée quand même
  assert.equal(C.tailleChiffree(40, 16), 40 + 3 * C.SURCOUT_PAR_PARTIE);
  assert.equal(C.tailleChiffree(0, 16), C.SURCOUT_PAR_PARTIE);
});

test("chiffrerPartie produit IV(12) + ciphertext + tag(16), taille = clair + surcout", async () => {
  const { cleCrypto } = await C.genererCle();
  const clair = new Uint8Array(100).fill(7);
  const chiffre = await C.chiffrerPartie(cleCrypto, clair, C.aadPourPartie("f", 0, 1));
  assert.equal(chiffre.length, 100 + C.SURCOUT_PAR_PARTIE);
});

test("dechiffrerPartie rejette une AAD différente (partie échangée/réordonnée)", async () => {
  const { cleCrypto } = await C.genererCle();
  const clair = new TextEncoder().encode("secret");
  const chiffre = await C.chiffrerPartie(cleCrypto, clair, C.aadPourPartie("f1", 0, 2));
  await assert.rejects(() => C.dechiffrerPartie(cleCrypto, chiffre, C.aadPourPartie("f1", 1, 2)));
});

test("encoderBase64Url / decoderBase64Url round-trip sur des octets aléatoires", () => {
  const octets = crypto.getRandomValues(new Uint8Array(32));
  const s = C.encoderBase64Url(octets);
  assert.deepEqual(Array.from(C.decoderBase64Url(s)), Array.from(octets));
});

test("creerFluxDechiffrement reconstruit le clair depuis un flux ciphertext TCP-fragmenté", async () => {
  const { cleCrypto } = await C.genererCle();
  const taillePartie = 8;
  const idFichier = "fichier-test";
  // 3 parties de clair : 8 + 8 + 4 = 20 octets
  const clairTotal = new Uint8Array(20).map((_, i) => i);
  const partiesClair = [clairTotal.slice(0, 8), clairTotal.slice(8, 16), clairTotal.slice(16, 20)];
  const parties = C.nbParties(20, taillePartie);
  const morceauxChiffres = [];
  for (let i = 0; i < partiesClair.length; i++) {
    morceauxChiffres.push(
      await C.chiffrerPartie(cleCrypto, partiesClair[i], C.aadPourPartie(idFichier, i, parties)),
    );
  }
  const ciphertextComplet = new Uint8Array(morceauxChiffres.reduce((n, m) => n + m.length, 0));
  let off = 0;
  for (const m of morceauxChiffres) { ciphertextComplet.set(m, off); off += m.length; }

  // Simule un flux réseau TCP : re-fragmente en morceaux arbitraires de 5 octets
  // (indépendants des frontières de partie chiffrée) pour vérifier le buffering interne.
  const source = new ReadableStream({
    start(controller) {
      for (let i = 0; i < ciphertextComplet.length; i += 5) {
        controller.enqueue(ciphertextComplet.slice(i, i + 5));
      }
      controller.close();
    },
  });

  const dechiffre = source.pipeThrough(
    C.creerFluxDechiffrement(cleCrypto, taillePartie, 20, idFichier),
  );
  const lecteur = dechiffre.getReader();
  const recu = [];
  for (;;) {
    const { done, value } = await lecteur.read();
    if (done) break;
    recu.push(...value);
  }
  assert.deepEqual(recu, Array.from(clairTotal));
});

test("creerFluxDechiffrement signale une erreur sur un flux tronqué", async () => {
  const { cleCrypto } = await C.genererCle();
  const idFichier = "f-tronque";
  const chiffre = await C.chiffrerPartie(
    cleCrypto, new Uint8Array(8).fill(1), C.aadPourPartie(idFichier, 0, 1),
  );
  const tronque = chiffre.slice(0, chiffre.length - 5);   // coupe les 5 derniers octets
  const source = new ReadableStream({
    start(controller) { controller.enqueue(tronque); controller.close(); },
  });
  const dechiffre = source.pipeThrough(C.creerFluxDechiffrement(cleCrypto, 8, 8, idFichier));
  const lecteur = dechiffre.getReader();
  await assert.rejects(async () => { while (!(await lecteur.read()).done); });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/transferts && node --test static/chiffrement.test.mjs
```
Expected: FAIL — `Cannot find module './chiffrement.js'`.

- [ ] **Step 3: Implement `briques/transferts/static/chiffrement.js`**

```javascript
// Primitives crypto E2E — AES-256-GCM via WebCrypto, vendorées à la main depuis
// le design de suitenumerique/transfers (docs/ENCRYPTION.md, encryption.ts),
// PAS un import de leur code : Workplace ne fork pas l'appli Django (S196).
//
// Layout par partie chiffrée : [ IV(12) | ciphertext | tag GCM(16) ].
// Une "partie" = un PUT HTTP direct vers notre propre endpoint (pas une URL S3
// présignée : sans S3, chaque partie va directement à notre FastAPI, cf. plan
// S196 § Risques/Décisions). L'AAD `idFichier:numero:nbParties` empêche
// l'échange/réordonnancement de parties entre fichiers ou positions (le tag
// GCM ne s'authentifie que si l'AAD recalculée est identique des deux côtés).
//
// La clé (32 octets aléatoires) ne quitte JAMAIS ce module vers le serveur :
// v1 est TOUJOURS en mode confidentiel/E2E pur (pas de mode "normal" où le
// serveur détiendrait la clé, cf. arbitrage du plan) — le `fragment` base64url
// vit uniquement dans le fragment `#` de l'URL de partage.

export const SURCOUT_PAR_PARTIE = 12 /* IV */ + 16 /* tag GCM */;
const TAILLE_CLE_OCTETS = 32;
const TAILLE_IV_OCTETS = 12;

export async function genererCle() {
  const brut = crypto.getRandomValues(new Uint8Array(TAILLE_CLE_OCTETS));
  const cleCrypto = await crypto.subtle.importKey(
    "raw", brut, { name: "AES-GCM" }, false, ["encrypt", "decrypt"],
  );
  return { cleCrypto, fragment: encoderBase64Url(brut) };
}

export async function importerCle(fragment) {
  const brut = decoderBase64Url(fragment);
  if (brut.length !== TAILLE_CLE_OCTETS) throw new Error("Longueur de clé invalide.");
  return crypto.subtle.importKey("raw", brut, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

export function aadPourPartie(idFichier, numero, nbParties) {
  return new TextEncoder().encode(`${idFichier}:${numero}:${nbParties}`);
}

export function nbParties(tailleClair, taillePartie) {
  if (tailleClair <= 0) return 1;   // fichier vide : une partie authentifiée (IV+tag) quand même
  return Math.ceil(tailleClair / taillePartie);
}

export function tailleChiffree(tailleClair, taillePartie) {
  return tailleClair + nbParties(tailleClair, taillePartie) * SURCOUT_PAR_PARTIE;
}

export async function chiffrerPartie(cle, clair, aad) {
  const iv = crypto.getRandomValues(new Uint8Array(TAILLE_IV_OCTETS));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad }, cle, clair),
  );
  const out = new Uint8Array(iv.length + ct.length);
  out.set(iv, 0);
  out.set(ct, iv.length);
  return out;
}

export async function dechiffrerPartie(cle, partieChiffree, aad) {
  if (partieChiffree.length < TAILLE_IV_OCTETS + 16) throw new Error("Partie chiffrée trop courte.");
  const iv = partieChiffree.subarray(0, TAILLE_IV_OCTETS);
  const corps = partieChiffree.subarray(TAILLE_IV_OCTETS);
  const clair = await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: aad }, cle, corps);
  return new Uint8Array(clair);
}

export function encoderBase64Url(octets) {
  let bin = "";
  for (let i = 0; i < octets.length; i++) bin += String.fromCharCode(octets[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decoderBase64Url(s) {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// TransformStream ciphertext → clair, en flux : le réseau livre le ciphertext
// en paquets TCP arbitraires (~64 Ko), pas alignés sur la frontière de partie
// chiffrée (tailleChiffréePartie = taillePartie + SURCOUT_PAR_PARTIE). On
// bufferise jusqu'à avoir une partie complète, on la déchiffre, on pousse le
// clair — jamais tout le fichier en RAM (mirrors sw.js::decryptStream de
// suitenumerique/transfers, docs/ENCRYPTION.md § Stream reassembly).
export function creerFluxDechiffrement(cle, taillePartie, tailleClairTotale, idFichier) {
  const tailleChiffreePartie = taillePartie + SURCOUT_PAR_PARTIE;
  const encoder = new TextEncoder();
  const parties = nbParties(tailleClairTotale, taillePartie);
  let enAttente = new Uint8Array(0);
  let clairRestant = tailleClairTotale;
  let numero = 0;

  function concat(a, b) {
    const bArr = b instanceof Uint8Array ? b : new Uint8Array(b);
    const out = new Uint8Array(a.length + bArr.length);
    out.set(a, 0);
    out.set(bArr, a.length);
    return out;
  }

  return new TransformStream({
    async transform(morceau, controller) {
      enAttente = concat(enAttente, morceau);
      while (clairRestant > taillePartie && enAttente.length >= tailleChiffreePartie) {
        const partieChiffree = enAttente.subarray(0, tailleChiffreePartie);
        enAttente = enAttente.slice(tailleChiffreePartie);
        const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
        const clair = await dechiffrerPartie(cle, partieChiffree, aad);
        controller.enqueue(clair);
        clairRestant -= clair.length;
        numero += 1;
      }
    },
    async flush(controller) {
      const attendu = clairRestant + SURCOUT_PAR_PARTIE;
      if (enAttente.length !== attendu) {
        controller.error(new Error(
          `Flux ciphertext tronqué (attendu ${attendu} octets restants, reçu ${enAttente.length}).`,
        ));
        return;
      }
      const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
      const clair = await dechiffrerPartie(cle, enAttente, aad);
      if (clair.length > 0) controller.enqueue(clair);
      clairRestant -= clair.length;
      if (clairRestant !== 0) {
        controller.error(new Error(`Taille de clair incohérente après déchiffrement (résiduel ${clairRestant}).`));
      }
    },
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/transferts && node --test static/chiffrement.test.mjs
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add briques/transferts/static/chiffrement.js briques/transferts/static/chiffrement.test.mjs
git commit -m "feat(transferts): chiffrement.js — primitives E2E AES-256-GCM vendorées, testées offline via Node (S196)"
```

---

### Task 4: `main.py` — endpoints upload/finalisation/téléchargement/gestion

**Files:**
- Modify: `briques/transferts/main.py`
- Modify: `briques/transferts/test_api.py`

**Interfaces:**
- Consumes: toutes les fonctions de `stockage.py` (Task 2).
- Produces: routes HTTP consommées par les pages statiques en Task 5 : `POST /transferts` (gate `cle_api`), `POST /transferts/{tid}/fichiers`, `PUT /transferts/{tid}/fichiers/{fid}/parties/{n}`, `POST /transferts/{tid}/finaliser`, `GET /t/{jeton_public}/meta`, `GET /t/{jeton_public}/fichiers/{fid}/chiffre`, `GET /transferts` (gate `cle_api`), `POST /transferts/{tid}/revoquer` (gate `cle_api`), `POST /purge/executer` (gate `verifier_cle_horloge`), `GET /configuration`.

- [ ] **Step 1: Write the failing tests — append to `briques/transferts/test_api.py`**

```python
import os


def test_configuration_expose_la_taille_de_partie():
    r = c.get("/configuration")
    assert r.status_code == 200
    d = r.json()
    assert d["taille_partie_octets"] == int(os.environ["TAILLE_PARTIE_OCTETS"])


def test_creer_transfert_sans_cle_api_ouvert_en_dev():
    r = c.post("/transferts", json={"expiration_heures": 1})
    assert r.status_code == 200
    assert "jeton_upload" in r.json()


def test_parcours_complet_upload_finalisation_telechargement():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid, jeton_upload = creation["id"], creation["jeton_upload"]

    fichier = c.post(f"/transferts/{tid}/fichiers",
                      json={"nom": "x.bin", "type_mime": "application/octet-stream",
                            "taille_clair": 20, "taille_partie": 16},
                      headers={"X-Upload-Token": jeton_upload}).json()
    fid = fichier["id"]
    assert fichier["nb_parties"] == 2

    r0 = c.put(f"/transferts/{tid}/fichiers/{fid}/parties/0",
               content=b"A" * 44, headers={"X-Upload-Token": jeton_upload})
    assert r0.status_code == 200 and r0.json()["complet"] is False
    r1 = c.put(f"/transferts/{tid}/fichiers/{fid}/parties/1",
               content=b"B" * 32, headers={"X-Upload-Token": jeton_upload})
    assert r1.json()["complet"] is True

    fin = c.post(f"/transferts/{tid}/finaliser", headers={"X-Upload-Token": jeton_upload}).json()
    jeton_public = fin["jeton_public"]

    meta = c.get(f"/t/{jeton_public}/meta").json()
    assert meta["statut"] == "actif"
    assert meta["fichiers"][0]["nom"] == "x.bin"

    brut = c.get(f"/t/{jeton_public}/fichiers/{fid}/chiffre")
    assert brut.status_code == 200
    assert brut.content == b"A" * 44 + b"B" * 32
    assert brut.headers["content-type"] == "application/octet-stream"


def test_upload_partie_mauvais_jeton_refuse():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid = creation["id"]
    fichier = c.post(f"/transferts/{tid}/fichiers",
                      json={"nom": "x.bin", "type_mime": "application/octet-stream",
                            "taille_clair": 10, "taille_partie": 16},
                      headers={"X-Upload-Token": creation["jeton_upload"]}).json()
    r = c.put(f"/transferts/{tid}/fichiers/{fichier['id']}/parties/0",
              content=b"z" * 38, headers={"X-Upload-Token": "faux-jeton"})
    assert r.status_code == 403


def test_meta_transfert_inconnu_404():
    assert c.get("/t/nimporte-quoi/meta").status_code == 404


def test_lister_et_revoquer():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid = creation["id"]
    assert any(t["id"] == tid for t in c.get("/transferts").json())
    r = c.post(f"/transferts/{tid}/revoquer")
    assert r.status_code == 200
    assert not any(t["id"] == tid for t in c.get("/transferts").json())


def test_revoquer_transfert_inconnu_404():
    assert c.post("/transferts/nimporte-quoi/revoquer").status_code == 404


def test_purge_executer_sans_cle_horloge_ouvert_en_dev():
    r = c.post("/purge/executer")
    assert r.status_code == 200
    assert "purges" in r.json()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/transferts && python3 -m pytest test_api.py -v
```
Expected: FAIL — 404 sur toutes les nouvelles routes (elles n'existent pas encore).

- [ ] **Step 3: Modify `briques/transferts/main.py`** — fichier complet résultant :

```python
"""Brique « transferts » — transfert de gros fichiers chiffrés bout-en-bout (S196).

Le serveur ne voit JAMAIS le clair : chaque fichier est chiffré (AES-256-GCM)
dans le navigateur de l'expéditeur AVANT l'upload, la clé vit uniquement dans
le fragment `#` de l'URL de partage (jamais envoyée au serveur, cf.
docs/ENCRYPTION.md du dépôt suitenumerique/transfers, vendoring du design en
S196). Ce fichier ne contient donc AUCUNE ligne de crypto : c'est un simple
stockage de blobs opaques + métadonnées + expiration.

Deux niveaux d'auth (cf. plan S196 § Risques/Décisions) :
  • `cle_api` (API_KEYS) gate les routes de GESTION : créer/lister/révoquer.
  • Les routes d'upload de partie / finalisation / téléchargement PUBLIC ne
    sont PAS gatées par API_KEYS (motif briques/restaurant, accès par QR) :
    leur protection vient de jetons non devinables (`jeton_upload`,
    `jeton_public` + fragment de clé côté navigateur).
  • `verifier_cle_horloge` (TRANSFERTS_KEY) gate uniquement /purge/executer,
    appelée par core/horloge.py (même motif que briques/veille-info).
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

import stockage

app = FastAPI(title="Transferts — fichiers chiffrés bout-en-bout", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None),
            x_user_id: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS and presentee not in API_KEYS:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or "perso"


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /purge/executer : jeton partagé TRANSFERTS_KEY (motif verifier_cle_horloge
    de briques/veille-info) — fail-closed si TRANSFERTS_KEY est défini."""
    attendu = os.environ.get("TRANSFERTS_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


STATIC_DIR = Path(__file__).parent / "static"

TAILLE_PARTIE_OCTETS = int(os.getenv("TAILLE_PARTIE_OCTETS", str(16 * 1024 * 1024)))
TAILLE_MAX_OCTETS = int(os.getenv("TAILLE_MAX_OCTETS", str(20 * 1024 ** 3)))
EXPIRATION_MAX_HEURES = float(os.getenv("EXPIRATION_MAX_HEURES", "168"))
EXPIRATION_DEFAUT_HEURES = float(os.getenv("EXPIRATION_DEFAUT_HEURES", "72"))


class NouveauTransfert(BaseModel):
    expiration_heures: float = EXPIRATION_DEFAUT_HEURES


class NouveauFichier(BaseModel):
    nom: str
    type_mime: str = "application/octet-stream"
    taille_clair: int
    taille_partie: int


def _jeton_upload(x_upload_token: Optional[str] = Header(None)) -> str:
    if not x_upload_token:
        raise HTTPException(403, "En-tête X-Upload-Token manquant.")
    return x_upload_token


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True}


@app.get("/configuration", tags=["public"])
def configuration():
    return {
        "taille_partie_octets": TAILLE_PARTIE_OCTETS,
        "taille_max_octets": TAILLE_MAX_OCTETS,
        "expiration_max_heures": EXPIRATION_MAX_HEURES,
        "expiration_defaut_heures": EXPIRATION_DEFAUT_HEURES,
    }


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Cache-Control: no-cache pour qu'un nouveau déploiement du SW s'active dès
    # le prochain chargement de page (motif upstream, docs/ENCRYPTION.md § SW scope).
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.post("/transferts", tags=["gestion"])
def creer_transfert(body: NouveauTransfert, proprietaire: str = Depends(cle_api)):
    heures = min(body.expiration_heures, EXPIRATION_MAX_HEURES)
    if heures <= 0:
        heures = EXPIRATION_DEFAUT_HEURES
    return stockage.creer_transfert(proprietaire, heures)


@app.post("/transferts/{tid}/fichiers", tags=["upload"])
def ajouter_fichier(tid: str, body: NouveauFichier, jeton: str = Depends(_jeton_upload)):
    try:
        return stockage.ajouter_fichier(tid, jeton, body.nom, body.type_mime,
                                        body.taille_clair, body.taille_partie)
    except ValueError as e:
        code = 403 if "jeton" in str(e).lower() else 422
        raise HTTPException(code, str(e)) from e


@app.put("/transferts/{tid}/fichiers/{fid}/parties/{numero}", tags=["upload"])
async def ecrire_partie(tid: str, fid: str, numero: int, request: Request,
                        jeton: str = Depends(_jeton_upload)):
    donnees = await request.body()
    try:
        return stockage.ecrire_partie(tid, fid, jeton, numero, donnees)
    except ValueError as e:
        code = 403 if "jeton" in str(e).lower() else 422
        raise HTTPException(code, str(e)) from e


@app.post("/transferts/{tid}/finaliser", tags=["upload"])
def finaliser(tid: str, jeton: str = Depends(_jeton_upload)):
    try:
        return stockage.finaliser_transfert(tid, jeton)
    except ValueError as e:
        code = 403 if "jeton" in str(e).lower() else 422
        raise HTTPException(code, str(e)) from e


@app.get("/t/{jeton_public}/meta", tags=["public"])
def meta_publique(jeton_public: str):
    pub = stockage.lire_transfert_public(jeton_public)
    if pub is None:
        raise HTTPException(404, "Lien introuvable.")
    if pub["statut"] != "actif":
        raise HTTPException(410, f"Lien {pub['statut']}.")
    return pub


@app.get("/t/{jeton_public}/fichiers/{fid}/chiffre", tags=["public"], include_in_schema=False)
def telecharger_ciphertext(jeton_public: str, fid: str):
    pub = stockage.lire_transfert_public(jeton_public)
    if pub is None:
        raise HTTPException(404, "Lien introuvable.")
    if pub["statut"] != "actif":
        raise HTTPException(410, f"Lien {pub['statut']}.")
    chemin = stockage.chemin_ciphertext(pub["id"], fid).resolve()
    if not str(chemin).startswith(str(stockage.DIR.resolve())) or not chemin.is_file():
        raise HTTPException(404, "Fichier introuvable.")
    stockage.enregistrer_telechargement(pub["id"])

    def flux():
        with open(chemin, "rb") as f:
            while morceau := f.read(1024 * 1024):
                yield morceau

    return StreamingResponse(flux(), media_type="application/octet-stream")


@app.get("/transferts", tags=["gestion"])
def lister(proprietaire: str = Depends(cle_api)):
    return stockage.lister_transferts(proprietaire)


@app.post("/transferts/{tid}/revoquer", tags=["gestion"])
def revoquer_route(tid: str, proprietaire: str = Depends(cle_api)):
    if not stockage.revoquer(tid, proprietaire):
        raise HTTPException(404, "Transfert introuvable (ou pas le vôtre).")
    return {"revoque": True}


@app.post("/purge/executer", tags=["système"], dependencies=[Depends(verifier_cle_horloge)])
def purge():
    return {"purges": stockage.purger_expires()}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/transferts && python3 -m pytest -v
```
Expected: all tests in `test_api.py` + `test_stockage.py` pass (24 total). Note : `test_configuration_expose_la_taille_de_partie` et le parcours complet utilisent `TAILLE_PARTIE_OCTETS=16` fixé par `conftest.py` (Task 1) — cohérent avec les tailles de partie (16 octets) utilisées dans les tests d'upload.

- [ ] **Step 5: Commit**

```bash
git add briques/transferts/main.py briques/transferts/test_api.py
git commit -m "feat(transferts): endpoints upload/finalisation/téléchargement/gestion/purge (S196)"
```

---

### Task 5: `static/sw.js` + pages HTML (upload / téléchargement)

**Files:**
- Create: `briques/transferts/static/sw.js`
- Create: `briques/transferts/static/index.html`
- Create: `briques/transferts/static/telecharger.html`

**Interfaces:**
- Consumes: `static/chiffrement.js` (Task 3, importé par les DEUX pages HTML en `<script type="module">`) ; routes HTTP de Task 4 (`/transferts`, `/transferts/{tid}/fichiers`, `.../parties/{n}`, `.../finaliser`, `/t/{jeton}/meta`, `/t/{jeton}/fichiers/{fid}/chiffre`, `/configuration`).
- Produces: `static/sw.js` (Service Worker, scope `/`) — **non testable offline** (voir note ci-dessous), vérifié manuellement en Task 7.

> **Pourquoi `sw.js` n'a pas de test Node, alors que `chiffrement.js` en a** : `sw.js` tourne dans le scope `ServiceWorkerGlobalScope` (`self.addEventListener("install"/"activate"/"message"/"fetch")`, `self.clients.claim()`) — un scope qui n'existe qu'en navigateur, pas mockable raisonnablement sous Node. Son algorithme de déchiffrement en flux est une **duplication volontaire** de `creerFluxDechiffrement` (déjà testé à fond en Task 3, 8 tests incluant flux TCP-fragmenté et troncature) — **exactement le même motif que l'upstream** : `docs/ENCRYPTION.md` documente que `sw.js` et `encryption.ts` dupliquent l'algo indépendamment (« The constant `CRYPTO_OVERHEAD_PER_CHUNK = 28` appears verbatim on both sides »). La preuve que `sw.js` fonctionne réellement dans un navigateur se fait en Task 7 (régime de preuve Docker différé).

- [ ] **Step 1: Create `briques/transferts/static/sw.js`**

```javascript
// Service Worker de déchiffrement — intercepte /_dl/<jetonPublic>/<idFichier>
// et streame le clair directement vers le gestionnaire de téléchargement du
// navigateur (jamais de Blob, jamais tout le fichier en RAM).
//
// Duplique volontairement l'algorithme de déchiffrement en flux de
// chiffrement.js (déjà testé en Node, cf. static/chiffrement.test.mjs) : un
// Service Worker ne peut pas importer un module ES de façon universellement
// fiable sur tous les navigateurs cibles, donc on l'inline ici — même motif
// que sw.js/encryption.ts dans suitenumerique/transfers (docs/ENCRYPTION.md
// § What's ours vs what WebCrypto handles).
//
// Différence avec l'upstream : un seul hop réseau (pas de S3), on fetch
// directement notre propre endpoint /t/<jeton>/fichiers/<id>/chiffre, même
// origine — pas besoin du détour "backend renvoie une URL présignée S3 en
// JSON, puis fetch anonyme vers S3" qui existe chez eux pour contourner les
// particularités CORS/cookies d'un fetch cross-origin vers S3.

const IV_OCTETS = 12;
const SURCOUT = IV_OCTETS + 16;
const REGISTRE = new Map(); // jetonPublic -> { cle, fichiers: Map<id, meta> }

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || typeof data !== "object") return;
  if (data.type === "enregistrer-cle") {
    enregistrerCle(data)
      .then(() => event.source?.postMessage({ type: "enregistrer-cle-ok", jeton: data.jeton }))
      .catch((err) => event.source?.postMessage({
        type: "enregistrer-cle-erreur", jeton: data.jeton, message: String(err?.message || err),
      }));
  } else if (data.type === "oublier-cle") {
    REGISTRE.delete(data.jeton);
  }
});

async function enregistrerCle({ jeton, cleOctets, fichiers }) {
  if (!jeton || !(cleOctets instanceof Uint8Array) || !Array.isArray(fichiers)) {
    throw new Error("Message enregistrer-cle malformé.");
  }
  const cle = await crypto.subtle.importKey("raw", cleOctets, { name: "AES-GCM" }, false, ["decrypt"]);
  const fichierMap = new Map();
  for (const f of fichiers) {
    fichierMap.set(f.id, {
      taillePartie: f.taillePartie, tailleClair: f.tailleClair,
      nom: f.nom, typeMime: f.typeMime || "application/octet-stream",
    });
  }
  REGISTRE.set(jeton, { cle, fichiers: fichierMap });
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const m = url.pathname.match(/^\/_dl\/([^/]+)\/([^/]+)/);
  if (!m) return;
  event.respondWith(gererTelechargement(m[1], m[2]));
});

async function gererTelechargement(jeton, idFichier) {
  const entree = REGISTRE.get(jeton);
  if (!entree) {
    return new Response("Clé de déchiffrement non chargée. Rouvre le lien.", { status: 500 });
  }
  const meta = entree.fichiers.get(idFichier);
  if (!meta) return new Response("Fichier inconnu.", { status: 404 });

  const reponse = await fetch(`/t/${jeton}/fichiers/${idFichier}/chiffre`, { credentials: "omit" });
  if (!reponse.ok || !reponse.body) {
    return new Response("Échec de récupération du fichier chiffré.", { status: reponse.status || 502 });
  }

  const flux = reponse.body.pipeThrough(
    creerFluxDechiffrement(entree.cle, meta.taillePartie, meta.tailleClair, idFichier),
  );

  return new Response(flux, {
    headers: {
      "Content-Type": meta.typeMime,
      "Content-Length": String(meta.tailleClair),
      "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(meta.nom)}`,
      "Cache-Control": "no-store",
    },
  });
}

// Copie de chiffrement.js::creerFluxDechiffrement — voir la note en tête de
// fichier pour pourquoi cette duplication est assumée.
function creerFluxDechiffrement(cle, taillePartie, tailleClairTotale, idFichier) {
  const tailleChiffreePartie = taillePartie + SURCOUT;
  const encoder = new TextEncoder();
  const parties = tailleClairTotale <= 0 ? 1 : Math.ceil(tailleClairTotale / taillePartie);
  let enAttente = new Uint8Array(0);
  let clairRestant = tailleClairTotale;
  let numero = 0;

  function concat(a, b) {
    const bArr = b instanceof Uint8Array ? b : new Uint8Array(b);
    const out = new Uint8Array(a.length + bArr.length);
    out.set(a, 0); out.set(bArr, a.length);
    return out;
  }
  async function dechiffrerUne(ciphertext, aad) {
    const iv = ciphertext.subarray(0, IV_OCTETS);
    const corps = ciphertext.subarray(IV_OCTETS);
    return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: aad }, cle, corps));
  }

  return new TransformStream({
    async transform(morceau, controller) {
      enAttente = concat(enAttente, morceau);
      while (clairRestant > taillePartie && enAttente.length >= tailleChiffreePartie) {
        const ct = enAttente.subarray(0, tailleChiffreePartie);
        enAttente = enAttente.slice(tailleChiffreePartie);
        const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
        const clair = await dechiffrerUne(ct, aad);
        controller.enqueue(clair);
        clairRestant -= clair.length;
        numero += 1;
      }
    },
    async flush(controller) {
      const attendu = clairRestant + SURCOUT;
      if (enAttente.length !== attendu) {
        controller.error(new Error(`Flux tronqué (attendu ${attendu}, reçu ${enAttente.length}).`));
        return;
      }
      const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
      const clair = await dechiffrerUne(enAttente, aad);
      if (clair.length > 0) controller.enqueue(clair);
      clairRestant -= clair.length;
      if (clairRestant !== 0) controller.error(new Error(`Taille incohérente (résiduel ${clairRestant}).`));
    },
  });
}
```

- [ ] **Step 2: Create `briques/transferts/static/index.html`** (page d'envoi)

```html
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Transferts — envoyer un fichier</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>📦 Envoyer un fichier (chiffré bout-en-bout)</h1>
<p>Le fichier est chiffré dans <strong>ce navigateur</strong> avant l'envoi : le serveur ne voit jamais le contenu en clair.</p>
<input type="file" id="fichier">
<label>Expire dans (heures) : <input type="number" id="expiration" value="72" min="1" max="168"></label>
<button id="envoyer">Envoyer</button>
<progress id="progression" value="0" max="100" style="display:none"></progress>
<p id="resultat"></p>

<script type="module">
import * as Chiffrement from "/static/chiffrement.js";

const boutonEnvoyer = document.getElementById("envoyer");
const champFichier = document.getElementById("fichier");
const champExpiration = document.getElementById("expiration");
const barre = document.getElementById("progression");
const resultat = document.getElementById("resultat");

boutonEnvoyer.addEventListener("click", async () => {
  const fichier = champFichier.files[0];
  if (!fichier) { resultat.textContent = "Choisis un fichier d'abord."; return; }

  const config = await (await fetch("/configuration")).json();
  const taillePartie = config.taille_partie_octets;

  const { cleCrypto, fragment } = await Chiffrement.genererCle();

  const creation = await (await fetch("/transferts", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expiration_heures: Number(champExpiration.value) }),
  })).json();
  const { id: transfertId, jeton_upload: jetonUpload } = creation;

  const declaration = await (await fetch(`/transferts/${transfertId}/fichiers`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Upload-Token": jetonUpload },
    body: JSON.stringify({
      nom: fichier.name, type_mime: fichier.type || "application/octet-stream",
      taille_clair: fichier.size, taille_partie: taillePartie,
    }),
  })).json();
  const fichierId = declaration.id;
  const nbParties = declaration.nb_parties;

  barre.style.display = "block";
  for (let numero = 0; numero < nbParties; numero++) {
    const debut = numero * taillePartie;
    const fin = Math.min(debut + taillePartie, fichier.size);
    const morceauClair = new Uint8Array(await fichier.slice(debut, fin).arrayBuffer());
    const aad = Chiffrement.aadPourPartie(fichierId, numero, nbParties);
    const morceauChiffre = await Chiffrement.chiffrerPartie(cleCrypto, morceauClair, aad);
    await fetch(`/transferts/${transfertId}/fichiers/${fichierId}/parties/${numero}`, {
      method: "PUT", headers: { "X-Upload-Token": jetonUpload }, body: morceauChiffre,
    });
    barre.value = Math.round(((numero + 1) / nbParties) * 100);
  }

  const fin = await (await fetch(`/transferts/${transfertId}/finaliser`, {
    method: "POST", headers: { "X-Upload-Token": jetonUpload },
  })).json();

  const lien = `${location.origin}/t/${fin.jeton_public}#${fragment}`;
  resultat.innerHTML = `Lien (valable ${champExpiration.value} h) : <a href="${lien}">${lien}</a>`;
});
</script>
</body>
</html>
```

- [ ] **Step 3: Create `briques/transferts/static/telecharger.html`** (page de réception, servie pour toute route `/t/{jeton}`)

```html
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Transferts — télécharger</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>📦 Fichier(s) reçu(s)</h1>
<p id="etat">Préparation du déchiffrement…</p>
<ul id="liste"></ul>

<script type="module">
import * as Chiffrement from "/static/chiffrement.js";

const etat = document.getElementById("etat");
const liste = document.getElementById("liste");

async function main() {
  const jeton = location.pathname.split("/").filter(Boolean)[1]; // /t/<jeton>
  const fragment = location.hash.slice(1);
  if (!fragment) { etat.textContent = "Clé de déchiffrement absente du lien (fragment #manquant)."; return; }
  const cleCrypto = await Chiffrement.importerCle(fragment);

  const meta = await fetch(`/t/${jeton}/meta`);
  if (!meta.ok) { etat.textContent = meta.status === 410 ? "Ce lien a expiré." : "Lien introuvable."; return; }
  const donnees = await meta.json();

  if (!("serviceWorker" in navigator)) {
    etat.textContent = "Ton navigateur ne supporte pas les Service Workers (requis pour le déchiffrement en flux).";
    return;
  }
  const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;

  const cleOctets = Chiffrement.decoderBase64Url(fragment);
  await new Promise((resolve, reject) => {
    const cible = navigator.serviceWorker.controller || reg.active;
    const ecouteur = (event) => {
      if (event.data?.jeton !== jeton) return;
      navigator.serviceWorker.removeEventListener("message", ecouteur);
      event.data.type === "enregistrer-cle-ok" ? resolve() : reject(new Error(event.data.message));
    };
    navigator.serviceWorker.addEventListener("message", ecouteur);
    cible.postMessage({
      type: "enregistrer-cle", jeton, cleOctets,
      fichiers: donnees.fichiers.map((f) => ({
        id: f.id, taillePartie: f.taille_partie, tailleClair: f.taille_clair,
        nom: f.nom, typeMime: f.type_mime,
      })),
    });
  });

  // Retire la clé de la barre d'adresse une fois chargée en mémoire du SW.
  history.replaceState(null, "", location.pathname);

  etat.textContent = "Prêt à télécharger :";
  for (const f of donnees.fichiers) {
    const lien = document.createElement("a");
    lien.href = `/_dl/${jeton}/${f.id}/${encodeURIComponent(f.nom)}`;
    lien.textContent = `${f.nom} (${f.taille_clair} octets)`;
    lien.download = f.nom;
    const item = document.createElement("li");
    item.appendChild(lien);
    liste.appendChild(item);
  }
}

main().catch((e) => { etat.textContent = `Erreur : ${e.message}`; });
</script>
</body>
</html>
```

- [ ] **Step 4: Wire the two HTML routes in `briques/transferts/main.py`** — add after the `/sw.js` route:

```python
@app.get("/t/{jeton_public}", response_class=HTMLResponse, include_in_schema=False)
def page_telechargement(jeton_public: str):
    return FileResponse(STATIC_DIR / "telecharger.html")
```

- [ ] **Step 5: Add a route smoke test — append to `briques/transferts/test_api.py`**

```python
def test_page_upload_servie():
    r = c.get("/")
    assert r.status_code == 200 and "chiffré" in r.text.lower()


def test_page_telechargement_servie_pour_nimporte_quel_jeton():
    # La page se charge toujours (c'est le JS ensuite qui valide le jeton côté /meta) —
    # une route HTML statique ne doit pas dépendre de la validité du jeton en amont.
    r = c.get("/t/nimporte-quoi")
    assert r.status_code == 200 and "déchiffrement" in r.text.lower()


def test_sw_js_servi_avec_cache_control_no_cache():
    r = c.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
```

- [ ] **Step 6: Run the full test suite**

```bash
cd briques/transferts && python3 -m pytest -v && node --test static/chiffrement.test.mjs
```
Expected: all Python tests pass (27 total) + 8 Node tests pass.

- [ ] **Step 7: Commit**

```bash
git add briques/transferts/static briques/transferts/main.py briques/transferts/test_api.py
git commit -m "feat(transferts): Service Worker de déchiffrement + pages upload/téléchargement (S196)"
```

---

### Task 6: Câbler au Cœur — capacités, purge planifiée (horloge), launcher, docs

**Files:**
- Modify: `briques/transferts/manifest.json` (ajoute `capacites` + `taches`)
- Modify: `Lancer Workplace.command`
- Modify: `.env.example`

- [ ] **Step 1: Add `capacites` and `taches` to `briques/transferts/manifest.json`** — replace `"capacites": [],\n  "taches": []` with:

```json
  "capacites": [
    {
      "nom": "transferts_lister",
      "description": "Liste les transferts de fichiers actifs (nom pas exposé — seuls id, statut, date de création, échéance d'expiration et nombre de téléchargements, l'assistant ne voit JAMAIS le contenu ni la clé de déchiffrement). Utile pour répondre à « ai-je encore un lien de transfert actif ? » ou « quand expire mon transfert ? ».",
      "methode": "GET",
      "chemin": "/transferts",
      "params": {},
      "action": false,
      "niveau": 0
    },
    {
      "nom": "transferts_revoquer",
      "description": "Révoque immédiatement un transfert avant son expiration naturelle : supprime le fichier chiffré du disque et invalide le lien de partage. Irréversible : confirme=true requis.",
      "methode": "POST",
      "chemin": "/transferts/{tid}/revoquer",
      "params": {
        "tid": {
          "type": "string",
          "description": "Identifiant du transfert à révoquer (obtenu via transferts_lister).",
          "requis": true
        }
      },
      "action": true,
      "niveau": 0
    }
  ],
  "taches": [
    {
      "nom": "purge-transferts-expires",
      "description": "Supprime les fichiers chiffrés et les métadonnées des transferts expirés ou révoqués — purge le disque toutes les heures.",
      "methode": "POST",
      "chemin": "/purge/executer",
      "cadence_heures": 1,
      "idempotent": true,
      "entete_token_env": "TRANSFERTS_KEY",
      "tolere_echec": false
    }
  ],
```

- [ ] **Step 2: Re-run the smoke test to validate manifest, capacités and tâche are well-formed**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke
```
Expected: all pass, including `test_capacites_et_taches_bien_formees` for `transferts`.

- [ ] **Step 3: Add the launcher entry in `Lancer Workplace.command`**

Find the line `"export|$RACINE/briques/export|http://localhost:6150/sante"` and add immediately after it:

```
  "transferts|$RACINE/briques/transferts|http://localhost:6180/sante"
```

- [ ] **Step 4: Document `TRANSFERTS_KEY` and the shared `API_KEYS` scope in `.env.example`**

Find the comment block:
```
# Clés d'API acceptées par les briques autonomes (calcul, images, personnages,
# studio, transcription, video, vision, connexion, export) — CSV, en-tête X-API-Key.
```
Replace with:
```
# Clés d'API acceptées par les briques autonomes (calcul, images, personnages,
# studio, transcription, video, vision, connexion, export, transferts) — CSV, en-tête X-API-Key.
```

Then, near the other dedicated per-brique tokens (search for `VEILLE_INFO_KEY`), add:
```
# Jeton dédié horloge pour la brique transferts (purge des liens expirés,
# motif VEILLE_INFO_KEY) — SEUL core/horloge.py le détient.
TRANSFERTS_KEY=
```

- [ ] **Step 5: Run the full offline test suite one more time**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke \
  && cd briques/transferts && python3 -m pytest -v && node --test static/chiffrement.test.mjs
```
Expected: everything green (smoke + 27 pytest + 8 Node tests).

- [ ] **Step 6: Commit**

```bash
git add briques/transferts/manifest.json "Lancer Workplace.command" .env.example
git commit -m "$(cat <<'EOF'
feat(transferts): câble la brique au Cœur — capacités, purge horloge, launcher (S196)

transferts_lister/transferts_revoquer exposées au LLM (niveau 0 ;
revoquer en action:true car destructif) ; purge-transferts-expires
déclarée en taches, câblée sur core/horloge.py (motif veille-info) ;
TRANSFERTS_KEY documenté. Vendoring du design E2E de
suitenumerique/transfers (docs/ENCRYPTION.md), pas de fork Django —
voir arbitrage dans docs/superpowers/plans/2026-07-25-s196-*.md.
EOF
)"
```

---

### Task 7: Preuve Docker + navigateur bout-en-bout, self-review

**Files:** aucun fichier de code — étape de vérification uniquement.

- [ ] **Step 1: Build and start the brique**

```bash
cd briques/transferts
docker compose up -d --build
curl -s http://localhost:6180/sante
```
Expected: `{"ok": true}`.

- [ ] **Step 2: Roundtrip HTTP brut (sans navigateur) — confirme le protocole indépendamment du JS**

```bash
TID_JSON=$(curl -s -X POST http://localhost:6180/transferts -H "Content-Type: application/json" -d '{"expiration_heures": 1}')
echo "$TID_JSON"
# Récupère manuellement id + jeton_upload de la réponse ci-dessus, puis :
curl -s -X POST http://localhost:6180/transferts/<ID>/fichiers -H "Content-Type: application/json" \
  -H "X-Upload-Token: <JETON>" -d '{"nom":"x.bin","type_mime":"application/octet-stream","taille_clair":10,"taille_partie":16}'
# Récupère fichier id, puis une seule partie (10 octets clair + 28 = 38 octets, contenu arbitraire ici — un vrai chiffrement se ferait via chiffrement.js) :
curl -s -X PUT http://localhost:6180/transferts/<ID>/fichiers/<FID>/parties/0 \
  -H "X-Upload-Token: <JETON>" --data-binary "$(python3 -c 'print("A"*38, end="")')"
curl -s -X POST http://localhost:6180/transferts/<ID>/finaliser -H "X-Upload-Token: <JETON>"
# Récupère jeton_public, puis :
curl -s http://localhost:6180/t/<JETON_PUBLIC>/meta
curl -s http://localhost:6180/t/<JETON_PUBLIC>/fichiers/<FID>/chiffre | wc -c   # attend 38
```
Expected: chaque étape renvoie un JSON cohérent ; le dernier `curl | wc -c` confirme que les 38 octets bruts sont bien servis (le "chiffré" ici est un contenu factice — la vraie preuve crypto est faite en Node dans Task 3 et au navigateur ci-dessous).

- [ ] **Step 3: Preuve navigateur réelle (chiffrement WebCrypto de bout en bout)** — utiliser le skill `playwright-skill` ou une vérification manuelle :

1. Ouvrir `http://localhost:6180/` dans deux profils/onglets différents (ou un onglet normal + un onglet privé, pour bien séparer les Service Workers).
2. Onglet A : choisir un vrai fichier (quelques Mo), cliquer Envoyer. Attendre la barre de progression à 100 % puis récupérer le lien affiché (avec `#fragment`).
3. Copier ce lien dans l'onglet B, ouvrir. Vérifier : la page affiche "Prêt à télécharger", cliquer le lien du fichier.
4. **Vérifier dans les DevTools (Application → Service Workers)** que `/sw.js` est bien enregistré et actif.
5. **Vérifier dans l'onglet Network** que la requête vers `/t/<jeton>/fichiers/<id>/chiffre` renvoie des octets de taille `taille_clair + 28*nb_parties` (le ciphertext, PAS le clair) — c'est la preuve que ce que le serveur sert est bien opaque.
6. Ouvrir le fichier téléchargé : il doit être identique bit-à-bit au fichier original envoyé (comparer un hash `sha256sum` avant/après).
7. **Contre-épreuve confidentialité** : ouvrir un troisième onglet, aller sur `/t/<jeton_public>` **sans** le fragment `#...` (couper l'URL avant le `#`) → la page doit rester bloquée sur "Clé de déchiffrement absente du lien", jamais de téléchargement possible sans la clé.

Expected: fichier téléchargé identique à l'original (hash identique), aucune fuite de clé observable côté serveur (le `curl` de l'étape 2 et l'inspection réseau de l'étape 5 ne montrent que du binaire opaque).

- [ ] **Step 4: Preuve de la purge planifiée**

```bash
# Créer un transfert déjà expiré (expiration_heures négative accepté ? Non — la route
# clampe à EXPIRATION_DEFAUT_HEURES si <= 0, donc pour tester la purge sans attendre
# 72h, positionne EXPIRATION_DEFAUT_HEURES=0.001 temporairement dans le docker-compose,
# ou appelle directement l'endpoint de purge après avoir raccourci EXPIRATION_MAX_HEURES
# pour un test manuel, puis restaure les valeurs par défaut.
curl -s -X POST http://localhost:6180/purge/executer -H "Authorization: Bearer $TRANSFERTS_KEY"
```
Expected: `{"purges": N}` avec `N >= 0`, sans erreur 401 si `TRANSFERTS_KEY` est bien celui du `.env`.

- [ ] **Step 5: Vérifier la découverte par le Cœur**

```bash
# Cœur démarré (cf. GUIDE-ajouter-une-brique.md §5) :
curl -s http://localhost:5100/capacites | grep -i transferts
```
Expected: `transferts_lister` et `transferts_revoquer` apparaissent dans la liste.

- [ ] **Step 6: Self-Review**

- **Spec coverage** : chiffrement E2E navigateur (clé jamais côté serveur) → Tasks 3+5 ; Service Worker de déchiffrement en streaming → Task 5 ; upload en parties (mirrors S3 multipart, sans S3) → Tasks 2+4 ; stockage + expiration + purge planifiée → Tasks 2+6 (câblé sur `core/horloge.py`, pas de nouveau scheduler) ; capacités du Cœur → Task 6 ; tests TDD offline → Tasks 1-5 (27 tests pytest + 8 tests Node, tous exécutables sans Docker) ; arbitrage Option A/B documenté et justifié → tête de document.
- **Placeholder scan** : aucun TBD/TODO — chaque étape a du code littéral ou une commande exacte avec sortie attendue (Task 7 contient des `<ID>`/`<FID>`/`<JETON>` à substituer manuellement, c'est une procédure de vérification humaine, pas un placeholder de plan).
- **Type consistency** : `stockage.creer_transfert(proprietaire, expiration_heures)` (Task 2) ↔ appel dans `main.py::creer_transfert` (Task 4) ; `stockage.ajouter_fichier(transfert_id, jeton_upload, nom, type_mime, taille_clair, taille_partie)` (Task 2) ↔ `main.py::ajouter_fichier` (Task 4) ; `chiffrement.js::creerFluxDechiffrement(cle, taillePartie, tailleClairTotale, idFichier)` (Task 3) ↔ la copie inline dans `sw.js` (Task 5, mêmes noms de paramètres, documentée comme duplication volontaire) ; AAD `${idFichier}:${numero}:${parties}` identique dans `chiffrement.js`, `sw.js` et `stockage.py` (ce dernier ne la calcule pas — il ne fait que compter les parties, jamais de crypto côté serveur, cohérent avec l'arbitrage E2E).
- **Décisions non rouvertes** : mode "normal" (clé côté serveur) = absent, comme décidé ; MinIO/S3 = absent, comme décidé ; ClamAV/Drive/Keycloak dédié = absents, comme décidé (YAGNI documenté en tête de doc).
