# Standard vocal IVR + répondeur générique — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un appel SIP (softphone LAN pour l'instant) est décroché par un agent vocal
Python qui joue un menu à 7 options, écoute la touche pressée, puis — pour toutes les
options aujourd'hui — enregistre un message vocal, le transcrit, et notifie Telegram.

**Architecture:** Réutilise tel quel le stack SIP prouvé en S197
(`sip-stack/roomkit-visio/` : Kamailio + rtpengine + `livekit-sip:local`), promeut le
LiveKit+redis de test en instance **permanente** dédiée (toujours découplée d'Oria).
Une nouvelle brique `briques/standard-telephonique/` (port 6190) fournit deux
processus : une API FastAPI (lecture des messages reçus, capacité assistant) et un
worker `livekit-agents` qui rejoint automatiquement chaque appel entrant.

**Tech Stack:** Python 3.12, FastAPI, `livekit-agents==1.6.7`, `livekit==1.1.13`
(SDK `rtc`), SQLite (stdlib `sqlite3`), `httpx` pour appeler les briques `voix`
(5985), `transcription` (5980), `connexion` (5870) déjà existantes.

## Global Constraints

- Aucune modification d'`oria-stack/` — le LiveKit utilisé ici est dédié et permanent,
  jamais celui d'Oria (cf. design, section « Hors périmètre »).
- Aucun vrai numéro de téléphone (OVH/Twilio) — reste testé en LAN via softphone,
  comme en S197.
- Les 7 usages réels (rendez-vous, écoute réunion, etc.) restent hors périmètre —
  toutes les options du menu tombent sur le répondeur générique.
- Repli honnête partout : jamais de fausse transcription, jamais de notification
  Telegram si l'enregistrement est vide, jamais d'échec de transcription masqué.
- Conventions du monorepo à respecter : FastAPI + `X-API-Key` (`API_KEYS` env, CSV),
  CORS via `CORS_ORIGINS`, healthcheck `/sante`, `manifest.json` avec `capacites`,
  ports de brique choisis après vérification (6190 = premier libre après 6180).

---

## Fichiers touchés — vue d'ensemble

```
sip-stack/roomkit-visio/
  compose.override.yml                          MODIFIER (secrets permanents)
  docker/livekit-standalone/livekit.yaml         MODIFIER (nouvelle clé)
  .env                                            MODIFIER (non commité)

briques/standard-telephonique/                  CRÉER (nouvelle brique)
  manifest.json
  Dockerfile
  requirements.txt
  docker-compose.yml
  .gitignore
  conftest.py
  README.md
  menu.py                  — texte du menu, constantes
  messages_store.py        — persistance SQLite des messages reçus
  test_messages_store.py
  audio_util.py             — WAV ↔ rtc.AudioFrame
  test_audio_util.py
  voix_client.py            — appelle briques/voix (/synthetiser)
  test_voix_client.py
  transcription_client.py   — appelle briques/transcription (/transcrire)
  test_transcription_client.py
  notifier.py                — appelle briques/connexion (/pousser)
  test_notifier.py
  main.py                    — API FastAPI (capacité de lecture)
  test_api.py
  agent.py                   — worker livekit-agents (décroché, menu, enregistrement)
```

---

### Task 1 : Promouvoir le LiveKit+redis de test en instance permanente + dispatch rule individuelle

**Contexte :** le S197 a validé la mécanique avec un LiveKit+redis *jetables* (clé
`s197sipkey` en dur, dispatch rule `--direct` vers une room fixe `sip-test-s197`).
Cette tâche les remplace par une config permanente, et bascule vers une dispatch rule
`--individual` (une room différente par appel, préfixée `tel-`) puisque le vrai
répondeur doit gérer des appels concurrents sans collision.

**Fichiers :**
- Modifier : `sip-stack/roomkit-visio/docker/livekit-standalone/livekit.yaml`
- Modifier : `sip-stack/roomkit-visio/compose.override.yml`
- Modifier : `sip-stack/roomkit-visio/.env` (non commité)

**Interfaces :**
- Produit : un LiveKit joignable à `ws://livekit:7880` depuis le réseau Docker
  `roomkit-visio_default`, clé `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` (nouvelles
  valeurs, pas les valeurs de test S197) — consommé par `briques/standard-telephonique`
  (Task 6).

- [ ] **Étape 1 : générer une nouvelle clé/secret permanents (sur le HP)**

```bash
ssh debian@192.168.1.89 "openssl rand -hex 8 && openssl rand -base64 32"
```

Noter les deux valeurs générées — on les appellera `<NOUVELLE_CLE>` et
`<NOUVEAU_SECRET>` dans les étapes suivantes (remplacer par les vraies valeurs).

- [ ] **Étape 2 : mettre à jour `docker/livekit-standalone/livekit.yaml`**

```bash
ssh debian@192.168.1.89 "cd ~/workplace/sip-stack/roomkit-visio && sed -i 's/s197sipkey:.*/<NOUVELLE_CLE>: <NOUVEAU_SECRET>/' docker/livekit-standalone/livekit.yaml && cat docker/livekit-standalone/livekit.yaml"
```

Attendu : la ligne `keys:` ne contient plus que la nouvelle clé/secret.

- [ ] **Étape 3 : mettre à jour `compose.override.yml` (service `livekit-sip`)**

Remplacer dans `sip-stack/roomkit-visio/compose.override.yml` :
```yaml
    environment:
      LIVEKIT_API_KEY: s197sipkey
      LIVEKIT_API_SECRET: q2jCv9Vhq5fHdferu5Eq+D8Y/PXfPl079BfX3PMdjO8=
      LIVEKIT_WS_URL: ws://livekit:7880
```
par :
```yaml
    environment:
      LIVEKIT_API_KEY: <NOUVELLE_CLE>
      LIVEKIT_API_SECRET: <NOUVEAU_SECRET>
      LIVEKIT_WS_URL: ws://livekit:7880
```

- [ ] **Étape 4 : recréer les services avec la nouvelle clé**

```bash
ssh debian@192.168.1.89 "cd ~/workplace/sip-stack/roomkit-visio && docker compose -f compose.yml -f compose.override.yml up -d --force-recreate livekit livekit-sip && docker compose -f compose.yml -f compose.override.yml ps"
```
Attendu : `livekit` et `livekit-sip` `Up`.

- [ ] **Étape 5 : supprimer l'ancienne dispatch rule de test et en recréer une `--individual`**

```bash
ssh debian@192.168.1.89 "~/bin/lk sip dispatch list --url ws://192.168.1.89:7890 --api-key <NOUVELLE_CLE> --api-secret '<NOUVEAU_SECRET>'"
```
Noter l'ID retourné (`SDR_...`), puis :
```bash
ssh debian@192.168.1.89 "~/bin/lk sip dispatch delete SDR_Wu6LTRyfZt3a --url ws://192.168.1.89:7890 --api-key <NOUVELLE_CLE> --api-secret '<NOUVEAU_SECRET>'"
ssh debian@192.168.1.89 "~/bin/lk sip dispatch create --name standard-telephonique --trunks ST_2qr8kXf7ojXL --individual tel- --url ws://192.168.1.89:7890 --api-key <NOUVELLE_CLE> --api-secret '<NOUVEAU_SECRET>'"
```
Attendu : un nouvel ID `SDR_...` retourné, type dispatch = individual, préfixe `tel-`.

- [ ] **Étape 6 : mettre à jour `.env` (non commité, secret local)**

```bash
ssh debian@192.168.1.89 "cd ~/workplace/sip-stack/roomkit-visio && sed -i '/^LIVEKIT_API_KEY=/d;/^LIVEKIT_API_SECRET=/d' .env && printf 'LIVEKIT_API_KEY=<NOUVELLE_CLE>\nLIVEKIT_API_SECRET=<NOUVEAU_SECRET>\n' >> .env"
```

- [ ] **Étape 7 : commit (uniquement les 2 fichiers versionnés, pas `.env`)**

```bash
ssh debian@192.168.1.89 "cd ~/workplace && git add sip-stack/roomkit-visio/docker/livekit-standalone/livekit.yaml sip-stack/roomkit-visio/compose.override.yml && git status --short sip-stack/ && git commit -m 'chore(sip-stack): LiveKit permanent (secret dédié) + dispatch individuelle tel- (fondation standard-telephonique)'"
```

---

### Task 2 : Scaffold de la brique — manifest, Dockerfile, requirements, squelette API

**Fichiers :**
- Créer : `briques/standard-telephonique/manifest.json`
- Créer : `briques/standard-telephonique/Dockerfile`
- Créer : `briques/standard-telephonique/requirements.txt`
- Créer : `briques/standard-telephonique/.gitignore`
- Créer : `briques/standard-telephonique/conftest.py`
- Créer : `briques/standard-telephonique/main.py`
- Créer : `briques/standard-telephonique/test_api.py`

**Interfaces :**
- Produit : `app` (objet FastAPI) dans `main.py`, endpoint `GET /sante` — consommé par
  Task 8 (qui ajoute l'endpoint de lecture des messages sur ce même `app`).

- [ ] **Étape 1 : écrire `manifest.json`**

```json
{
  "nom": "standard-telephonique",
  "famille": "collaboration",
  "version": "0.1.0",
  "description": "Standard vocal téléphonique : un agent (livekit-agents) décroche les appels SIP entrants (pont sip-stack/roomkit-visio, S197), joue un menu à 7 options, et — le temps que chaque usage réel soit construit — enregistre un message vocal, le transcrit (briques/transcription) et notifie Telegram (briques/connexion). Fondation commune réutilisable par les usages futurs (rendez-vous, écoute réunion, support produit, journal vocal, rappel prospect, assistant collaborateurs, standard familial).",
  "role": "telephonie",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/standard-telephonique",
  "port": 6190,
  "url_sante": "http://host.docker.internal:6190/sante",
  "depends_on": [],
  "offre": [
    "repondeur_menu_vocal",
    "transcription_auto",
    "notification_telegram"
  ],
  "besoin": [],
  "taches": [],
  "capacites": [
    {
      "nom": "standard_telephonique_messages_lister",
      "description": "Liste les messages vocaux reçus au standard téléphonique (répondeur) : option du menu choisie, horodatage, durée, texte transcrit si disponible, lien vers l'audio. Lecture seule.",
      "methode": "GET",
      "chemin": "/messages",
      "params": {
        "limite": {
          "type": "integer",
          "description": "Nombre maximum de messages à renvoyer (défaut 20, les plus récents d'abord)."
        }
      },
      "action": false,
      "niveau": 1
    }
  ]
}
```

- [ ] **Étape 2 : écrire `requirements.txt`**

```
# Brique standard-telephonique — agent vocal SIP (livekit-agents) + API de lecture.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
livekit-agents==1.6.7
livekit==1.1.13
```

- [ ] **Étape 3 : écrire `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6190"]
```

- [ ] **Étape 4 : écrire `.gitignore`**

```
__pycache__/
.pytest_cache/
data/
```

- [ ] **Étape 5 : écrire `conftest.py`**

```python
"""Config de test : aucune clé API configurée → mode ouvert, déterministe."""
import os

os.environ["API_KEYS"] = ""
for _v in ("CONNEXION_URL", "CONNEXION_KEY", "VOIX_URL", "VOIX_KEY",
           "TRANSCRIPTION_URL", "TRANSCRIPTION_KEY", "MESSAGES_DB", "MESSAGES_DIR"):
    os.environ.pop(_v, None)
```

- [ ] **Étape 6 : écrire `main.py` (squelette — juste `/sante` pour l'instant)**

```python
"""Brique « standard-telephonique » — standard vocal IVR + répondeur générique.

API de lecture (capacité assistant `standard_telephonique_messages_lister`) branchée
sur le même stockage SQLite que l'agent `livekit-agents` (agent.py) qui décroche
réellement les appels — cf. manifest.json.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Standard téléphonique — IVR + répondeur", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


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
    return {"ok": True, "brique": "standard-telephonique"}
```

- [ ] **Étape 7 : écrire `test_api.py` (le seul test pour l'instant)**

```python
"""Tests API (TestClient) : santé."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["brique"] == "standard-telephonique"
```

- [ ] **Étape 8 : lancer les tests**

```bash
cd briques/standard-telephonique && python3 -m venv .venv-test && .venv-test/bin/pip install -q -r requirements.txt && .venv-test/bin/python -m pytest test_api.py -v
```
Attendu : `1 passed`.

- [ ] **Étape 9 : commit**

```bash
git add briques/standard-telephonique/manifest.json briques/standard-telephonique/requirements.txt \
        briques/standard-telephonique/Dockerfile briques/standard-telephonique/.gitignore \
        briques/standard-telephonique/conftest.py briques/standard-telephonique/main.py \
        briques/standard-telephonique/test_api.py
git commit -m "feat(standard-telephonique): scaffold brique — manifest, API /sante"
```

---

### Task 3 : `audio_util.py` — conversion WAV ↔ `rtc.AudioFrame`

**Fichiers :**
- Créer : `briques/standard-telephonique/audio_util.py`
- Créer : `briques/standard-telephonique/test_audio_util.py`

**Interfaces :**
- Produit :
  - `wav_bytes_to_audio_frames(wav_bytes: bytes, frame_ms: int = 20) -> tuple[int, int, list[rtc.AudioFrame]]`
    — retourne `(sample_rate, num_channels, frames)`, consommé par `agent.py` (Task 9)
    pour publier le menu/le bip.
  - `pcm_chunks_to_wav_bytes(chunks: list[bytes], sample_rate: int, num_channels: int) -> bytes`
    — consommé par `agent.py` (Task 9) pour sauvegarder l'enregistrement du répondeur.
- Consomme : `livekit.rtc.AudioFrame` (import direct — la construction d'un
  `AudioFrame` est une pure structure de données, aucune connexion réseau requise,
  vérifié dans `livekit-rtc/livekit/rtc/audio_frame.py`).

- [ ] **Étape 1 : écrire le test de conversion WAV → frames**

```python
"""Tests audio_util : conversion WAV ↔ rtc.AudioFrame, sans connexion réseau."""
import io
import wave

from livekit import rtc

import audio_util


def _wav_de_test(sample_rate: int = 22050, num_channels: int = 1, duree_s: float = 0.5) -> bytes:
    """Construit un WAV silencieux en mémoire pour les tests (pas de fichier disque)."""
    n_samples = int(sample_rate * duree_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_samples * num_channels)
    return buf.getvalue()


def test_wav_bytes_to_audio_frames_parametres_corrects():
    wav = _wav_de_test(sample_rate=22050, num_channels=1, duree_s=0.5)
    sample_rate, num_channels, frames = audio_util.wav_bytes_to_audio_frames(wav, frame_ms=20)
    assert sample_rate == 22050
    assert num_channels == 1
    assert len(frames) > 0
    assert all(isinstance(f, rtc.AudioFrame) for f in frames)


def test_wav_bytes_to_audio_frames_couvre_toute_la_duree():
    wav = _wav_de_test(sample_rate=16000, num_channels=1, duree_s=1.0)
    sample_rate, _, frames = audio_util.wav_bytes_to_audio_frames(wav, frame_ms=20)
    total_samples = sum(f.samples_per_channel for f in frames)
    # 1.0s à 16000Hz = 16000 échantillons — tolérance de +/- 1 frame (arrondi du dernier bloc)
    assert abs(total_samples - 16000) <= (0.020 * sample_rate)


def test_pcm_chunks_to_wav_bytes_roundtrip():
    wav = _wav_de_test(sample_rate=48000, num_channels=1, duree_s=0.2)
    sample_rate, num_channels, frames = audio_util.wav_bytes_to_audio_frames(wav, frame_ms=20)
    chunks = [bytes(f.data) for f in frames]
    rebuilt = audio_util.pcm_chunks_to_wav_bytes(chunks, sample_rate, num_channels)
    with wave.open(io.BytesIO(rebuilt), "rb") as w:
        assert w.getframerate() == sample_rate
        assert w.getnchannels() == num_channels
        assert w.getsampwidth() == 2
        assert w.getnframes() > 0
```

- [ ] **Étape 2 : lancer le test, vérifier qu'il échoue (module absent)**

```bash
cd briques/standard-telephonique && .venv-test/bin/python -m pytest test_audio_util.py -v
```
Attendu : `ModuleNotFoundError: No module named 'audio_util'`.

- [ ] **Étape 3 : ajouter `livekit` aux dépendances de test et installer**

```bash
.venv-test/bin/pip install -q livekit==1.1.13
```

- [ ] **Étape 4 : écrire `audio_util.py`**

```python
"""Conversion WAV ↔ rtc.AudioFrame — pure, sans connexion réseau LiveKit.

Le format audio interne de LiveKit est du PCM 16 bits signé entrelacé par canal
(cf. livekit.rtc.AudioFrame). On lit/écrit des fichiers WAV via le module stdlib
`wave`, qui utilise exactement ce même format — pas de dépendance supplémentaire.
"""
import io
import wave

from livekit import rtc


def wav_bytes_to_audio_frames(wav_bytes: bytes, frame_ms: int = 20) -> tuple[int, int, list[rtc.AudioFrame]]:
    """Découpe un WAV (mono ou stéréo, PCM 16 bits) en frames LiveKit de `frame_ms`
    millisecondes, prêtes à être poussées via `AudioSource.capture_frame`.

    Retourne (sample_rate, num_channels, frames) — sample_rate/num_channels sont ceux
    du fichier WAV lui-même (on ne suppose jamais un débit fixe : le moteur TTS peut
    changer de voix/modèle avec un débit différent)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sample_rate = w.getframerate()
        num_channels = w.getnchannels()
        assert w.getsampwidth() == 2, "seul le PCM 16 bits est supporté"
        pcm = w.readframes(w.getnframes())

    samples_per_frame = max(1, int(sample_rate * frame_ms / 1000))
    bytes_per_sample_all_channels = 2 * num_channels
    bloc_octets = samples_per_frame * bytes_per_sample_all_channels

    frames: list[rtc.AudioFrame] = []
    for debut in range(0, len(pcm), bloc_octets):
        bloc = pcm[debut:debut + bloc_octets]
        if not bloc:
            continue
        n_samples = len(bloc) // bytes_per_sample_all_channels
        if n_samples == 0:
            continue
        frames.append(rtc.AudioFrame(
            data=bloc,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=n_samples,
        ))
    return sample_rate, num_channels, frames


def pcm_chunks_to_wav_bytes(chunks: list[bytes], sample_rate: int, num_channels: int) -> bytes:
    """Concatène des morceaux de PCM 16 bits (ex. audio reçu d'un appelant) en un WAV
    complet. Utilisé pour sauvegarder l'enregistrement du répondeur."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"".join(chunks))
    return buf.getvalue()
```

- [ ] **Étape 5 : lancer les tests, vérifier qu'ils passent**

```bash
.venv-test/bin/python -m pytest test_audio_util.py -v
```
Attendu : `3 passed`.

- [ ] **Étape 6 : ajouter `livekit==1.1.13` à `requirements.txt` si pas déjà fait (déjà ajouté en Task 2), commit**

```bash
git add briques/standard-telephonique/audio_util.py briques/standard-telephonique/test_audio_util.py
git commit -m "feat(standard-telephonique): conversion WAV <-> rtc.AudioFrame (audio_util)"
```

---

### Task 4 : `voix_client.py` — appeler `briques/voix` pour synthétiser le menu

**Fichiers :**
- Créer : `briques/standard-telephonique/voix_client.py`
- Créer : `briques/standard-telephonique/test_voix_client.py`

**Interfaces :**
- Produit : `async def synthetiser(texte: str) -> bytes | None` — retourne les octets
  WAV, ou `None` si la brique voix est indisponible/en repli placeholder (repli
  honnête — jamais un faux audio). Consommé par `agent.py` (Task 9).
- Consomme : `httpx.AsyncClient`, env `VOIX_URL` (défaut
  `http://host.docker.internal:5985`), `VOIX_KEY` (optionnel, header `X-API-Key`).

- [ ] **Étape 1 : écrire le test avec `httpx.MockTransport`**

```python
"""Tests voix_client : appel HTTP vers briques/voix, mocké (aucun réseau réel)."""
import httpx
import pytest

import voix_client


@pytest.mark.asyncio
async def test_synthetiser_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/synthetiser"
        assert request.method == "POST"
        return httpx.Response(200, content=b"FAUX-WAV-OCTETS",
                              headers={"content-type": "audio/wav"})

    monkeypatch.setattr(voix_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://voix.test"))
    monkeypatch.setenv("VOIX_URL", "http://voix.test")

    audio = await voix_client.synthetiser("Bonjour")
    assert audio == b"FAUX-WAV-OCTETS"


@pytest.mark.asyncio
async def test_synthetiser_repli_honnete_si_placeholder(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"place_holder": True, "backend": "aucun"})

    monkeypatch.setattr(voix_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://voix.test"))
    monkeypatch.setenv("VOIX_URL", "http://voix.test")

    audio = await voix_client.synthetiser("Bonjour")
    assert audio is None


@pytest.mark.asyncio
async def test_synthetiser_repli_honnete_si_brique_injoignable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brique absente")

    monkeypatch.setattr(voix_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://voix.test"))
    monkeypatch.setenv("VOIX_URL", "http://voix.test")

    audio = await voix_client.synthetiser("Bonjour")
    assert audio is None
```

- [ ] **Étape 2 : installer `pytest-asyncio` pour le venv de test, lancer, vérifier l'échec**

```bash
.venv-test/bin/pip install -q pytest-asyncio
.venv-test/bin/python -m pytest test_voix_client.py -v
```
Attendu : `ModuleNotFoundError: No module named 'voix_client'`.

- [ ] **Étape 3 : ajouter `pytest-asyncio` à `requirements.txt`** (dépendance de test) —
  créer `requirements-test.txt` :

```
pytest==8.3.4
pytest-asyncio==0.25.2
```

- [ ] **Étape 4 : écrire `voix_client.py`**

```python
"""Client HTTP vers briques/voix (port 5985) — synthèse du menu/répondeur.

Repli honnête : si la brique est absente, injoignable, ou répond en mode placeholder
(aucun moteur TTS configuré), on retourne None — jamais un faux audio."""
import os

import httpx


def _client() -> httpx.AsyncClient:
    base = os.getenv("VOIX_URL", "http://host.docker.internal:5985").rstrip("/")
    return httpx.AsyncClient(base_url=base, timeout=20)


async def synthetiser(texte: str) -> bytes | None:
    """Texte → octets WAV via briques/voix. None si indisponible ou placeholder."""
    entetes = {}
    cle = os.getenv("VOIX_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    try:
        async with _client() as client:
            r = await client.post("/synthetiser", json={"texte": texte, "format": "wav"},
                                  headers=entetes)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    if r.headers.get("content-type", "").startswith("application/json"):
        return None  # placeholder honnête renvoyé en JSON, pas d'audio
    return r.content
```

- [ ] **Étape 5 : lancer les tests, vérifier qu'ils passent**

```bash
.venv-test/bin/pip install -q -r requirements-test.txt
.venv-test/bin/python -m pytest test_voix_client.py -v
```
Attendu : `3 passed`.

- [ ] **Étape 6 : commit**

```bash
git add briques/standard-telephonique/voix_client.py briques/standard-telephonique/test_voix_client.py \
        briques/standard-telephonique/requirements-test.txt
git commit -m "feat(standard-telephonique): client HTTP vers briques/voix (synthese menu)"
```

---

### Task 5 : `transcription_client.py` — appeler `briques/transcription`

**Fichiers :**
- Créer : `briques/standard-telephonique/transcription_client.py`
- Créer : `briques/standard-telephonique/test_transcription_client.py`

**Interfaces :**
- Produit : `async def transcrire(wav_bytes: bytes) -> str | None` — retourne le texte
  transcrit, ou `None` si indisponible/placeholder (repli honnête). Consommé par
  `agent.py` (Task 9).
- Consomme : `httpx.AsyncClient`, env `TRANSCRIPTION_URL` (défaut
  `http://host.docker.internal:5980`), `TRANSCRIPTION_KEY` (optionnel).

- [ ] **Étape 1 : écrire le test**

```python
"""Tests transcription_client : appel HTTP vers briques/transcription, mocké."""
import httpx
import pytest

import transcription_client


@pytest.mark.asyncio
async def test_transcrire_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcrire"
        return httpx.Response(200, json={"texte": "bonjour, ceci est un message",
                                        "place_holder": False})

    monkeypatch.setattr(transcription_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://transcription.test"))

    texte = await transcription_client.transcrire(b"faux-audio-wav")
    assert texte == "bonjour, ceci est un message"


@pytest.mark.asyncio
async def test_transcrire_repli_honnete_si_placeholder(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"texte": "", "place_holder": True})

    monkeypatch.setattr(transcription_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://transcription.test"))

    texte = await transcription_client.transcrire(b"faux-audio-wav")
    assert texte is None


@pytest.mark.asyncio
async def test_transcrire_repli_honnete_si_brique_injoignable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brique absente")

    monkeypatch.setattr(transcription_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://transcription.test"))

    texte = await transcription_client.transcrire(b"faux-audio-wav")
    assert texte is None
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
.venv-test/bin/python -m pytest test_transcription_client.py -v
```
Attendu : `ModuleNotFoundError: No module named 'transcription_client'`.

- [ ] **Étape 3 : écrire `transcription_client.py`**

```python
"""Client HTTP vers briques/transcription (port 5980) — transcription du message
vocal enregistré par le répondeur.

Repli honnête : indisponible/placeholder → None, jamais un faux texte."""
import os

import httpx


def _client() -> httpx.AsyncClient:
    base = os.getenv("TRANSCRIPTION_URL", "http://host.docker.internal:5980").rstrip("/")
    return httpx.AsyncClient(base_url=base, timeout=60)


async def transcrire(wav_bytes: bytes) -> str | None:
    """Audio WAV → texte via briques/transcription. None si indisponible/placeholder."""
    entetes = {}
    cle = os.getenv("TRANSCRIPTION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    try:
        async with _client() as client:
            r = await client.post("/transcrire",
                                  files={"fichier": ("message.wav", wav_bytes, "audio/wav")},
                                  headers=entetes)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("place_holder") or not data.get("texte"):
        return None
    return data["texte"]
```

- [ ] **Étape 4 : lancer les tests, vérifier qu'ils passent**

```bash
.venv-test/bin/python -m pytest test_transcription_client.py -v
```
Attendu : `3 passed`.

- [ ] **Étape 5 : commit**

```bash
git add briques/standard-telephonique/transcription_client.py briques/standard-telephonique/test_transcription_client.py
git commit -m "feat(standard-telephonique): client HTTP vers briques/transcription"
```

---

### Task 6 : `notifier.py` — appeler `briques/connexion` (`/pousser`, Telegram)

**Fichiers :**
- Créer : `briques/standard-telephonique/notifier.py`
- Créer : `briques/standard-telephonique/test_notifier.py`

**Interfaces :**
- Produit : `async def notifier(texte: str) -> None` — best-effort, ne lève jamais
  (motif copié de `core/proactif.py::_pousser_messagerie` et `briques/geo/main.py::_pousser_connexion`,
  déjà établi dans le monorepo). Consommé par `agent.py` (Task 9).
- Consomme : `httpx.AsyncClient`, env `CONNEXION_URL` (défaut
  `http://host.docker.internal:5870`), `CONNEXION_KEY` (optionnel),
  `STANDARD_TEL_NOTIF_UTILISATEUR` (défaut `"perso"`, même convention que
  `GEO_NOTIF_UTILISATEUR` dans `briques/geo/main.py`).

- [ ] **Étape 1 : écrire le test**

```python
"""Tests notifier : appel HTTP vers briques/connexion (/pousser), mocké."""
import httpx
import pytest

import notifier


@pytest.mark.asyncio
async def test_notifier_appelle_pousser_avec_le_bon_corps(monkeypatch):
    appels = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request)
        return httpx.Response(200, json={"ok": True, "envoyes": 1})

    monkeypatch.setattr(notifier, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://connexion.test"))
    monkeypatch.setenv("STANDARD_TEL_NOTIF_UTILISATEUR", "perso")

    await notifier.notifier("Nouveau message vocal (option 3) : bonjour...")

    assert len(appels) == 1
    assert appels[0].url.path == "/pousser"
    import json
    corps_envoye = json.loads(appels[0].content)
    assert corps_envoye["utilisateur"] == "perso"
    assert "option 3" in corps_envoye["texte"]


@pytest.mark.asyncio
async def test_notifier_ne_leve_jamais_si_brique_injoignable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brique absente")

    monkeypatch.setattr(notifier, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://connexion.test"))

    await notifier.notifier("texte")  # ne doit pas lever
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
.venv-test/bin/python -m pytest test_notifier.py -v
```
Attendu : `ModuleNotFoundError: No module named 'notifier'`.

- [ ] **Étape 3 : écrire `notifier.py`**

```python
"""Notification Telegram best-effort via briques/connexion (/pousser).

Motif copié de core/proactif.py::_pousser_messagerie et briques/geo/main.py::_pousser_connexion
(déjà établis dans le monorepo) : le pont /pousser résout LUI-MÊME les canaux liés de
l'utilisateur — best-effort, ne lève jamais."""
import logging
import os

import httpx

logger = logging.getLogger("standard-telephonique.notifier")


def _client() -> httpx.AsyncClient:
    base = os.getenv("CONNEXION_URL", "http://host.docker.internal:5870").rstrip("/")
    return httpx.AsyncClient(base_url=base, timeout=10)


async def notifier(texte: str) -> None:
    """Pousse `texte` vers les messageries liées de l'utilisateur. Ne lève jamais."""
    entetes = {}
    cle = os.getenv("CONNEXION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    utilisateur = os.getenv("STANDARD_TEL_NOTIF_UTILISATEUR", "perso")
    try:
        async with _client() as client:
            await client.post("/pousser", json={"utilisateur": utilisateur, "texte": texte},
                              headers=entetes)
    except httpx.HTTPError as ex:
        logger.warning("Notification standard-telephonique : %s", ex)
```

- [ ] **Étape 4 : lancer les tests, vérifier qu'ils passent**

```bash
.venv-test/bin/python -m pytest test_notifier.py -v
```
Attendu : `2 passed`.

- [ ] **Étape 5 : commit**

```bash
git add briques/standard-telephonique/notifier.py briques/standard-telephonique/test_notifier.py
git commit -m "feat(standard-telephonique): notification Telegram via briques/connexion (/pousser)"
```

---

### Task 7 : `messages_store.py` — persistance SQLite des messages reçus

**Fichiers :**
- Créer : `briques/standard-telephonique/messages_store.py`
- Créer : `briques/standard-telephonique/test_messages_store.py`

**Interfaces :**
- Produit :
  - `enregistrer(db_path: str, *, option: str | None, audio_path: str, duree_s: float, texte: str | None) -> int`
    (retourne l'id du message créé) — consommé par `agent.py` (Task 9).
  - `lister(db_path: str, limite: int = 20) -> list[dict]` (les plus récents d'abord)
    — consommé par `main.py` (Task 8).

- [ ] **Étape 1 : écrire le test**

```python
"""Tests messages_store : SQLite sur fichier temporaire, aucune dépendance externe."""
import tempfile
from pathlib import Path

import messages_store


def test_enregistrer_puis_lister():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "messages.db")

        id1 = messages_store.enregistrer(db_path, option="3", audio_path="/data/audio/a.wav",
                                         duree_s=12.5, texte="bonjour ceci est un test")
        id2 = messages_store.enregistrer(db_path, option=None, audio_path="/data/audio/b.wav",
                                         duree_s=4.0, texte=None)

        assert id1 != id2
        messages = messages_store.lister(db_path, limite=20)
        assert len(messages) == 2
        # le plus récent (id2) en premier
        assert messages[0]["id"] == id2
        assert messages[0]["option"] is None
        assert messages[0]["texte"] is None
        assert messages[1]["id"] == id1
        assert messages[1]["option"] == "3"
        assert messages[1]["texte"] == "bonjour ceci est un test"
        assert messages[1]["duree_s"] == 12.5


def test_lister_respecte_la_limite():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "messages.db")
        for i in range(5):
            messages_store.enregistrer(db_path, option=str(i), audio_path=f"/data/audio/{i}.wav",
                                       duree_s=1.0, texte=None)
        assert len(messages_store.lister(db_path, limite=3)) == 3


def test_lister_db_absente_renvoie_liste_vide():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "inexistant.db")
        assert messages_store.lister(db_path) == []
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
.venv-test/bin/python -m pytest test_messages_store.py -v
```
Attendu : `ModuleNotFoundError: No module named 'messages_store'`.

- [ ] **Étape 3 : écrire `messages_store.py`**

```python
"""Persistance SQLite des messages vocaux reçus par le répondeur (stdlib uniquement)."""
import sqlite3
from pathlib import Path


def _connexion(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option TEXT,
            audio_path TEXT NOT NULL,
            duree_s REAL NOT NULL,
            texte TEXT,
            horodatage TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    return conn


def enregistrer(db_path: str, *, option: str | None, audio_path: str, duree_s: float,
                texte: str | None) -> int:
    """Enregistre un message reçu, retourne son id."""
    conn = _connexion(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO messages (option, audio_path, duree_s, texte) VALUES (?, ?, ?, ?)",
            (option, audio_path, duree_s, texte),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def lister(db_path: str, limite: int = 20) -> list[dict]:
    """Liste les messages, les plus récents d'abord. Liste vide si la DB n'existe pas
    encore (repli honnête — pas une erreur, juste « aucun message pour l'instant »)."""
    if not Path(db_path).exists():
        return []
    conn = _connexion(db_path)
    try:
        rows = conn.execute(
            "SELECT id, option, audio_path, duree_s, texte, horodatage "
            "FROM messages ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [
            {
                "id": r[0], "option": r[1], "audio_path": r[2],
                "duree_s": r[3], "texte": r[4], "horodatage": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()
```

- [ ] **Étape 4 : lancer les tests, vérifier qu'ils passent**

```bash
.venv-test/bin/python -m pytest test_messages_store.py -v
```
Attendu : `3 passed`.

- [ ] **Étape 5 : commit**

```bash
git add briques/standard-telephonique/messages_store.py briques/standard-telephonique/test_messages_store.py
git commit -m "feat(standard-telephonique): persistance SQLite des messages recus"
```

---

### Task 8 : `main.py` — endpoint `GET /messages` (capacité assistant)

**Fichiers :**
- Modifier : `briques/standard-telephonique/main.py`
- Modifier : `briques/standard-telephonique/test_api.py`

**Interfaces :**
- Consomme : `messages_store.lister` (Task 7).
- Produit : `GET /messages` — implémente la capacité manifest
  `standard_telephonique_messages_lister` (Task 2).

- [ ] **Étape 1 : ajouter le test dans `test_api.py`**

```python
def test_messages_vide_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGES_DB", str(tmp_path / "messages.db"))
    r = client.get("/messages")
    assert r.status_code == 200
    assert r.json() == {"messages": []}


def test_messages_liste_apres_enregistrement(tmp_path, monkeypatch):
    db_path = str(tmp_path / "messages.db")
    monkeypatch.setenv("MESSAGES_DB", db_path)
    import messages_store
    messages_store.enregistrer(db_path, option="1", audio_path="/data/audio/x.wav",
                               duree_s=3.0, texte="allo")

    r = client.get("/messages")
    assert r.status_code == 200
    data = r.json()["messages"]
    assert len(data) == 1
    assert data[0]["option"] == "1"
    assert data[0]["texte"] == "allo"


def test_messages_respecte_limite(tmp_path, monkeypatch):
    db_path = str(tmp_path / "messages.db")
    monkeypatch.setenv("MESSAGES_DB", db_path)
    import messages_store
    for i in range(5):
        messages_store.enregistrer(db_path, option=str(i), audio_path=f"/data/audio/{i}.wav",
                                   duree_s=1.0, texte=None)

    r = client.get("/messages", params={"limite": 2})
    assert len(r.json()["messages"]) == 2
```

- [ ] **Étape 2 : lancer, vérifier l'échec (404 sur `/messages`)**

```bash
.venv-test/bin/python -m pytest test_api.py -v
```

- [ ] **Étape 3 : ajouter l'endpoint dans `main.py`**

Ajouter en haut du fichier :
```python
import messages_store
```
Ajouter à la fin du fichier :
```python
@app.get("/messages", tags=["messages"])
def messages(limite: int = 20, _cle: str = Depends(cle_api)):
    """Liste les messages vocaux reçus (les plus récents d'abord). Lecture seule."""
    db_path = os.getenv("MESSAGES_DB", "/data/messages.db")
    return {"messages": messages_store.lister(db_path, limite=limite)}
```

- [ ] **Étape 4 : lancer les tests, vérifier qu'ils passent**

```bash
.venv-test/bin/python -m pytest test_api.py -v
```
Attendu : `4 passed`.

- [ ] **Étape 5 : commit**

```bash
git add briques/standard-telephonique/main.py briques/standard-telephonique/test_api.py
git commit -m "feat(standard-telephonique): endpoint GET /messages (capacite assistant)"
```

---

### Task 9 : `menu.py` + `agent.py` — le worker qui décroche, joue le menu, enregistre

**Fichiers :**
- Créer : `briques/standard-telephonique/menu.py`
- Créer : `briques/standard-telephonique/agent.py`

**Interfaces :**
- Consomme : `audio_util.wav_bytes_to_audio_frames`, `audio_util.pcm_chunks_to_wav_bytes`
  (Task 3), `voix_client.synthetiser` (Task 4), `transcription_client.transcrire`
  (Task 5), `notifier.notifier` (Task 6), `messages_store.enregistrer` (Task 7).
- Produit : script exécutable `python agent.py start` (worker `livekit-agents`, aucune
  fonction publique consommée par d'autres tâches — c'est la dernière couche).

**Note sur les tests :** ce fichier orchestre une vraie connexion réseau temps réel
(room LiveKit, audio SIP) — comme pour le stack S197 lui-même, sa correction se
vérifie par un **test manuel de bout en bout** (Task 10), pas par des tests
automatisés. Chaque brique qu'il appelle (`audio_util`, `voix_client`,
`transcription_client`, `notifier`, `messages_store`) est, elle, entièrement testée en
isolation dans les tâches précédentes.

- [ ] **Étape 1 : écrire `menu.py` (texte du menu, aucune logique)**

```python
"""Texte du menu vocal — 7 options, une par usage envisagé (S197+). Toutes tombent
aujourd'hui sur le répondeur générique (aucun usage réel construit pour l'instant)."""

TEXTE_MENU = (
    "Bonjour. Tapez 1 pour la famille, 2 pour un rendez-vous, 3 pour une réunion, "
    "4 pour le support produit, 5 pour un journal vocal, 6 pour un rappel de prospect, "
    "ou 7 pour autre chose. Sinon, laissez un message après le bip."
)

TEXTE_BIP_INTRODUCTION = "Parlez après le bip. Raccrochez ou tapez dièse pour terminer."

DUREE_ATTENTE_DTMF_S = 8.0
DUREE_MAX_ENREGISTREMENT_S = 300.0
```

- [ ] **Étape 2 : écrire `agent.py`**

```python
"""Worker livekit-agents — décroche chaque appel SIP entrant (dispatch individuelle
`tel-*`, cf. Task 1), joue le menu, écoute la touche DTMF, enregistre un message
vocal (toutes les options tombent aujourd'hui sur le répondeur générique), le
transcrit, et notifie Telegram.

Dispatch automatique : aucun `agent_name` n'est fixé dans WorkerOptions, donc ce
worker rejoint AUTOMATIQUEMENT chaque nouvelle room du serveur LiveKit dédié
(cf. sip-stack/roomkit-visio/compose.override.yml — ce LiveKit n'est utilisé QUE par
ce chantier, l'auto-dispatch global est donc sans risque)."""
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from livekit import agents, rtc
from livekit.agents import JobContext, WorkerOptions, cli

import audio_util
import menu
import messages_store
import notifier
import transcription_client
import voix_client

logger = logging.getLogger("standard-telephonique.agent")
logging.basicConfig(level=logging.INFO)


async def _jouer_texte(room: rtc.Room, texte: str) -> None:
    """Synthétise `texte` (briques/voix) et le joue dans la room. Repli honnête : si
    la synthèse échoue, on ne joue rien plutôt que de faire planter l'appel."""
    wav = await voix_client.synthetiser(texte)
    if wav is None:
        logger.warning("Synthèse indisponible, menu non joué : %r", texte[:50])
        return

    sample_rate, num_channels, frames = audio_util.wav_bytes_to_audio_frames(wav)
    source = rtc.AudioSource(sample_rate=sample_rate, num_channels=num_channels)
    track = rtc.LocalAudioTrack.create_audio_track("menu", source)
    publication = await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    try:
        for frame in frames:
            await source.capture_frame(frame)
        await source.wait_for_playout()
    finally:
        await room.local_participant.unpublish_track(publication.sid)
        await source.aclose()


async def _attendre_choix(queue: "asyncio.Queue[str]", timeout_s: float) -> str | None:
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None


async def _enregistrer_message(track: rtc.Track, digit_queue: "asyncio.Queue[str]",
                               duree_max_s: float) -> tuple[bytes, int, int, float]:
    """Enregistre l'audio entrant jusqu'à `#`, raccroché, ou `duree_max_s` écoulées.
    Retourne (wav_bytes, sample_rate, num_channels, duree_s)."""
    sample_rate, num_channels = 48000, 1
    stream = rtc.AudioStream(track, sample_rate=sample_rate, num_channels=num_channels)
    chunks: list[bytes] = []
    debut = time.monotonic()

    async def _collecter() -> None:
        async for ev in stream:
            chunks.append(bytes(ev.frame.data))

    tache_collecte = asyncio.create_task(_collecter())

    async def _attendre_diese() -> None:
        while True:
            digit = await digit_queue.get()
            if digit == "#":
                return

    tache_arret = asyncio.create_task(_attendre_diese())
    try:
        await asyncio.wait(
            [tache_arret, asyncio.create_task(asyncio.sleep(duree_max_s))],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        tache_collecte.cancel()
        tache_arret.cancel()
        await stream.aclose()

    duree_s = time.monotonic() - debut
    wav = audio_util.pcm_chunks_to_wav_bytes(chunks, sample_rate, num_channels)
    return wav, sample_rate, num_channels, duree_s


async def _gerer_appel(ctx: JobContext) -> None:
    room = ctx.room
    digit_queue: "asyncio.Queue[str]" = asyncio.Queue()

    @room.on("sip_dtmf_received")
    def _on_dtmf(dtmf: rtc.SipDTMF) -> None:
        digit_queue.put_nowait(dtmf.digit)

    track_appelant: rtc.Track | None = None
    track_pret = asyncio.Event()

    @room.on("track_subscribed")
    def _on_track_subscribed(track: rtc.Track, publication, participant) -> None:
        nonlocal track_appelant
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP and \
                track.kind == rtc.TrackKind.KIND_AUDIO:
            track_appelant = track
            track_pret.set()

    participant = await ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
    logger.info("Participant SIP connecté : %s", participant.identity)

    await asyncio.wait_for(track_pret.wait(), timeout=10.0)

    # Menu, avec une répétition si aucune touche n'est pressée
    await _jouer_texte(room, menu.TEXTE_MENU)
    choix = await _attendre_choix(digit_queue, menu.DUREE_ATTENTE_DTMF_S)
    if choix is None:
        await _jouer_texte(room, menu.TEXTE_MENU)
        choix = await _attendre_choix(digit_queue, menu.DUREE_ATTENTE_DTMF_S)

    logger.info("Option choisie : %r", choix)

    # Toutes les options tombent aujourd'hui sur le répondeur générique.
    await _jouer_texte(room, menu.TEXTE_BIP_INTRODUCTION)
    wav, sample_rate, num_channels, duree_s = await _enregistrer_message(
        track_appelant, digit_queue, menu.DUREE_MAX_ENREGISTREMENT_S
    )

    if duree_s < 0.5:
        logger.info("Enregistrement vide (%.1fs), rien à faire.", duree_s)
        return

    messages_dir = Path(os.getenv("MESSAGES_DIR", "/data/audio"))
    messages_dir.mkdir(parents=True, exist_ok=True)
    audio_path = messages_dir / f"{uuid.uuid4()}.wav"
    audio_path.write_bytes(wav)

    texte = await transcription_client.transcrire(wav)

    db_path = os.getenv("MESSAGES_DB", "/data/messages.db")
    messages_store.enregistrer(db_path, option=choix, audio_path=str(audio_path),
                               duree_s=duree_s, texte=texte)

    resume = texte if texte else "(transcription indisponible)"
    option_txt = choix if choix else "aucune (délai dépassé)"
    await notifier.notifier(
        f"📞 Nouveau message vocal — option {option_txt} ({duree_s:.0f}s)\n{resume}"
    )


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Connexion à la room %s", ctx.room.name)
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    try:
        await _gerer_appel(ctx)
    except Exception:
        logger.exception("Erreur pendant la gestion de l'appel")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

- [ ] **Étape 3 : vérifier que le fichier s'importe sans erreur (pas de connexion réseau à cette étape)**

```bash
cd briques/standard-telephonique && .venv-test/bin/python -c "import agent"
```
Attendu : aucune erreur (juste l'import — `cli.run_app` n'est appelé que sous
`if __name__ == "__main__"`, donc l'import seul ne tente aucune connexion).

- [ ] **Étape 4 : commit**

```bash
git add briques/standard-telephonique/menu.py briques/standard-telephonique/agent.py
git commit -m "feat(standard-telephonique): agent livekit-agents (menu, DTMF, repondeur)"
```

---

### Task 10 : `docker-compose.yml` de la brique + test manuel de bout en bout

**Fichiers :**
- Créer : `briques/standard-telephonique/docker-compose.yml`
- Créer : `briques/standard-telephonique/README.md`

**Interfaces :**
- Consomme : le réseau Docker externe `roomkit-visio_default` (créé par
  `sip-stack/roomkit-visio/`, Task 1), les briques `voix`/`transcription`/`connexion`
  via `host.docker.internal` (déjà tournantes, aucune modification requise).

- [ ] **Étape 1 : écrire `docker-compose.yml`**

```yaml
services:
  standard-telephonique-api:
    build: .
    container_name: workplace_standard_telephonique_api
    image: workplace/standard-telephonique:0.1.0
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6190:6190"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - MESSAGES_DB=/data/messages.db
      - MESSAGES_DIR=/data/audio
    volumes:
      - standard_telephonique_data:/data
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6190"]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6190/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

  standard-telephonique-agent:
    build: .
    container_name: workplace_standard_telephonique_agent
    image: workplace/standard-telephonique:0.1.0
    env_file:
      - path: ../../.env
        required: false
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - MESSAGES_DB=/data/messages.db
      - MESSAGES_DIR=/data/audio
      - LIVEKIT_URL=ws://livekit:7880
      - LIVEKIT_API_KEY=${STANDARD_TEL_LIVEKIT_API_KEY}
      - LIVEKIT_API_SECRET=${STANDARD_TEL_LIVEKIT_API_SECRET}
    volumes:
      - standard_telephonique_data:/data
    command: ["python", "agent.py", "start"]
    networks:
      - default
      - roomkit_net
    restart: unless-stopped

networks:
  roomkit_net:
    external: true
    name: roomkit-visio_default

volumes:
  standard_telephonique_data:
```

- [ ] **Étape 2 : ajouter les secrets partagés au `.env` racine (non commité)**

Sur le HP, dans `~/workplace/.env` (racine, PAS `sip-stack/.env`), ajouter les
**mêmes valeurs** `<NOUVELLE_CLE>`/`<NOUVEAU_SECRET>` générées en Task 1 Étape 1 (deux
projets Docker Compose distincts, donc deux fichiers `.env` distincts à tenir à jour
avec la même valeur — documenté ici pour ne pas l'oublier) :

```bash
ssh debian@192.168.1.89 "cd ~/workplace && printf 'STANDARD_TEL_LIVEKIT_API_KEY=<NOUVELLE_CLE>\nSTANDARD_TEL_LIVEKIT_API_SECRET=<NOUVEAU_SECRET>\n' >> .env"
```

- [ ] **Étape 3 : écrire `README.md`**

```markdown
# standard-telephonique — standard vocal IVR + répondeur générique

Fondation téléphonique commune (S197+) : décroche les appels SIP entrants (via
`sip-stack/roomkit-visio/`), joue un menu à 7 options, enregistre un message vocal
(toutes les options tombent aujourd'hui sur le répondeur générique), le transcrit
(`briques/transcription`) et notifie Telegram (`briques/connexion`).

## Démarrer

Prérequis : `sip-stack/roomkit-visio/` déjà démarré (fournit le réseau Docker
`roomkit-visio_default` et le LiveKit dédié), `.env` racine avec
`STANDARD_TEL_LIVEKIT_API_KEY`/`_SECRET` (mêmes valeurs que
`sip-stack/roomkit-visio/.env`).

```bash
docker compose up -d --build
```

Deux services : `standard-telephonique-api` (port 6190, capacité assistant
`standard_telephonique_messages_lister`) et `standard-telephonique-agent` (worker
`livekit-agents`, rejoint automatiquement chaque appel — aucun port exposé).

## Hors périmètre (voir docs/superpowers/specs/2026-07-25-standard-vocal-ivr-repondeur-design.md)

Les 7 usages réels (rendez-vous, écoute réunion, etc.), le vrai numéro de téléphone
(OVH/Twilio), le branchement sur le LiveKit réel d'Oria.
```

- [ ] **Étape 4 : démarrer et vérifier les deux services**

```bash
ssh debian@192.168.1.89 "cd ~/workplace/briques/standard-telephonique && docker compose up -d --build && docker compose ps"
```
Attendu : `standard-telephonique-api` et `standard-telephonique-agent` `Up`.

- [ ] **Étape 5 : vérifier la santé de l'API**

```bash
ssh debian@192.168.1.89 "curl -s http://localhost:6190/sante"
```
Attendu : `{"ok": true, "brique": "standard-telephonique"}`.

- [ ] **Étape 6 : vérifier les logs de l'agent (dispatch OK, pas d'erreur de connexion)**

```bash
ssh debian@192.168.1.89 "cd ~/workplace/briques/standard-telephonique && docker compose logs standard-telephonique-agent --tail 30"
```
Attendu : logs de démarrage du worker `livekit-agents`, connexion au serveur
`ws://livekit:7880` réussie, aucune erreur `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`.

- [ ] **Étape 7 : test manuel de bout en bout (softphone LAN, comme en S197)**

1. Depuis Linphone (ou tout softphone LAN déjà configuré en S197), appeler `555`.
2. Vérifier que le menu vocal se joue (les 7 options + « laissez un message »).
3. Presser une touche (ex. `3`).
4. Après le bip, dire une phrase courte, puis raccrocher (ou taper `#`).
5. Vérifier la notification Telegram reçue, avec le texte transcrit et « option 3 ».
6. Vérifier l'entrée dans l'API :

```bash
curl -s http://192.168.1.89:6190/messages | python3 -m json.tool
```
Attendu : un message avec `"option": "3"`, `"duree_s"` proche de la durée réelle
parlée, `"texte"` correspondant à ce qui a été dit.

- [ ] **Étape 8 : commit**

```bash
git add briques/standard-telephonique/docker-compose.yml briques/standard-telephonique/README.md
git commit -m "feat(standard-telephonique): docker-compose (API + agent) + test bout-en-bout"
```

---

## Self-Review

- **Couverture design → plan** : menu 7 options (Task 9/menu.py), répondeur générique
  pour toutes les options (Task 9/`_gerer_appel`), transcription auto (Task 5),
  notification Telegram (Task 6), capacité de lecture manifest (Task 2/8), LiveKit+redis
  permanents découplés d'Oria (Task 1), test comme en S197 (Task 10) — chaque item du
  design a une tâche.
- **APIs LiveKit vérifiées, pas supposées** : chaque signature utilisée dans `agent.py`
  (`AudioSource`, `AudioFrame`, `LocalAudioTrack.create_audio_track`, `publish_track`,
  `unpublish_track`, `AudioStream`, `rtc.SipDTMF`, `rtc.ParticipantKind.PARTICIPANT_KIND_SIP`,
  `AutoSubscribe.AUDIO_ONLY`, `WorkerOptions`/`cli.run_app`, dispatch automatique sans
  `agent_name`) a été lue directement dans le code source de `livekit/python-sdks` et
  `livekit/agents` (pas de supposition non vérifiée) — sources consultées pendant la
  conception de ce plan.
- **Repli honnête cohérent** : `voix_client`, `transcription_client` renvoient `None`
  en cas d'échec/placeholder (jamais de faux contenu) ; `notifier` ne lève jamais
  (best-effort, motif déjà établi dans le monorepo) ; enregistrement vide (< 0.5s) ne
  déclenche ni transcription ni notification.
- **Deux fichiers `.env` à tenir en cohérence** (risque identifié explicitement dans
  Task 10 Étape 2) : `sip-stack/roomkit-visio/.env` et `.env` racine doivent porter la
  MÊME valeur de clé/secret LiveKit — deux projets Docker Compose distincts qui ne
  partagent pas nativement un `.env`.
