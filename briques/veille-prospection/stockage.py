"""Persistance de veille-prospection (SQLite). Cloisonné par `user_id` (motif
briques/veille-info/stockage.py). `campagnes` référence une zone `geo` EXISTANTE
(`zone_id`) — la définition de zone reste exclusivement dans `geo`, jamais dupliquée ici.
`executions` journalise chaque passage horloge, par campagne."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

_DB = os.getenv("VEILLE_PROSPECTION_DB", "/data/veille_prospection.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS campagnes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    actif INTEGER NOT NULL DEFAULT 1,
    derniere_execution TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campagnes_user ON campagnes(user_id);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campagne_id INTEGER NOT NULL REFERENCES campagnes(id),
    date TEXT NOT NULL,
    trouves INTEGER NOT NULL DEFAULT 0,
    deja_connus INTEGER NOT NULL DEFAULT 0,
    nouveaux_crm INTEGER NOT NULL DEFAULT 0,
    erreur TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_executions_campagne ON executions(campagne_id);
"""


def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)


init()  # schéma prêt dès l'import (robuste même sous TestClient)


def _campagne_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "zone_id": r["zone_id"],
            "actif": bool(r["actif"]), "derniere_execution": r["derniere_execution"],
            "created_at": r["created_at"]}


def creer_campagne(user_id: str, zone_id: str) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO campagnes (user_id, zone_id, actif, created_at) VALUES (?,?,1,?)",
            (user_id, zone_id, _maintenant()))
        row = c.execute("SELECT * FROM campagnes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _campagne_dict(row)


def lister_campagnes(user_id: str, *, actives_seulement: bool = False) -> list[dict]:
    q = "SELECT * FROM campagnes WHERE user_id = ?"
    if actives_seulement:
        q += " AND actif = 1"
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, (user_id,)).fetchall()
    return [_campagne_dict(r) for r in rows]


def supprimer_campagne(user_id: str, campagne_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM campagnes WHERE id = ? AND user_id = ?",
                        (campagne_id, user_id))
    return cur.rowcount > 0


def lister_user_ids_actifs() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT user_id FROM campagnes WHERE actif = 1").fetchall()
    return [r["user_id"] for r in rows]


def _execution_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "campagne_id": r["campagne_id"], "date": r["date"],
            "trouves": r["trouves"], "deja_connus": r["deja_connus"],
            "nouveaux_crm": r["nouveaux_crm"], "erreur": r["erreur"],
            "created_at": r["created_at"]}


def inserer_execution(campagne_id: int, *, trouves: int, deja_connus: int,
                      nouveaux_crm: int, erreur: str | None) -> dict:
    date = datetime.now(timezone.utc).date().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO executions (campagne_id, date, trouves, deja_connus, nouveaux_crm,"
            " erreur, created_at) VALUES (?,?,?,?,?,?,?)",
            (campagne_id, date, trouves, deja_connus, nouveaux_crm, erreur, _maintenant()))
        row = c.execute("SELECT * FROM executions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _execution_dict(row)


def lister_executions(campagne_id: int, limite: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM executions WHERE campagne_id = ? ORDER BY created_at DESC LIMIT ?",
            (campagne_id, limite)).fetchall()
    return [_execution_dict(r) for r in rows]


def maj_derniere_execution(campagne_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE campagnes SET derniere_execution = ? WHERE id = ?",
                  (_maintenant(), campagne_id))
