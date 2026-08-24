"""Persistance SQLite des fédérations de pays (Sprint D) : regroupement de
mondes existants (chacun devenant un « pays » une fois rattaché), adjacences
déclarées entre pays — base de la migration transfrontière (horloge_moteur.py).
Même base (`WORLD_ENGINE_DB`) que les autres modules stockage_*.py, tables
séparées.

Une fédération peut mélanger des `cle_api` différentes (voir design) : le
cloisonnement n'est donc PAS un filtre `cle_api` systématique comme dans
stockage_spatial.py — chaque fonction documente précisément ce qu'elle
vérifie (ou ne vérifie pas, laissant `main.py` le faire en amont)."""
from __future__ import annotations

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
    c.execute("""CREATE TABLE IF NOT EXISTS federations (
        id TEXT PRIMARY KEY, nom TEXT, createur_cle_api TEXT NOT NULL, cree_le TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS federation_pays (
        federation_id TEXT NOT NULL, monde_id TEXT NOT NULL, cle_api TEXT NOT NULL,
        nom TEXT, rattache_le TEXT, PRIMARY KEY (federation_id, monde_id))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_federation_pays_monde ON federation_pays(monde_id)")
    c.execute("""CREATE TABLE IF NOT EXISTS federation_adjacences (
        federation_id TEXT NOT NULL, monde_id_a TEXT NOT NULL, monde_id_b TEXT NOT NULL,
        declaree_le TEXT, PRIMARY KEY (federation_id, monde_id_a, monde_id_b))""")
    return c


def _federation_row(c: sqlite3.Connection, federation_id: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM federations WHERE id=?", (federation_id,)).fetchone()


def _pays_row(c: sqlite3.Connection, federation_id: str, monde_id: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM federation_pays WHERE federation_id=? AND monde_id=?",
                      (federation_id, monde_id)).fetchone()


def _paire_normalisee(monde_id_a: str, monde_id_b: str) -> tuple[str, str]:
    """Tri par chaîne — une seule ligne par paire non ordonnée (voir design)."""
    return (monde_id_a, monde_id_b) if monde_id_a < monde_id_b else (monde_id_b, monde_id_a)


def creer_federation(cle_api: str, nom: str | None) -> dict:
    fid = uuid.uuid4().hex
    cree_le = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("INSERT INTO federations (id, nom, createur_cle_api, cree_le) VALUES (?,?,?,?)",
                   (fid, nom, cle_api, cree_le))
    return {"id": fid, "nom": nom, "createur_cle_api": cle_api, "cree_le": cree_le}


def rattacher_pays(federation_id: str, monde_id: str, cle_api: str, nom: str | None) -> dict | None:
    """`cle_api` DOIT être le propriétaire de `monde_id` — vérifié par l'APPELANT
    (main.py, via stockage_spatial.monde_existe) : ce module ne connaît pas la
    table `mondes` et ne peut pas le vérifier lui-même. Renvoie None si la
    fédération est absente."""
    rattache_le = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        if _federation_row(c, federation_id) is None:
            return None
        c.execute("INSERT OR REPLACE INTO federation_pays "
                   "(federation_id, monde_id, cle_api, nom, rattache_le) VALUES (?,?,?,?,?)",
                   (federation_id, monde_id, cle_api, nom, rattache_le))
    return {"federation_id": federation_id, "monde_id": monde_id, "nom": nom,
            "rattache_le": rattache_le}


def lire_federation(federation_id: str) -> dict | None:
    with _conn() as c:
        f = _federation_row(c, federation_id)
        if f is None:
            return None
        pays = c.execute("SELECT monde_id, nom, cle_api, rattache_le FROM federation_pays "
                          "WHERE federation_id=? ORDER BY rattache_le", (federation_id,)).fetchall()
        adj = c.execute("SELECT monde_id_a, monde_id_b FROM federation_adjacences "
                         "WHERE federation_id=? ORDER BY declaree_le", (federation_id,)).fetchall()
    return {"id": f["id"], "nom": f["nom"], "createur_cle_api": f["createur_cle_api"],
            "cree_le": f["cree_le"],
            "pays": [dict(r) for r in pays],
            "adjacences": [dict(r) for r in adj]}


def lister_federations(cle_api: str) -> list[dict]:
    """Fédérations où `cle_api` est créatrice OU possède au moins un pays membre."""
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT f.id, f.nom, f.createur_cle_api, f.cree_le FROM federations f "
            "LEFT JOIN federation_pays p ON p.federation_id = f.id "
            "WHERE f.createur_cle_api=? OR p.cle_api=? ORDER BY f.cree_le DESC",
            (cle_api, cle_api)).fetchall()
    return [dict(r) for r in rows]


def detacher_pays(federation_id: str, monde_id: str, cle_api: str) -> bool:
    """`cle_api` DOIT être le propriétaire ENREGISTRÉ de ce pays dans CETTE
    fédération (vérifié dans le DELETE lui-même, même motif que
    stockage_spatial.supprimer_monde). Retire aussi ses adjacences dans cette
    fédération. Renvoie False si aucune ligne ne correspondait (pays non membre,
    ou mauvaise cle_api — indistinguable, comme le reste du cloisonnement)."""
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM federation_pays WHERE federation_id=? AND monde_id=? AND cle_api=?",
            (federation_id, monde_id, cle_api))
        if cur.rowcount == 0:
            return False
        c.execute("DELETE FROM federation_adjacences WHERE federation_id=? AND "
                   "(monde_id_a=? OR monde_id_b=?)", (federation_id, monde_id, monde_id))
    return True


def membre(federation_id: str, cle_api: str) -> bool:
    """`cle_api` possède-t-elle au moins un pays membre de cette fédération ?
    (Le créateur d'une fédération SANS pays à lui n'est PAS "membre" au sens de
    cette fonction — voir design : le droit de déclarer une adjacence appartient
    aux membres, pas au créateur en tant que tel.)"""
    with _conn() as c:
        r = c.execute("SELECT 1 FROM federation_pays WHERE federation_id=? AND cle_api=?",
                       (federation_id, cle_api)).fetchone()
    return r is not None


def declarer_adjacence(federation_id: str, monde_id_a: str, monde_id_b: str) -> dict | None:
    """Renvoie None si la fédération, ou l'un des deux pays (pas encore membre de
    CETTE fédération), est absent. L'appelant (main.py) a déjà vérifié que la
    `cle_api` appelante est membre AVANT cet appel — cette fonction ne le
    revérifie pas."""
    a, b = _paire_normalisee(monde_id_a, monde_id_b)
    declaree_le = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        if _federation_row(c, federation_id) is None:
            return None
        if _pays_row(c, federation_id, a) is None or _pays_row(c, federation_id, b) is None:
            return None
        c.execute("INSERT OR REPLACE INTO federation_adjacences "
                   "(federation_id, monde_id_a, monde_id_b, declaree_le) VALUES (?,?,?,?)",
                   (federation_id, a, b, declaree_le))
    return {"federation_id": federation_id, "monde_id_a": a, "monde_id_b": b,
            "declaree_le": declaree_le}


def pays_adjacents(monde_id: str) -> list[str]:
    """Union (triée, dédupliquée) des pays adjacents à `monde_id` dans TOUTES les
    fédérations dont il est membre — utilisée par horloge_moteur.py pour résoudre
    les destinations de migration transfrontière. Un pays peut être adjacent au
    même voisin dans 2 fédérations distinctes : il n'apparaît qu'une fois."""
    with _conn() as c:
        rows = c.execute(
            "SELECT monde_id_a, monde_id_b FROM federation_adjacences "
            "WHERE monde_id_a=? OR monde_id_b=?", (monde_id, monde_id)).fetchall()
    voisins = {r["monde_id_b"] if r["monde_id_a"] == monde_id else r["monde_id_a"] for r in rows}
    return sorted(voisins)


def supprimer_federation(cle_api: str, federation_id: str) -> bool:
    """Cascade `federation_pays` + `federation_adjacences` — ne touche JAMAIS
    `mondes`/`cellules`/`placements` (les pays sous-jacents survivent, redevenus
    indépendants). `cle_api` DOIT être `createur_cle_api` (vérifié dans le DELETE
    lui-même, même motif que `detacher_pays`)."""
    with _conn() as c:
        cur = c.execute("DELETE FROM federations WHERE id=? AND createur_cle_api=?",
                         (federation_id, cle_api))
        if cur.rowcount == 0:
            return False
        c.execute("DELETE FROM federation_pays WHERE federation_id=?", (federation_id,))
        c.execute("DELETE FROM federation_adjacences WHERE federation_id=?", (federation_id,))
    return True


def population_vivante_federation(federation_id: str) -> dict | None:
    """Agrégat pour `GET /federation/{id}/etat` : population vivante (actuellement
    `vivant=1` seulement ; filtrage `emigre=0` non encore appliqué car la colonne
    `emigre` n'existe pas encore sur `placements`). Par pays membre + total. Lit
    `placements` (propriété de stockage_spatial.py, même base SQLite) SANS en
    dupliquer la DDL — même hypothèse que stockage_horloge.horloges_actives_a_declencher :
    un pays n'est rattachable (voir rattacher_pays) que s'il existe déjà, donc la table
    `placements` existe forcément par construction dès qu'il y a ≥1 pays membre."""
    with _conn() as c:
        if _federation_row(c, federation_id) is None:
            return None
        membres = c.execute("SELECT monde_id FROM federation_pays WHERE federation_id=?",
                             (federation_id,)).fetchall()
        par_pays = []
        total = 0
        for r in membres:
            mid = r["monde_id"]
            # TODO(Task 2): Once stockage_spatial.py adds `emigre` column to `placements`,
            # update this query to: WHERE monde_id=? AND vivant=1 AND emigre=0 to avoid
            # double-counting habitants who have emigrated to adjacent countries.
            n = c.execute(
                "SELECT COUNT(*) AS n FROM placements WHERE monde_id=? AND vivant=1",
                (mid,)).fetchone()["n"]
            par_pays.append({"monde_id": mid, "population_vivante": n})
            total += n
    return {"federation_id": federation_id, "pays": par_pays, "population_totale": total}
