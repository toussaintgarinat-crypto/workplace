"""Persistance de la brique veille-info (SQLite). Cloisonné par `user_id` : une personne ne
voit jamais les sources, articles ni digests d'une autre — même motif que `briques/mail`.

Trois tables : `sources` (flux RSS suivis), `articles` (dédup par `(user_id, url)`) et
`digests` (un résumé consolidé par jour et par personne — `UNIQUE(user_id, date)` porte
l'idempotence de la tâche horloge, cf. `digest.py`)."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

_DB = os.getenv("VEILLE_INFO_DB", "/data/veille_info.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aujourdhui() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    nom TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_user ON sources(user_id);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    titre TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    created_at TEXT NOT NULL,
    digested INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_articles_user ON articles(user_id);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    texte_resume TEXT NOT NULL,
    nb_articles INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, date)
);
CREATE INDEX IF NOT EXISTS idx_digests_user ON digests(user_id);

CREATE TABLE IF NOT EXISTS digest_audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    url TEXT NOT NULL,
    duree REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_digest_audio_digest ON digest_audio(digest_id);
"""


def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)


init()  # schéma prêt dès l'import (robuste même sous TestClient)


# ── Sources ───────────────────────────────────────────────────
def _source_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "url": r["url"], "enabled": bool(r["enabled"]),
            "created_at": r["created_at"]}


def creer_source(user_id: str, nom: str, url: str) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sources (user_id, nom, url, enabled, created_at) VALUES (?,?,?,1,?)",
            (user_id, nom, url, _maintenant()))
        row = c.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _source_dict(row)


def lister_sources(user_id: str, *, actives_seulement: bool = False) -> list[dict]:
    q = "SELECT * FROM sources WHERE user_id = ?"
    if actives_seulement:
        q += " AND enabled = 1"
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, (user_id,)).fetchall()
    return [_source_dict(r) for r in rows]


def supprimer_source(user_id: str, source_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM sources WHERE id = ? AND user_id = ?", (source_id, user_id))
    return cur.rowcount > 0


def lister_user_ids_actifs() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT user_id FROM sources WHERE enabled = 1").fetchall()
    return [r["user_id"] for r in rows]


# ── Articles ──────────────────────────────────────────────────
def inserer_article(user_id: str, source_id: int, titre: str, url: str,
                    published_at: str) -> bool:
    """Insère un article. Renvoie False si déjà présent pour cet utilisateur (dédup par URL)."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO articles (user_id, source_id, titre, url, published_at, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (user_id, source_id, titre, url, published_at, _maintenant()))
    return cur.rowcount > 0


def articles_non_digestes(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM articles WHERE user_id = ? AND digested = 0 ORDER BY created_at ASC",
            (user_id,)).fetchall()
    return [{"id": r["id"], "titre": r["titre"], "url": r["url"],
            "published_at": r["published_at"]} for r in rows]


def marquer_articles_digestes(article_ids: list[int]) -> None:
    if not article_ids:
        return
    placeholders = ",".join("?" * len(article_ids))
    with _conn() as c:
        c.execute(f"UPDATE articles SET digested = 1 WHERE id IN ({placeholders})", article_ids)


# ── Digests ───────────────────────────────────────────────────
def _digest_dict(r: sqlite3.Row) -> dict:
    cols = r.keys()
    return {"id": r["id"], "date": r["date"], "texte_resume": r["texte_resume"],
            "nb_articles": r["nb_articles"], "created_at": r["created_at"],
            "audio_url": r["audio_url"] if "audio_url" in cols else None,
            "audio_duree": r["audio_duree"] if "audio_duree" in cols else None}


_DIGEST_AVEC_AUDIO = """
    SELECT d.*, da.url AS audio_url, da.duree AS audio_duree
    FROM digests d
    LEFT JOIN digest_audio da ON da.id = (
        SELECT id FROM digest_audio WHERE digest_id = d.id ORDER BY id DESC LIMIT 1
    )
"""


def digest_existe(user_id: str, date: str | None = None) -> bool:
    date = date or _aujourdhui()
    with _conn() as c:
        row = c.execute("SELECT 1 FROM digests WHERE user_id = ? AND date = ?",
                        (user_id, date)).fetchone()
    return row is not None


def inserer_digest(user_id: str, texte_resume: str, nb_articles: int,
                   date: str | None = None) -> dict:
    date = date or _aujourdhui()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digests (user_id, date, texte_resume, nb_articles, created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, date, texte_resume, nb_articles, _maintenant()))
        row = c.execute("SELECT * FROM digests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _digest_dict(row)


def lister_digests(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(_DIGEST_AVEC_AUDIO + " WHERE d.user_id = ? ORDER BY d.date DESC",
                         (user_id,)).fetchall()
    return [_digest_dict(r) for r in rows]


def digest_get(user_id: str, digest_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(_DIGEST_AVEC_AUDIO + " WHERE d.id = ? AND d.user_id = ?",
                        (digest_id, user_id)).fetchone()
    return _digest_dict(row) if row else None


# ── Audio ─────────────────────────────────────────────────────
def inserer_audio_digest(digest_id: int, url: str, duree: float | None) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digest_audio (digest_id, url, duree, created_at) VALUES (?,?,?,?)",
            (digest_id, url, duree, _maintenant()))
        row = c.execute("SELECT * FROM digest_audio WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"id": row["id"], "digest_id": row["digest_id"], "url": row["url"],
            "duree": row["duree"], "created_at": row["created_at"]}
