"""Persistance SQLite de la brique téléphonie — numéros possédés, messages, appels.

Tout est CLOISONNÉ par `solution` (le tenant, dérivé de la clé API). Une solution ne voit ni
n'utilise jamais les numéros/messages d'une autre. Le schéma est créé à l'import (idempotent).
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB = os.getenv("TELEPHONIE_DB", "/data/telephonie.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nouvel_id(prefixe: str) -> str:
    return f"{prefixe}_{uuid.uuid4().hex[:16]}"


def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _init() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS numeros (
                id          TEXT PRIMARY KEY,
                solution    TEXT NOT NULL,
                ref_externe TEXT,
                numero      TEXT NOT NULL,
                pays        TEXT,
                statut      TEXT NOT NULL,
                date        TEXT NOT NULL
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                solution    TEXT NOT NULL,
                ref_externe TEXT,
                sens        TEXT NOT NULL,           -- sortant | entrant
                de          TEXT NOT NULL,
                vers        TEXT NOT NULL,
                corps       TEXT NOT NULL,
                segments    INTEGER DEFAULT 1,
                statut      TEXT NOT NULL,
                date        TEXT NOT NULL
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS appels (
                id          TEXT PRIMARY KEY,
                solution    TEXT NOT NULL,
                ref_externe TEXT,
                de          TEXT NOT NULL,
                vers        TEXT NOT NULL,
                message     TEXT,
                statut      TEXT NOT NULL,
                date        TEXT NOT NULL
            )""")
        c.commit()


_init()


def _d(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


# ── Numéros possédés ─────────────────────────────────────────────
def creer_numero(solution: str, ref_externe: str, numero: str, pays: str, statut: str) -> dict:
    nid = _nouvel_id("num")
    with _conn() as c:
        c.execute("INSERT INTO numeros (id, solution, ref_externe, numero, pays, statut, date)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (nid, solution, ref_externe, numero, pays, statut, _maintenant()))
        c.commit()
    return lire_numero(solution, nid)


def lister_numeros(solution: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM numeros WHERE solution=? ORDER BY date DESC",
                         (solution,)).fetchall()
    return [dict(r) for r in rows]


def lire_numero(solution: str, numero_id: str) -> dict | None:
    with _conn() as c:
        return _d(c.execute("SELECT * FROM numeros WHERE solution=? AND id=?",
                            (solution, numero_id)).fetchone())


def numero_possede(solution: str, numero: str) -> bool:
    """La solution possède-t-elle CE numéro (émetteur autorisé) ? Cloisonnement de l'envoi."""
    with _conn() as c:
        return c.execute("SELECT 1 FROM numeros WHERE solution=? AND numero=? LIMIT 1",
                         (solution, numero)).fetchone() is not None


# ── Messages (SMS) ───────────────────────────────────────────────
def creer_message(solution: str, ref_externe: str, sens: str, de: str, vers: str,
                  corps: str, segments: int, statut: str) -> dict:
    mid = _nouvel_id("sms")
    with _conn() as c:
        c.execute("INSERT INTO messages (id, solution, ref_externe, sens, de, vers, corps,"
                  " segments, statut, date) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (mid, solution, ref_externe, sens, de, vers, corps, segments, statut,
                   _maintenant()))
        c.commit()
    return lire_message(solution, mid)


def lister_messages(solution: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM messages WHERE solution=? ORDER BY date DESC",
                         (solution,)).fetchall()
    return [dict(r) for r in rows]


def lire_message(solution: str, message_id: str) -> dict | None:
    with _conn() as c:
        return _d(c.execute("SELECT * FROM messages WHERE solution=? AND id=?",
                            (solution, message_id)).fetchone())


def maj_statut_message(message_id: str, statut: str) -> None:
    with _conn() as c:
        c.execute("UPDATE messages SET statut=? WHERE id=?", (statut, message_id))
        c.commit()


def message_par_ref(ref_externe: str) -> dict | None:
    with _conn() as c:
        return _d(c.execute("SELECT * FROM messages WHERE ref_externe=?",
                            (ref_externe,)).fetchone())


# ── Appels ───────────────────────────────────────────────────────
def creer_appel(solution: str, ref_externe: str, de: str, vers: str,
                message: str, statut: str) -> dict:
    aid = _nouvel_id("appel")
    with _conn() as c:
        c.execute("INSERT INTO appels (id, solution, ref_externe, de, vers, message, statut,"
                  " date) VALUES (?,?,?,?,?,?,?,?)",
                  (aid, solution, ref_externe, de, vers, message, statut, _maintenant()))
        c.commit()
    return lire_appel(solution, aid)


def lister_appels(solution: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM appels WHERE solution=? ORDER BY date DESC",
                         (solution,)).fetchall()
    return [dict(r) for r in rows]


def lire_appel(solution: str, appel_id: str) -> dict | None:
    with _conn() as c:
        return _d(c.execute("SELECT * FROM appels WHERE solution=? AND id=?",
                            (solution, appel_id)).fetchone())


def maj_statut_appel(appel_id: str, statut: str) -> None:
    with _conn() as c:
        c.execute("UPDATE appels SET statut=? WHERE id=?", (statut, appel_id))
        c.commit()


def appel_par_ref(ref_externe: str) -> dict | None:
    with _conn() as c:
        return _d(c.execute("SELECT * FROM appels WHERE ref_externe=?",
                            (ref_externe,)).fetchone())
