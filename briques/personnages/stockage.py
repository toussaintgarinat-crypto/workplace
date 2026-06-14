"""Stockage optionnel des distributions, cloisonné par clé API (couche « stateful »).

SQLite (stdlib) : une distribution = {id, titre, langue, premisse, personnages:[...]}.
Chaque ligne porte sa `cle_api` → un client ne voit JAMAIS les distributions d'un autre
(isolation par tenant). Le mode stateless n'utilise pas ce module.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("PERSONNAGES_DB", "/data/personnages.db")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS distributions (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, titre TEXT, langue TEXT,
        premisse TEXT, personnages TEXT NOT NULL, cree_le TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cle ON distributions(cle_api)")
    return c


def _ligne(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "titre": r["titre"], "langue": r["langue"],
            "premisse": r["premisse"], "personnages": json.loads(r["personnages"]),
            "cree_le": r["cree_le"]}


def creer(cle_api: str, titre: str = "", langue: str = "fr",
          premisse: str = "", personnages: list | None = None) -> dict:
    d = {"id": uuid.uuid4().hex, "titre": titre or "Distribution", "langue": langue or "fr",
         "premisse": premisse or "", "personnages": personnages or [],
         "cree_le": datetime.now(timezone.utc).isoformat()}
    with _conn() as c:
        c.execute("INSERT INTO distributions VALUES (?,?,?,?,?,?,?)",
                  (d["id"], cle_api, d["titre"], d["langue"], d["premisse"],
                   json.dumps(d["personnages"], ensure_ascii=False), d["cree_le"]))
    return d


def lister(cle_api: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM distributions WHERE cle_api=? ORDER BY cree_le DESC",
            (cle_api,)).fetchall()
    return [{"id": r["id"], "titre": r["titre"], "langue": r["langue"],
             "personnages": len(json.loads(r["personnages"])), "cree_le": r["cree_le"]}
            for r in rows]


def lire(cle_api: str, did: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM distributions WHERE id=? AND cle_api=?",
                      (did, cle_api)).fetchone()
    return _ligne(r) if r else None


def maj(cle_api: str, did: str, champs: dict) -> dict | None:
    d = lire(cle_api, did)
    if not d:
        return None
    for k in ("titre", "langue", "premisse", "personnages"):
        if k in champs and champs[k] is not None:
            d[k] = champs[k]
    with _conn() as c:
        c.execute("""UPDATE distributions SET titre=?, langue=?, premisse=?, personnages=?
                     WHERE id=? AND cle_api=?""",
                  (d["titre"], d["langue"], d["premisse"],
                   json.dumps(d["personnages"], ensure_ascii=False), did, cle_api))
    return d


def supprimer(cle_api: str, did: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM distributions WHERE id=? AND cle_api=?", (did, cle_api))
    return cur.rowcount > 0
