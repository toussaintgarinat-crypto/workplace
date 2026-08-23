"""Stockage des enfants générés par `POST /genome/croiser` — persistance AUTOMATIQUE
(contrairement à `personnages/stockage.py` qui est opt-in) : c'est ce qui permet
d'enchaîner les générations sans geste explicite à chaque croisement. Cloisonné par
`cle_api`, même motif que `personnages`."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("WORLD_ENGINE_DB", "/data/world_engine.db")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_enfant_cle ON enfants(cle_api)")
    return c


def _ligne_complete(r: sqlite3.Row) -> dict:
    d = json.loads(r["donnees"])
    return {"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
            "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"],
            "theme": d["theme"], "description_genome": d["description_genome"],
            "heredite": d["heredite"], "mutation_survenue": d["mutation_survenue"],
            "cree_le": r["cree_le"]}


def creer(cle_api: str, prenoms: str, nom: str, parent_a_id: str | None, parent_b_id: str | None,
          theme: dict, description_genome: str, heredite: dict, mutation_survenue: bool) -> str:
    """Persiste un enfant généré par un croisement. Renvoie son id.

    `theme` = snapshot COMPLET renvoyé par `personnages` (traditions/portrait/
    theme_complet) — la même forme qu'une fiche parent en sortie de
    `personnages_client.portrait`, pour pouvoir être réinjecté tel quel comme
    parent d'un croisement suivant sans rappeler `personnages`."""
    eid = uuid.uuid4().hex
    donnees = {"theme": theme, "description_genome": description_genome,
               "heredite": heredite, "mutation_survenue": mutation_survenue}
    with _conn() as c:
        c.execute("""INSERT INTO enfants (id, cle_api, prenoms, nom, parent_a_id, parent_b_id, donnees, cree_le)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (eid, cle_api, prenoms or "", nom or "", parent_a_id, parent_b_id,
                   json.dumps(donnees, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return eid


def lister(cle_api: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, prenoms, nom, parent_a_id, parent_b_id, cree_le FROM enfants "
            "WHERE cle_api=? ORDER BY cree_le DESC", (cle_api,)).fetchall()
    return [{"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
             "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"],
             "cree_le": r["cree_le"]} for r in rows]


def lire(cle_api: str, eid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM enfants WHERE id=? AND cle_api=?", (eid, cle_api)).fetchone()
    return _ligne_complete(r) if r else None


def supprimer(cle_api: str, eid: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM enfants WHERE id=? AND cle_api=?", (eid, cle_api))
    return cur.rowcount > 0
