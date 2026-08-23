"""Persistance SQLite des mondes spatiaux, de leurs cellules et des placements
d'enfants (Sprint B). Même base (`WORLD_ENGINE_DB`) et même motif que
`stockage.py` (cloisonnement par `cle_api`), tables séparées."""
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
    c.execute("""CREATE TABLE IF NOT EXISTS mondes (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, nb_cellules INTEGER NOT NULL,
        seed INTEGER NOT NULL, forked_from_id TEXT, cree_le TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_monde_cle ON mondes(cle_api)")
    c.execute("""CREATE TABLE IF NOT EXISTS cellules (
        monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        x REAL NOT NULL, y REAL NOT NULL, biome TEXT NOT NULL,
        ressources TEXT NOT NULL, voisins TEXT NOT NULL,
        PRIMARY KEY (monde_id, cellule_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS placements (
        enfant_id TEXT NOT NULL, monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        place_le TEXT, PRIMARY KEY (enfant_id, monde_id))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_placement_monde ON placements(monde_id)")
    # DUPLIQUÉE depuis stockage.py::_conn() (fix latent Task 2 : GET /spatial/mondes/{id}
    # 500ait sur une DB fraîche sans cette table). Le schéma DOIT rester identique entre
    # les deux copies — test_stockage_spatial.py::test_ddl_enfants_identique_a_stockage
    # pince les deux en synchro.
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    return c


def _meta(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nb_cellules": r["nb_cellules"], "seed": r["seed"],
            "forked_from_id": r["forked_from_id"], "cree_le": r["cree_le"]}


def creer_monde(cle_api: str, cellules: list[dict], seed: int, forked_from_id: str | None = None) -> dict:
    """Persiste un monde déjà généré (`cellules` = sortie de `spatial.generer_monde`,
    ou une copie lors d'un fork). Renvoie ses métadonnées."""
    mid = uuid.uuid4().hex
    cree_le = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("INSERT INTO mondes (id, cle_api, nb_cellules, seed, forked_from_id, cree_le) "
                   "VALUES (?,?,?,?,?,?)",
                   (mid, cle_api, len(cellules), seed, forked_from_id, cree_le))
        c.executemany(
            "INSERT INTO cellules (monde_id, cellule_id, x, y, biome, ressources, voisins) "
            "VALUES (?,?,?,?,?,?,?)",
            [(mid, cel["cellule_id"], cel["x"], cel["y"], cel["biome"],
              json.dumps(cel["ressources"], ensure_ascii=False),
              json.dumps(cel["voisins"])) for cel in cellules])
    return {"id": mid, "nb_cellules": len(cellules), "seed": seed,
            "forked_from_id": forked_from_id, "cree_le": cree_le}


def lister_mondes(cle_api: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, nb_cellules, seed, forked_from_id, cree_le FROM mondes "
            "WHERE cle_api=? ORDER BY cree_le DESC", (cle_api,)).fetchall()
    return [_meta(r) for r in rows]


def monde_existe(cle_api: str, monde_id: str) -> bool:
    with _conn() as c:
        r = c.execute("SELECT 1 FROM mondes WHERE id=? AND cle_api=?", (monde_id, cle_api)).fetchone()
    return r is not None


def nb_cellules_monde(monde_id: str) -> int | None:
    """⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction."""
    with _conn() as c:
        r = c.execute("SELECT nb_cellules FROM mondes WHERE id=?", (monde_id,)).fetchone()
    return r["nb_cellules"] if r else None


def _enfants_par_cellule(c: sqlite3.Connection, monde_id: str) -> dict[int, list[dict]]:
    """Enfants placés dans ce monde, groupés par cellule_id — lecture jointe à la
    table `enfants` de `stockage.py` (même base SQLite, tables distinctes)."""
    rows = c.execute(
        "SELECT p.cellule_id AS cid, e.id AS id, e.prenoms AS prenoms, e.nom AS nom "
        "FROM placements p JOIN enfants e ON p.enfant_id = e.id WHERE p.monde_id=?",
        (monde_id,)).fetchall()
    par_cellule: dict[int, list[dict]] = {}
    for r in rows:
        par_cellule.setdefault(r["cid"], []).append(
            {"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"]})
    return par_cellule


def _cellule_dict(r: sqlite3.Row, enfants: list[dict]) -> dict:
    return {"cellule_id": r["cellule_id"], "x": r["x"], "y": r["y"], "biome": r["biome"],
            "ressources": json.loads(r["ressources"]), "voisins": json.loads(r["voisins"]),
            "enfants": enfants}


def lire_monde(cle_api: str, monde_id: str) -> dict | None:
    with _conn() as c:
        m = c.execute("SELECT * FROM mondes WHERE id=? AND cle_api=?", (monde_id, cle_api)).fetchone()
        if m is None:
            return None
        rows = c.execute("SELECT * FROM cellules WHERE monde_id=? ORDER BY cellule_id",
                          (monde_id,)).fetchall()
        enfants = _enfants_par_cellule(c, monde_id)
    cellules = [_cellule_dict(r, enfants.get(r["cellule_id"], [])) for r in rows]
    return {**_meta(m), "cellules": cellules}


def lire_cellule(cle_api: str, monde_id: str, cellule_id: int) -> dict | None:
    with _conn() as c:
        if c.execute("SELECT 1 FROM mondes WHERE id=? AND cle_api=?",
                      (monde_id, cle_api)).fetchone() is None:
            return None
        r = c.execute("SELECT * FROM cellules WHERE monde_id=? AND cellule_id=?",
                       (monde_id, cellule_id)).fetchone()
        if r is None:
            return None
        enfants = _enfants_par_cellule(c, monde_id).get(cellule_id, [])
    return _cellule_dict(r, enfants)


def voisins_cellule(monde_id: str, cellule_id: int) -> list[int] | None:
    """⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction."""
    with _conn() as c:
        r = c.execute("SELECT voisins FROM cellules WHERE monde_id=? AND cellule_id=?",
                       (monde_id, cellule_id)).fetchone()
    return json.loads(r["voisins"]) if r else None


def placement_cellule(monde_id: str, enfant_id: str) -> int | None:
    """⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction."""
    with _conn() as c:
        r = c.execute("SELECT cellule_id FROM placements WHERE monde_id=? AND enfant_id=?",
                       (monde_id, enfant_id)).fetchone()
    return r["cellule_id"] if r else None


def placer(monde_id: str, enfant_id: str, cellule_id: int) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction."""
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO placements (enfant_id, monde_id, cellule_id, place_le) "
                   "VALUES (?,?,?,?)",
                   (enfant_id, monde_id, cellule_id, datetime.now(timezone.utc).isoformat()))


def supprimer_placements_enfant(enfant_id: str) -> None:
    """Supprime tous les placements de cet enfant, dans TOUS les mondes — appelée
    après `stockage.supprimer(cle_api, enfant_id)` pour ne pas laisser de rangée
    `placements` orpheline. Pas de cloisonnement `cle_api` ici : l'appartenance de
    `enfant_id` au tenant a déjà été confirmée par `stockage.supprimer()` avant cet
    appel (voir `main.py::genome_enfant_supprimer`)."""
    with _conn() as c:
        c.execute("DELETE FROM placements WHERE enfant_id=?", (enfant_id,))


def forker_monde(cle_api: str, monde_id: str) -> dict | None:
    """Clone un monde : mêmes cellules (mêmes cellule_id, biomes, ressources,
    voisins — pas de régénération) et mêmes placements, sous un nouvel id. Le
    monde source n'est jamais modifié."""
    with _conn() as c:
        m = c.execute("SELECT * FROM mondes WHERE id=? AND cle_api=?", (monde_id, cle_api)).fetchone()
        if m is None:
            return None
        nid = uuid.uuid4().hex
        cree_le = datetime.now(timezone.utc).isoformat()
        c.execute("INSERT INTO mondes (id, cle_api, nb_cellules, seed, forked_from_id, cree_le) "
                   "VALUES (?,?,?,?,?,?)",
                   (nid, cle_api, m["nb_cellules"], m["seed"], monde_id, cree_le))
        cellules = c.execute("SELECT * FROM cellules WHERE monde_id=?", (monde_id,)).fetchall()
        c.executemany(
            "INSERT INTO cellules (monde_id, cellule_id, x, y, biome, ressources, voisins) "
            "VALUES (?,?,?,?,?,?,?)",
            [(nid, r["cellule_id"], r["x"], r["y"], r["biome"], r["ressources"], r["voisins"])
             for r in cellules])
        placements = c.execute("SELECT * FROM placements WHERE monde_id=?", (monde_id,)).fetchall()
        c.executemany(
            "INSERT INTO placements (enfant_id, monde_id, cellule_id, place_le) VALUES (?,?,?,?)",
            [(r["enfant_id"], nid, r["cellule_id"], r["place_le"]) for r in placements])
    return {"id": nid, "nb_cellules": m["nb_cellules"], "seed": m["seed"],
            "forked_from_id": monde_id, "cree_le": cree_le}


def supprimer_monde(cle_api: str, monde_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM mondes WHERE id=? AND cle_api=?", (monde_id, cle_api))
        if cur.rowcount == 0:
            return False
        c.execute("DELETE FROM cellules WHERE monde_id=?", (monde_id,))
        c.execute("DELETE FROM placements WHERE monde_id=?", (monde_id,))
    return True
