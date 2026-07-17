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
  erreur        TEXT,
  date_maj      TEXT
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