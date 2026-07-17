# S179 — Capacités asynchrones (Synopsis vidéo) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre les capacités asynchrones (202 + polling) génériques au Cœur et migrer Synopsis pour qu'une URL YouTube collée à l'assistant renvoie un résumé complet sans timeout 30 s.

**Architecture:** Le manifest déclare `async:true` + `poll_chemin` sur les capacités longues ; `catalogue.py` propage ces champs ; `outils_communs._appel_dynamique` détecte le `202` et poll `poll_chemin` avec son propre client HTTP (deadline `OUTILS_ASYNC_TIMEOUT=600s`). Côté brique, `lib/jobs.py` gère une table SQLite `/clips/jobs.db`, les 3 endpoints POST deviennent async (202 + `{job_id, statut:'en_cours', poll_url}`), `BackgroundTasks` exécute le pipeline en arrière-plan, `GET /jobs/{id}` rend l'état.

**Tech Stack:** Python 3.11, FastAPI, httpx, SQLite, pytest (TestClient), `respx` (mocks HTTP côté cœur), `youtube-transcript-api`.

**Spec :** `docs/superpowers/specs/2026-07-17-s179-capacites-async-synopsis-design.md` (commit `adc11d2`).

## Global Constraints

- Version Synopsis bumpée `1.1.0` → `1.2.0` (`briques/synopsis/main.py:30`, `briques/synopsis/docker-compose.yml:4`, `briques/synopsis/manifest.json:4`).
- DB jobs path : `/clips/jobs.db` (volume `synopsis_clips` existant — `briques/synopsis/docker-compose.yml:9`).
- Env Cœur nouveaux : `OUTILS_ASYNC_TIMEOUT=600`, `OUTILS_ASYNC_POLL=5`.
- Anti-régression : une capacité **synchrone** (sans `async:true`) continue à utiliser le client 30 s classique (`core/outils.py:447`) sans changement.
- Convention statut SQLite : `en_cours` | `termine` | `erreur` (calquée sur `audit/main.py:114` et `generateur/main.py:202`).
- HTTP : `POST /resumer` → `202` ; `GET /jobs/{id}` → `200` avec `statut` porteur de sens (pas de 500 sur job en erreur).
- Commentaires de code : **AUCUN** (convention repo).

---

## File Structure

### Créés
- `briques/synopsis/lib/jobs.py` — SQLite wrapper (init, creer_job, maj_statut, lire_job). ~80 lignes.

### Modifiés
- `briques/synopsis/main.py` — 3 endpoints POST `202 + job_id`, `GET /jobs/{id}`, 3 workers background, bump 1.2.0.
- `briques/synopsis/manifest.json` — `async:true` + `poll_chemin:"/jobs/{id}"` sur les 3 capacités, bump 1.2.0.
- `briques/synopsis/docker-compose.yml` — bump image `1.2.0`.
- `briques/synopsis/front.html` — JS `lancer` boucle `GET /jobs/{id}` + `progress_pct`.
- `briques/synopsis/test_synopsis.py` — 4 nouveaux tests async, ajustement des tests existants (200 → 202).
- `core/catalogue.py` — propage `async` + `poll_chemin` dans `collecter_capacites` (lignes 80-93).
- `core/outils_communs.py` — `_appel_dynamique` branche async + helper `_poll_async`.
- `core/test_outils_dynamiques.py` — 4 nouveaux tests async (avec `respx` ou stub `_Client`).

### Non touchés
- `core/outils.py` (le `AsyncClient(timeout=30)` reste — il sert aux caps sync ; le poll async ouvre son propre client).

---

## Task 1 : `lib/jobs.py` — wrapper SQLite

**Files:**
- Create: `briques/synopsis/lib/jobs.py`
- Test: `briques/synopsis/test_synopsis.py` (nouvelles fonctions de test en bas)

**Interfaces:**
- Produces:
  - `init_db() -> None` — idempotent, CREATE TABLE IF NOT EXISTS.
  - `creer_job(type: str, *, url: str | None = None, langue: str = "") -> str` — renvoie `id` (uuid4).
  - `maj_statut(job_id: str, statut: str, *, resultat: dict | None = None, erreur: str | None = None, progress_pct: int | None = None) -> None`
  - `lire_job(job_id: str) -> dict | None` — renvoie `{id, date_creation, type, url, langue, statut, progress_pct, resultat, erreur}` (où `resultat` est déjà dé-JSON-isé).

- [ ] **Step 1: Write the failing test**

Ajouter en bas de `briques/synopsis/test_synopsis.py` (avant `def test_front_servi`):

```python
# ── lib/jobs — persistance async (S179) ──────────────────────────────────────

import os as _os
import tempfile as _tempfile

def _avec_db_temp(monkeypatch, tmp_path):
    """Redirige JOBS_DB vers un fichier temporaire isolé du test."""
    db = tmp_path / "jobs.db"
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(db))
    _j.init_db()
    return _j


def test_jobs_creer_puis_lire(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    jid = j.creer_job("resumer", url="https://youtube.com/watch?v=abc", langue="Français")
    job = j.lire_job(jid)
    assert job["type"] == "resumer"
    assert job["url"] == "https://youtube.com/watch?v=abc"
    assert job["langue"] == "Français"
    assert job["statut"] == "en_cours"
    assert job["progress_pct"] == 0
    assert job["resultat"] is None and job["erreur"] is None


def test_jobs_maj_statut_termine_monkeypatch(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    jid = j.creer_job("resumer")
    j.maj_statut(jid, "termine", resultat={"titre": "T", "resume": "R"}, progress_pct=100)
    job = j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["progress_pct"] == 100
    assert job["resultat"] == {"titre": "T", "resume": "R"}


def test_jobs_maj_statut_erreur(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    jid = j.creer_job("reel")
    j.maj_statut(jid, "erreur", erreur="Whisper down")
    job = j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert job["erreur"] == "Whisper down"


def test_jobs_lire_job_inexistant_rend_none(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    assert j.lire_job("nexiste-pas") is None


def test_jobs_init_db_idempotent(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    j.init_db()  # ne lève pas
    jid = j.creer_job("resumer")
    assert j.lire_job(jid) is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py::test_jobs_creer_puis_lire -v
```
Expected: FAIL avec `ModuleNotFoundError: lib.jobs` (ou `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Create `briques/synopsis/lib/jobs.py`:

```python
"""Persistance des jobs asynchrones (S179) — SQLite dans le volume synopsis_clips.

Convention statut : 'en_cours' | 'termine' | 'erreur' (calque audit/generateur).
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

JOBS_DB = os.environ.get("JOBS_DB", "/clips/jobs.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  date_creation TEXT NOT NULL,
  type          TEXT NOT NULL,
  url           TEXT,
  langue        TEXT,
  statut        TEXT NOT NULL,
  progress_pct  INTEGER DEFAULT 0,
  resultat_json TEXT,
  erreur        TEXT
);
"""


def _connexion() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(JOBS_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(JOBS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connexion() as conn:
        conn.execute(_SCHEMA)
        conn.commit()


def creer_job(type: str, *, url: str | None = None, langue: str = "") -> str:
    jid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connexion() as conn:
        conn.execute(
            "INSERT INTO jobs (id, date_creation, type, url, langue, statut, progress_pct) "
            "VALUES (?,?,?,?,?,?,0)",
            (jid, now, type, url, langue or None, "en_cours"),
        )
        conn.commit()
    return jid


def maj_statut(job_id: str, statut: str, *, resultat: dict | None = None,
               erreur: str | None = None, progress_pct: int | None = None) -> None:
    champs = {"statut": statut, "date_maj": datetime.now(timezone.utc).isoformat()}
    if resultat is not None:
        champs["resultat_json"] = json.dumps(resultat, ensure_ascii=False)
    if erreur is not None:
        champs["erreur"] = erreur
    if progress_pct is not None:
        champs["progress_pct"] = int(progress_pct)
    sets = ", ".join(f"{k}=?" for k in champs)
    with _connexion() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*champs.values(), job_id))
        conn.commit()


def lire_job(job_id: str) -> dict | None:
    with _connexion() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("resultat_json"):
        try:
            d["resultat"] = json.loads(d["resultat_json"])
        except Exception:
            d["resultat"] = None
    else:
        d["resultat"] = None
    return d
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k jobs -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/lib/jobs.py briques/synopsis/test_synopsis.py
git commit -m "feat(s179): lib/jobs.py — persistance async SQLite"
```

---

## Task 2 : `GET /jobs/{id}` — endpoint de polling

**Files:**
- Modify: `briques/synopsis/main.py` (ajouter `from lib import jobs` + `@app.get("/jobs/{job_id}")`).
- Test: `briques/synopsis/test_synopsis.py`

**Interfaces:**
- Consumes: `lib.jobs.init_db`, `lib.jobs.lire_job` (Task 1).
- Produces: `GET /jobs/{job_id}` → `200 {statut, progress_pct?, erreur?, resultat?}` ou `404` si introuvable. Statut `erreur` → `200` avec `erreur` (pas de 500).

- [ ] **Step 1: Write the failing test**

Ajouter à `test_synopsis.py`:

```python
# ── GET /jobs/{id} — polling async (S179) ────────────────────────────────────

def test_jobs_endpoint_rend_un_job_en_cours(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer", url="https://youtube.com/watch?v=abc")
    r = client.get(f"/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "en_cours"
    assert data["progress_pct"] == 0
    assert "resultat" in data and data["resultat"] is None


def test_jobs_endpoint_rend_un_job_termine_avec_resultat(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer")
    _j.maj_statut(jid, "termine", resultat={"titre": "T", "resume": "R"}, progress_pct=100)
    r = client.get(f"/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "termine"
    assert data["progress_pct"] == 100
    assert data["resultat"]["titre"] == "T"


def test_jobs_endpoint_rend_une_erreur_en_200_pas_500(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer")
    _j.maj_statut(jid, "erreur", erreur="Vidéo inaccessible")
    r = client.get(f"/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "erreur"
    assert data["erreur"] == "Vidéo inaccessible"


def test_jobs_endpoint_404_si_inexistant():
    r = client.get("/jobs/nexiste-pas-uuid")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k "jobs_endpoint" -v
```
Expected: FAIL (404 sur tout — endpoint n'existe pas).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/synopsis/main.py`, ajouter en import après `from lib import transcribe_client, audio` (ligne 25):

```python
from lib import jobs as _jobs
```

Puis en bas du fichier, juste avant le bloc `if __name__ == "__main__":` (avant la ligne `import uvicorn`):

```python
@app.get("/jobs/{job_id}")
def job_etat(job_id: str):
    job = _jobs.lire_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} introuvable")
    return {
        "statut": job["statut"],
        "progress_pct": job.get("progress_pct") or 0,
        "resultat": job.get("resultat"),
        "erreur": job.get("erreur"),
    }
```

Ajouter aussi l'init au démarrage — juste après la définition de `app` (après ligne 33):

```python
try:
    _jobs.init_db()
    logger.info("Jobs DB prête (%s)", _jobs.JOBS_DB)
except Exception as _e:
    logger.warning("init_db jobs échoué : %s", _e)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k "jobs_endpoint" -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/main.py briques/synopsis/test_synopsis.py
git commit -m "feat(s179): GET /jobs/{id} — endpoint de polling"
```

---

## Task 3 : `POST /resumer` devient async (202)

**Files:**
- Modify: `briques/synopsis/main.py` (lignes 177-186 — remplace le handler `/resumer`).
- Test: `briques/synopsis/test_synopsis.py` (tests `test_resumer_*` à adapter + nouveaux tests async).

**Interfaces:**
- Consumes: `lib.jobs.creer_job`, `lib.jobs.maj_statut` (Task 1), `_summarize` (existant `main.py:118`), `FastAPI.BackgroundTasks`.
- Produces: `POST /resumer` → `202 {job_id, statut:"en_cours", poll_url}`. Worker `_pipeline_resumer`.

- [ ] **Step 1: Write the failing test**

Dans `test_synopsis.py`, **remplacer** le bloc `def test_resumer_structure():` par:

```python
def test_resumer_renvoie_202_avec_job_id(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=abc"})
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["statut"] == "en_cours"
    assert data["poll_url"].startswith("/jobs/")


def test_resumer_job_termine_apres_pipeline(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=abc"})
    jid = r.json()["job_id"]
    # BackgroundTasks du TestClient s'exécute APRES la réponse : le job est terminé.
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["titre"] == "Introduction à Python"
    assert "resume" in job["resultat"]


def test_resumer_job_erreur_sur_value_error(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with patch("main.get_youtube_transcript", side_effect=ValueError("Vidéo inaccessible")):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=bad"})
    assert r.status_code == 202  # le 202 est rendu AVANT que le background échoue
    jid = r.json()["job_id"]
    # BackgroundTasks exécuté par TestClient : on lit après.
    job = _j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert "Vidéo inaccessible" in (job["erreur"] or "")
```

Adapter aussi `test_auth_ouverte_sans_cles` (lignes 39-43) et `test_auth_ok_bonne_cle` (lignes 67-78) : remplacer `assert r.status_code == 200` par `assert r.status_code == 202`. Adapter `test_resumer_langue` (lignes 99-109) : remplace `assert r.status_code == 200` par `assert r.status_code == 202`. Adapter `test_resumer_erreur_transcript_400` (lignes 112-116) — supprimer ce test (le 400 synchrone n'existe plus ; le 202 + statut erreur le remplace, déjà couvert par `test_resumer_job_erreur_sur_value_error`). Supprimer aussi `test_resumer_url_media_delegue_transcription` et `test_est_youtube` devient `test_resumer_url_media_delegue_transcription`  → réécrire en variante async (checker 202 puis lire le job).

```python
def test_resumer_url_media_delegue_transcription(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    fake = {"transcript": [{"start": 0.0, "text": "Bonjour", "duration": 0.0}],
            "titre": "cours.mp4", "langue": "fr"}
    with (
        patch("main.transcribe_client.transcrire_url", return_value=fake) as mock_tr,
        patch("main.get_youtube_transcript") as mock_yt,
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://example.com/cours.mp4"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["titre"] == "cours.mp4"
    mock_tr.assert_called_once()
    mock_yt.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k "resumer" -v
```
Expected: FAIL avec `AssertionError: assert 200 != 202` (ou `KeyError 'job_id'`).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/synopsis/main.py`, **remplacer** le bloc `@app.post("/resumer")` (lignes 177-186) par:

```python
def _pipeline_resumer(job_id: str, url: str, langue: str, modele: str):
    try:
        _jobs.maj_statut(job_id, "en_cours", progress_pct=10)
        data = _summarize(url, langue, modele)
        _jobs.maj_statut(job_id, "termine", progress_pct=100, resultat=data)
    except Exception as e:
        logger.exception("pipeline_resumer job=%s", job_id)
        _jobs.maj_statut(job_id, "erreur", erreur=str(e))


@app.post("/resumer", status_code=202)
def resumer(req: ResumerRequest, background_tasks: BackgroundTasks,
            _cle: str = Depends(cle_api)):
    job_id = _jobs.creer_job("resumer", url=req.url, langue=req.langue)
    background_tasks.add_task(_pipeline_resumer, job_id, req.url, req.langue, req.modele)
    return {"job_id": job_id, "statut": "en_cours", "poll_url": f"/jobs/{job_id}"}
```

Ajouter l'import en haut (ligne 16, après les imports FastAPI existants):

```python
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, BackgroundTasks
```

(remplacer la ligne 16 existante qui importe `Depends, FastAPI, File, Form, Header, HTTPException, UploadFile`).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k "resumer or auth" -v
```
Expected: PASS (`test_resumer_*`, `test_auth_*`).

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/main.py briques/synopsis/test_synopsis.py
git commit -m "feat(s179): /resumer async (202 + BackgroundTasks + job_id)"
```

---

## Task 4 : `POST /reel` devient async

**Files:**
- Modify: `briques/synopsis/main.py` (bloc `/reel` lignes 207-219).
- Test: `briques/synopsis/test_synopsis.py`

**Interfaces:**
- Consumes: `_summarize` (existant), `_highlight_reel` (existant `main.py:140`), `lib.jobs.*`.
- Produces: `POST /reel` → `202 {job_id, statut:"en_cours", poll_url}`. Worker `_pipeline_reel`.

- [ ] **Step 1: Write the failing test**

Remplacer `test_reel_structure` (lignes 121-134) et `test_reel_erreur_transcript_400` (lignes 137-140) par:

```python
def test_reel_renvoie_202_avec_job_id(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    reel_result = {"reel_path": "/clips/test.mp4", "clip_count": 3, "vertical_path": None}
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
        patch("main._highlight_reel", return_value=reel_result),
    ):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=abc"})
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["statut"] == "en_cours"


def test_reel_job_termine_contient_reel_path_titre(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    reel_result = {"reel_path": "/clips/test.mp4", "clip_count": 3, "vertical_path": None}
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
        patch("main._highlight_reel", return_value=reel_result),
    ):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=abc"})
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["reel_path"] == "/clips/test.mp4"
    assert job["resultat"]["titre"] == "Introduction à Python"


def test_reel_job_erreur_sur_value_error(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with patch("main.get_youtube_transcript", side_effect=ValueError("Privée")):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=bad"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert "Privée" in (job["erreur"] or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k reel -v
```
Expected: FAIL `assert 200 != 202`.

- [ ] **Step 3: Write minimal implementation**

Dans `briques/synopsis/main.py`, **remplacer** le bloc `@app.post("/reel")` (lignes 207-219) par:

```python
def _pipeline_reel(job_id: str, req: ReelRequest):
    try:
        _jobs.maj_statut(job_id, "en_cours", progress_pct=10)
        summary = _summarize(req.url, "Français")
        _jobs.maj_statut(job_id, "en_cours", progress_pct=50)
        result = _highlight_reel(req.url, summary["resume"], req.duree_clip,
                                 req.sous_titres, req.narration, req.langue_narration,
                                 req.export_vertical)
        result["titre"] = summary["titre"]
        _jobs.maj_statut(job_id, "termine", progress_pct=100, resultat=result)
    except Exception as e:
        logger.exception("pipeline_reel job=%s", job_id)
        _jobs.maj_statut(job_id, "erreur", erreur=str(e))


@app.post("/reel", status_code=202)
def reel(req: ReelRequest, background_tasks: BackgroundTasks,
         _cle: str = Depends(cle_api)):
    job_id = _jobs.creer_job("reel", url=req.url)
    background_tasks.add_task(_pipeline_reel, job_id, req)
    return {"job_id": job_id, "statut": "en_cours", "poll_url": f"/jobs/{job_id}"}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k reel -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/main.py briques/synopsis/test_synopsis.py
git commit -m "feat(s179): /reel async (202 + BackgroundTasks + job_id)"
```

---

## Task 5 : `POST /resumer-fichier` devient async

**Files:**
- Modify: `briques/synopsis/main.py` (bloc `/resumer-fichier` lignes 189-204).
- Test: `briques/synopsis/test_synopsis.py`

**Interfaces:**
- Consumes: `audio.extraire_audio`, `transcribe_client.transcrire_fichier`, `_run_pipeline`, `lib.jobs.*`.
- Produces: `POST /resumer-fichier` → `202 {job_id, statut:"en_cours", poll_url}`. Worker `_pipeline_fichier` qui lit le fichier temporaire `/clips/uploads/{job_id}`.

- [ ] **Step 1: Write the failing test**

Remplacer `test_resumer_fichier_ok` (lignes 171-188), `test_resumer_fichier_vide_422` (lignes 191-194), `test_resumer_fichier_sans_moteur_400` (lignes 197-205) par:

```python
def test_resumer_fichier_renvoie_202_avec_job_id(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    fake = {"transcript": [{"start": 0.0, "text": "Salut", "duration": 0.0}],
            "titre": "ma-video", "langue": "fr"}
    with (
        patch("main.audio.extraire_audio", return_value=b"RIFFfakewav") as mock_audio,
        patch("main.transcribe_client.transcrire_fichier", return_value=fake) as mock_tr,
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer-fichier",
                        files={"fichier": ("ma-video.mp4", b"\x00\x01videodata", "video/mp4")},
                        data={"langue": "Français"})
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["statut"] == "en_cours"
    jid = data["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["titre"] == "ma-video"
    mock_audio.assert_called_once()
    mock_tr.assert_called_once()


def test_resumer_fichier_vide_422():
    r = client.post("/resumer-fichier",
                    files={"fichier": ("vide.mp4", b"", "video/mp4")})
    assert r.status_code == 422


def test_resumer_fichier_job_erreur_sur_value_error(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with patch("main.audio.extraire_audio", return_value=b"wav"), \
         patch("main.transcribe_client.transcrire_fichier",
               side_effect=ValueError("aucun moteur de transcription configuré")):
        r = client.post("/resumer-fichier",
                        files={"fichier": ("v.mp4", b"data", "video/mp4")})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert "moteur" in (job["erreur"] or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k "fichier" -v
```
Expected: FAIL (`assert 200 != 202`).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/synopsis/main.py`, **remplacer** le bloc `@app.post("/resumer-fichier")` (lignes 189-204) par:

```python
def _pipeline_fichier(job_id: str, fichier_path: str, nom: str, langue: str, modele: str):
    try:
        _jobs.maj_statut(job_id, "en_cours", progress_pct=10)
        contenu = Path(fichier_path).read_bytes()
        data = _summarize_fichier(contenu, nom, langue, modele)
        _jobs.maj_statut(job_id, "termine", progress_pct=100, resultat=data)
    except Exception as e:
        logger.exception("pipeline_fichier job=%s", job_id)
        _jobs.maj_statut(job_id, "erreur", erreur=str(e))
    finally:
        try:
            Path(fichier_path).unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/resumer-fichier", status_code=202)
async def resumer_fichier(fichier: UploadFile = File(...),
                          langue: str = Form("Français"),
                          modele: str = Form(""),
                          background_tasks: BackgroundTasks = BackgroundTasks(),
                          _cle: str = Depends(cle_api)):
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(422, "Fichier vide.")
    job_id = _jobs.creer_job("resumer_fichier", langue=langue)
    upload_dir = Path("/clips/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    fichier_path = str(upload_dir / job_id)
    Path(fichier_path).write_bytes(contenu)
    background_tasks.add_task(_pipeline_fichier, job_id, fichier_path,
                              fichier.filename or "media", langue, modele)
    return {"job_id": job_id, "statut": "en_cours", "poll_url": f"/jobs/{job_id}"}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd briques/synopsis && python -m pytest test_synopsis.py -k "fichier" -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/main.py briques/synopsis/test_synopsis.py
git commit -m "feat(s179): /resumer-fichier async (202 + fichier temporaire)"
```

---

## Task 6 : Manifest + docker-compose — `async:true` + bump 1.2.0

**Files:**
- Modify: `briques/synopsis/manifest.json`
- Modify: `briques/synopsis/docker-compose.yml`
- Test: visuel (relire le JSON) + test Cœur Task 8 qui validera la propagation.

**Interfaces:**
- Produces: le manifest déclare `async:true` + `poll_chemin:"/jobs/{id}"` sur les 3 capacités, version `1.2.0`. `core/catalogue.collecter_capacites` doit ensuite propager ces champs (Task 7).

- [ ] **Step 1: écrire le test de validation du manifest (un simple sanity check)**

Pas de test spécifique ici (la propagation est testée côté Cœur Task 7). On validera visuellement.

- [ ] **Step 2: Modify `briques/synopsis/manifest.json`**

Remplacer le contenu par (changement version `1.1.0`→`1.2.0`, ajout `"async": true` et `"poll_chemin": "/jobs/{id}"` à chaque capacité):

```json
{
  "nom": "synopsis",
  "famille": "media",
  "version": "1.2.0",
  "description": "Résumé de N'IMPORTE QUELLE vidéo par IA (YouTube, lien direct, ou fichier uploadé) — transcription, synthèse LLM, chapitrage automatique, points clés, highlight reels. Capacités asynchrones (202 + polling /jobs/{id}).",
  "role": "video",
  "couche": "backend",
  "statut": "actif",
  "chemin_source": "briques/synopsis",
  "port": 6090,
  "url_sante": "http://host.docker.internal:6090/sante",
  "depends_on": [
    "gateway",
    "transcription"
  ],
  "capacites": [
    {
      "nom": "video_resumer",
      "description": "Résume une vidéo à partir d'une URL : YouTube (transcript natif) OU lien direct vers un média (délégué à la transcription Whisper). Produit un résumé structuré avec chapitres temporels et points clés. Asynchrone : POST renvoie 202 + job_id, poller GET /jobs/{id} jusqu'à statut=termine.",
      "methode": "POST",
      "chemin": "/resumer",
      "async": true,
      "poll_chemin": "/jobs/{id}",
      "params": {
        "url": {
          "type": "string",
          "description": "URL de la vidéo (YouTube ou lien direct vers un fichier média)",
          "requis": true
        },
        "langue": {
          "type": "string",
          "description": "Langue du résumé (Français, English, Español, Deutsch, Português, Italiano)",
          "enum": [
            "Français",
            "English",
            "Español",
            "Deutsch",
            "Português",
            "Italiano"
          ]
        }
      },
      "action": false
    },
    {
      "nom": "youtube_reel",
      "description": "Crée un highlight reel vidéo à partir des moments clés identifiés dans un résumé YouTube. Télécharge la vidéo, extrait les clips par chapitre, les assemble avec sous-titres et narration TTS optionnelle. Asynchrone (202 + poll).",
      "methode": "POST",
      "chemin": "/reel",
      "async": true,
      "poll_chemin": "/jobs/{id}",
      "params": {
        "url": {
          "type": "string",
          "description": "URL de la vidéo YouTube",
          "requis": true
        },
        "duree_clip": {
          "type": "integer",
          "description": "Durée en secondes de chaque clip extrait (défaut 45)"
        },
        "sous_titres": {
          "type": "boolean",
          "description": "Incruster les titres des chapitres comme sous-titres (défaut true)"
        },
        "narration": {
          "type": "boolean",
          "description": "Ajouter une narration TTS au montage (défaut false)"
        },
        "export_vertical": {
          "type": "string",
          "description": "Mode d'export vertical (blur, crop, pad — vide = pas d'export)",
          "enum": [
            "blur",
            "crop",
            "pad",
            ""
          ]
        }
      },
      "action": true
    }
  ],
  "taches": []
}
```

Note: `/resumer-fichier` n'est pas exposé comme capacité (c'est l'upload direct via le front, pas un tool du LLM) — on ne le déclare pas. Seules les 2 caps `video_resumer` et `youtube_reel` déclarent `async:true`.

- [ ] **Step 3: Modify `briques/synopsis/docker-compose.yml`**

Changer la ligne 4: `image: workplace/synopsis:1.1.0` → `image: workplace/synopsis:1.2.0`.

- [ ] **Step 4: Sanity check**

```bash
cd briques/synopsis && python -c "import json; m=json.load(open('manifest.json')); print(m['version']); print([c['nom'] for c in m['capacites']]); print(all(c.get('async') for c in m['capacites']))"
```
Expected: `1.2.0\n['video_resumer', 'youtube_reel']\nTrue`.

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/manifest.json briques/synopsis/docker-compose.yml
git commit -m "feat(s179): manifest async:true + poll_chemin + bump 1.2.0"
```

---

## Task 7 : `core/catalogue.py` — propager `async` + `poll_chemin`

**Files:**
- Modify: `core/catalogue.py` (lignes 80-93 — bloc `capacites.append({...})`).
- Test: `core/test_catalogue.py` (nouveau test).

**Interfaces:**
- Consumes: déclaration manifest `capacites` (champs `async`, `poll_chemin`).
- Produces: entrée catalogue contient `"async": bool` et `"poll_chemin": str | None` pour consommation par `outils_communs._appel_dynamique` (Task 8).

- [ ] **Step 1: Write the failing test**

Dans `core/test_catalogue.py`, ajouter:

```python
def test_capacite_async_propage_async_et_poll_chemin():
    reg = _Registre({
        "synopsis": {"nom": "synopsis", "port": 6090, "capacites": [
            {"nom": "video_resumer", "methode": "POST", "chemin": "/resumer",
             "description": "resumer", "params": {},
             "async": True, "poll_chemin": "/jobs/{id}"},
            {"nom": "video_sync", "methode": "GET", "chemin": "/sync", "params": {}},
        ]},
    })
    cap = {c["nom"]: c for c in catalogue.collecter_capacites(reg)}
    assert cap["video_resumer"]["async"] is True
    assert cap["video_resumer"]["poll_chemin"] == "/jobs/{id}"
    assert cap["video_sync"]["async"] is False
    assert cap["video_sync"]["poll_chemin"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd core && python -m pytest test_catalogue.py::test_capacite_async_propage_async_et_poll_chemin -v
```
Expected: FAIL (`KeyError: 'async'` ou `assert None is True`).

- [ ] **Step 3: Write minimal implementation**

Dans `core/catalogue.py`, modifier le bloc `capacites.append({...})` (lignes 80-93) — ajouter deux champs avant la ligne `"socle"`:

```python
            capacites.append({
                "nom": decl["nom"],
                "brique": nom_brique,
                "description": decl.get("description", ""),
                "methode": (decl.get("methode") or "GET").upper(),
                "chemin": chemin,
                "url": base + chemin,
                "params": dict(decl.get("params") or {}),
                "action": bool(decl.get("action", False)),
                "niveau": _niveau(decl.get("niveau")),
                "socle": bool(decl.get("socle", False)),
                "async": bool(decl.get("async", False)),
                "poll_chemin": decl.get("poll_chemin"),
            })
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd core && python -m pytest test_catalogue.py -v
```
Expected: PASS (tous les tests, y compris le nouveau).

- [ ] **Step 5: Commit**

```bash
git add core/catalogue.py core/test_catalogue.py
git commit -m "feat(s179): catalogue propage async + poll_chemin"
```

---

## Task 8 : `outils_communs._appel_dynamique` — branche async (poll)

**Files:**
- Modify: `core/outils_communs.py` (fonction `_appel_dynamique`, lignes 75-109).
- Test: `core/test_outils_dynamiques.py` (4 nouveaux tests).

**Interfaces:**
- Consumes: `cap["async"]`, `cap["poll_chemin"]` (Task 7), `cap["url"]`, `_entetes_brique` (existant).
- Produces: `_appel_dynamique` détecte `202` sur une cap async, ouvre son propre `httpx.AsyncClient(timeout=None)`, boucle GET sur la `poll_url` (substituée), rend `json.dumps(data.get("resultat") or data)` ou `{"ok": False, "message":..., "job_id":...}`.

- [ ] **Step 1: Write the failing test**

En bas de `core/test_outils_dynamiques.py`, avant `if __name__ == "__main__":`, ajouter:

```python
# ── Capacités async (S179) — 202 + polling ──────────────────────────────────

class _ClientAsync:
    """Client stub qui répond :
       - sur POST /resumer -> 202 {job_id, statut:'en_cours'}
       - sur GET /jobs/{id} -> enfile les réponses préchargées dans self.polls.
    """
    def __init__(self, post_resp, polls):
        self.post_resp = post_resp
        self.polls = list(polls)
        self.poll_calls = 0
        self.dernier = {}

    async def request(self, methode, url, json=None, params=None, headers=None, timeout=None):
        self.dernier = {"methode": methode, "url": url}
        if methode == "POST":
            return self.post_resp
        # GET
        self.poll_calls += 1
        return self.polls[min(self.poll_calls - 1, len(self.polls) - 1)]


def _cap_async():
    return {
        "nom": "video_resumer", "brique": "synopsis", "description": "resumer",
        "methode": "POST", "chemin": "/resumer",
        "url": "http://host.docker.internal:6090/resumer",
        "params": {"url": {"type": "string", "requis": True}},
        "action": False, "async": True, "poll_chemin": "/jobs/{id}",
    }


def _patch_client_async(monkeypatch, post_resp, polls):
    """Force _appel_dynamique à utiliser un AsyncClient qui route vers _ClientAsync."""
    import outils_communs
    cli = _ClientAsync(post_resp, polls)

    class _Fab:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return cli

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(outils_communs.httpx, "AsyncClient", lambda *a, **kw: _Fab(*a, **kw))
    return cli


def test_appel_dynamique_async_termine_rend_resultat(monkeypatch):
    post = _Resp(202, {"job_id": "abc", "statut": "en_cours", "poll_url": "/jobs/abc"})
    polls = [
        _Resp(200, {"statut": "en_cours", "progress_pct": 50}),
        _Resp(200, {"statut": "termine", "progress_pct": 100,
                    "resultat": {"titre": "T", "resume": "R"}}),
    ]
    cli = _patch_client_async(monkeypatch, post, polls)
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=abc"})))
    assert out["titre"] == "T"
    assert out["resume"] == "R"


def test_appel_dynamique_async_erreur_rend_ok_false_avec_message(monkeypatch):
    post = _Resp(202, {"job_id": "x1", "statut": "en_cours"})
    polls = [_Resp(200, {"statut": "erreur", "erreur": "Vidéo inaccessible"})]
    cli = _patch_client_async(monkeypatch, post, polls)
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=bad"})))
    assert out["ok"] is False
    assert "Vidéo inaccessible" in out["message"]


def test_appel_dynamique_async_timeout_rend_message_avec_job_id(monkeypatch):
    import outils_communs
    monkeypatch.setenv("OUTILS_ASYNC_TIMEOUT", "0.05")
    post = _Resp(202, {"job_id": "abc", "statut": "en_cours"})
    polls = [_Resp(200, {"statut": "en_cours"})]  # toujours en_cours
    cli = _patch_client_async(monkeypatch, post, polls)
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=long"})))
    assert out["ok"] is False
    assert "délai" in out["message"].lower()
    assert out["job_id"] == "abc"


def test_appel_dynamique_async_sans_job_id_rend_honnete(monkeypatch):
    post = _Resp(202, {"statut": "en_cours"})  # pas de job_id
    cli = _patch_client_async(monkeypatch, post, [])
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=x"})))
    assert out["ok"] is False
    assert "job_id" in out["message"].lower() or "202" in out["message"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd core && python -m pytest test_outils_dynamiques.py -k async -v
```
Expected: FAIL (`assert "T" == None` ou similaire — la branche async n'existe pas).

- [ ] **Step 3: Write minimal implementation**

Dans `core/outils_communs.py`, modifier `_appel_dynamique` (lignes 75-109). Ajouter en haut de fichier (après `import httpx`, ligne 9):

```python
import asyncio
```

Puis **remplacer** toute la fonction `_appel_dynamique` (lignes 75-109) par:

```python
ASYNC_TIMEOUT = float(os.environ.get("OUTILS_ASYNC_TIMEOUT", "600"))
ASYNC_POLL = float(os.environ.get("OUTILS_ASYNC_POLL", "5"))


async def _poll_async(poll_url: str, headers: dict | None, brique: str,
                      job_id: str) -> str:
    """Boucle GET sur poll_url jusqu'à statut terminal. Rend un JSON pour le LLM."""
    async with httpx.AsyncClient(timeout=None, headers=headers) as c:
        while True:
            r = await c.get(poll_url)
            try:
                data = r.json()
            except ValueError:
                return json.dumps({"ok": False, "brique": brique,
                                   "message": f"Poll {poll_url} a renvoyé un corps non JSON "
                                              f"(HTTP {r.status_code})."}, ensure_ascii=False)
            statut = data.get("statut")
            if statut == "termine":
                return json.dumps(data.get("resultat") or data, ensure_ascii=False)
            if statut == "erreur":
                return json.dumps({"ok": False, "brique": brique,
                                   "message": data.get("erreur") or "job en erreur"},
                                  ensure_ascii=False)
            await asyncio.sleep(ASYNC_POLL)


async def _appel_dynamique(client, cap: dict, args: dict) -> str:
    """Exécute une capacité découverte : gate confirmation, appel HTTP, puis soit
    rend la réponse (sync) soit poll si cap.async=true et réponse 202."""
    args = dict(args or {})
    confirme = args.pop("confirme", None)
    if cap.get("action") and not confirme:
        return _confirmation(cap["nom"], cap["brique"])
    url = _url_dynamique(cap, args)
    charge = {k: v for k, v in args.items()
              if v is not None and ("{" + k + "}") not in cap["chemin"]}
    entetes = _entetes_brique(cap["brique"]) or None
    if cap["methode"] == "GET":
        r = await client.request("GET", url, params=charge, headers=entetes)
    else:
        r = await client.request(cap["methode"], url, json=charge, params=charge, headers=entetes)
    # ── Branche async (S179) : 202 sur cap async → on poll ──
    if cap.get("async") and r.status_code == 202:
        try:
            body = r.json()
        except ValueError:
            return json.dumps({"ok": False, "brique": cap["brique"],
                               "message": "202 sans corps JSON."}, ensure_ascii=False)
        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            return json.dumps({"ok": False, "brique": cap["brique"],
                               "message": "202 reçu sans job_id — impossible de poller."},
                              ensure_ascii=False)
        poll_chemin = (cap.get("poll_chemin") or "/jobs/{id}").replace("{id}", str(job_id))
        # On reconstruit l'URL absolue sur la même brique (cap.url = base + chemin).
        base = cap["url"].rsplit(cap["chemin"], 1)[0]  # retire le chemin POST
        poll_url = base + poll_chemin
        try:
            return await asyncio.wait_for(
                _poll_async(poll_url, entetes, cap["brique"], job_id),
                timeout=ASYNC_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return json.dumps({"ok": False, "brique": cap["brique"],
                               "message": f"Délai dépassé ({ASYNC_TIMEOUT:.0f}s). Job "
                                          f"toujours en cours — interroge GET {poll_url} "
                                          "plus tard.",
                               "job_id": job_id}, ensure_ascii=False)
    # ── Branche sync (comportement S64 inchangé) ──
    if r.status_code >= 400:
        return json.dumps({"ok": False, "brique": cap["brique"],
                           "message": f"Brique « {cap['brique']} » a refusé ({r.status_code})."},
                          ensure_ascii=False)
    try:
        return json.dumps(r.json(), ensure_ascii=False)
    except ValueError:
        texte = (r.text or "").strip()
        if not texte:
            return json.dumps({"ok": True, "brique": cap["brique"], "status": r.status_code},
                              ensure_ascii=False)
        return texte[:1000]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd core && python -m pytest test_outils_dynamiques.py -v
```
Expected: PASS (tous, y compris les 4 nouveaux async + les sync existants).

- [ ] **Step 5: Commit**

```bash
git add core/outils_communs.py core/test_outils_dynamiques.py
git commit -m "feat(s179): _appel_dynamique — branche async (202 + poll OUTILS_ASYNC_TIMEOUT)"
```

---

## Task 9 : Front `front.html` — polling navigateur

**Files:**
- Modify: `briques/synopsis/front.html` (fonction `lancer` lignes 150-159 + `resumerUrl` / `resumerFichier`).

**Interfaces:**
- Consumes: `POST /resumer` → `202 {job_id, poll_url}` (Task 3), `POST /reel` (Task 4), `POST /resumer-fichier` (Task 5), `GET /jobs/{id}` (Task 2).
- Produces: UX inchangée côté utilisateur (spinner, puis résumé) mais réactif à l'état async.

- [ ] **Step 1: No failing test** (front JS non testé par pytest ; on valide au runtime au Task 10).

- [ ] **Step 2: Modify `briques/synopsis/front.html`**

Remplacer les fonctions `resumerUrl`, `resumerFichier`, `alerter`, `lancer` (lignes 131-159) par:

```javascript
function alerter(m){ etat(m, true); }

async function lancer(req, msg){
  $('res').style.display = 'none'; busy(true); etat(msg, false);
  try{
    const r = await req();
    const data = await r.json();
    if(!r.ok) throw new Error(data.detail || ('Erreur ' + r.status));
    if (data.job_id && data.poll_url){
      await attendreJob(data.poll_url);
    } else {
      afficher(data); cacherEtat();
    }
  }catch(e){ alerter('❌ ' + e.message); }
  finally{ busy(false); }
}

async function attendreJob(pollUrl){
  let tour = 0;
  while(true){
    const r = await fetch(pollUrl);
    const j = await r.json();
    if(j.statut === 'termine'){
      afficher(j.resultat || {});
      cacherEtat();
      return;
    }
    if(j.statut === 'erreur'){
      throw new Error(j.erreur || 'Job en erreur');
    }
    const pct = j.progress_pct ? ` — ${j.progress_pct}%` : '';
    etat(`<span class="spin"></span>Traitement en cours${pct}…`, false);
    const delai = Math.min(2000 + tour * 500, 15000);
    await new Promise(res => setTimeout(res, delai));
    tour += 1;
  }
}
```

Adapter `resumerUrl` (lignes 131-138) et `resumerFichier` (lignes 140-146) — elles restent identiques : elles appellent `lancer(...)` qui gère maintenant l'async.

- [ ] **Step 3: Sanity check visuel**

```bash
cd briques/synopsis && grep -c "attendreJob\|poll_url\|progress_pct" front.html
```
Expected: ≥ 3 occurrences.

- [ ] **Step 4: Commit**

```bash
git add briques/synopsis/front.html
git commit -m "feat(s179): front — polling navigateur sur GET /jobs/{id}"
```

---

## Task 10 : Test d'intégration sur le HP + bump readme

**Files:**
- Modify: `briques/synopsis/README.md` (doc endpoints async).

Pas de test automatisé (HP = déploiement). On valide manuellement via `curl` sur le stack HP.

- [ ] **Step 1: Update `briques/synopsis/README.md`**

Remplacer le bloc « Endpoints API » (lignes 27-34) par:

```markdown
## Endpoints API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sante` | Health check (+ statut Gateway) |
| `POST` | `/resumer` | `{"url": "...", "langue": "Français"}` → `202 {job_id, statut:"en_cours", poll_url}` |
| `POST` | `/reel` | `{"url": "...", "duree_clip": 45}` → `202 {job_id, poll_url}` (highlight reel) |
| `POST` | `/resumer-fichier` | multipart `fichier=...` → `202 {job_id, poll_url}` |
| `GET` | `/jobs/{id}` | `{statut, progress_pct, resultat?, erreur?}` — poll jusqu'à `statut:"termine"\|"erreur"` |

Tous les POST sont **asynchrones** (S179) : la brique renvoie `202` immédiatement et
exécute le pipeline en arrière-plan (BackgroundTasks). Poller `GET /jobs/{job_id}`
jusqu'à `statut:"termine"` (résultat) ou `statut:"erreur"` (échec).
```

- [ ] **Step 2: Reconstruire synopsis sur le HP**

```bash
ssh debian@192.168.1.89 'cd ~/workplace && git pull --ff-only && \
  cd briques/synopsis && make build && make up'
```

- [ ] **Step 3: Reconstruire le Cœur sur le HP**

```bash
ssh debian@192.168.1.89 'cd ~/workplace/core && docker compose build core && docker compose up -d core'
```

- [ ] **Step 4: Recharger le registre**

```bash
ssh debian@192.168.1.89 'curl -sX POST http://localhost:5000/briques/reload'
```

- [ ] **Step 5: Test direct synopsis (curl)**

```bash
ssh debian@192.168.1.89 'sleep 5 && \
  R=$(curl -sX POST http://localhost:6090/resumer -H "Content-Type: application/json" \
       -d "{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\",\"langue\":\"Français\"}"); \
  echo "POST: $R"; \
  JID=$(echo "$R" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"job_id\"])"); \
  sleep 60; \
  curl -s http://localhost:6090/jobs/$JID | python3 -m json.tool | head -30'
```
Expected: `POST` renvoie `{"job_id":"...","statut":"en_cours","poll_url":"/jobs/..."}` puis `GET /jobs/{id}` renvoie `{"statut":"termine","progress_pct":100,"resultat":{"titre":"...","resume":"..."}}`.

- [ ] **Step 6: Test via l'assistant**

Sur front `http://localhost:5000/` (ou tunnelconnexion si à distance), coller une URL
YouTube à l'assistant. Vérifier que le résumé complet s'affiche en moins de 90 s (sans
erreur "Brique injoignable").

- [ ] **Step 7: Commit + suite**

```bash
git add briques/synopsis/README.md
git commit -m "docs(s179): README — endpoints async"
```

---

## Self-review (à exécuter avant handoff)

- Spec couverture :
  - Synopsis async sur 3 endpoints → Tasks 3 (resumer), 4 (reel), 5 (fichier). ✓
  - `lib/jobs.py` SQLite → Task 1. ✓
  - `GET /jobs/{id}` → Task 2. ✓
  - Manifest `async`/`poll_chemin` → Task 6. ✓
  - Bump 1.2.0 → Task 6. ✓
  - Catalogue propagation → Task 7. ✓
  - `_appel_dynamique` async → Task 8. ✓
  - Env `OUTILS_ASYNC_TIMEOUT`/`OUTILS_ASYNC_POLL` → Task 8. ✓
  - Front polling → Task 9. ✓
  - Tests côté Cœur async → Task 8. ✓
  - Tests Synopsis async → Tasks 1-5. ✓
  - Anti-régression sync → Task 8 garde la branche sync préexistante + tests existants. ✓
  - Déploiement HP → Task 10. ✓
- Placeholders : aucun TOD, code complet dans chaque step.
- Type cohérence : `lib.jobs.lire_job` renvoie `dict | None` — appelé cohéremment Tasks 2/3/4/5. `_appel_dynamique` signature `(client, cap, args)` inchangée. `_poll_async(poll_url, headers, brique, job_id)` référencée correctement.