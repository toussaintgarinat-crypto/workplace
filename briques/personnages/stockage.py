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
    # Fiches cosmiques enregistrées (opt-in) : le portrait holistique reste STATELESS ;
    # on ne stocke que sur action délibérée. `donnees` = snapshot complet (JSON).
    # `nom` = nom affiché (renommable, p.ex. nom de scène d'une série) ; `nom_naissance`
    # = nom cosmique d'origine, FIGÉ à la création (on garde toujours les deux).
    c.execute("""CREATE TABLE IF NOT EXISTS fiches (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, nom TEXT, nom_naissance TEXT,
        archetype TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fiche_cle ON fiches(cle_api)")
    # Migration douce : ajoute nom_naissance aux bases créées avant cette colonne.
    cols = {r[1] for r in c.execute("PRAGMA table_info(fiches)")}
    if "nom_naissance" not in cols:
        c.execute("ALTER TABLE fiches ADD COLUMN nom_naissance TEXT")
        c.execute("UPDATE fiches SET nom_naissance=nom WHERE nom_naissance IS NULL")
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


# ── Fiches cosmiques enregistrées (couche stateful du moteur holistique) ──
def creer_fiche(cle_api: str, nom: str, donnees: dict | None = None) -> dict:
    """Enregistre une fiche cosmique (snapshot complet). Renvoie le résumé (sans le blob).

    `nom_naissance` est figé sur le nom de création : même renommée plus tard pour une
    série, la fiche garde la trace de son nom cosmique d'origine."""
    donnees = donnees or {}
    archetype = ((donnees.get("portrait") or {}).get("archetype")) or ""
    nom = nom or "Personnage"
    f = {"id": uuid.uuid4().hex, "nom": nom, "nom_naissance": nom, "archetype": archetype,
         "cree_le": datetime.now(timezone.utc).isoformat()}
    with _conn() as c:
        # Colonnes NOMMÉES (pas positionnel) : sur une base migrée, ALTER ADD COLUMN
        # nom_naissance se range en fin de table → l'ordre diffère d'une base neuve.
        c.execute("""INSERT INTO fiches (id, cle_api, nom, nom_naissance, archetype, donnees, cree_le)
                     VALUES (?,?,?,?,?,?,?)""",
                  (f["id"], cle_api, f["nom"], f["nom_naissance"], f["archetype"],
                   json.dumps(donnees, ensure_ascii=False), f["cree_le"]))
    return f


def lister_fiches(cle_api: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, nom, nom_naissance, archetype, cree_le FROM fiches "
            "WHERE cle_api=? ORDER BY cree_le DESC", (cle_api,)).fetchall()
    return [{"id": r["id"], "nom": r["nom"], "nom_naissance": r["nom_naissance"],
             "archetype": r["archetype"], "cree_le": r["cree_le"]} for r in rows]


def lire_fiche(cle_api: str, fid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM fiches WHERE id=? AND cle_api=?", (fid, cle_api)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "nom": r["nom"], "nom_naissance": r["nom_naissance"],
            "archetype": r["archetype"], "donnees": json.loads(r["donnees"]),
            "cree_le": r["cree_le"]}


def renommer_fiche(cle_api: str, fid: str, nom: str) -> dict | None:
    """Change le nom AFFICHÉ d'une fiche (p.ex. nom de scène pour une série) sans toucher
    au nom_naissance ni aux données cosmiques. Renvoie le résumé, ou None si introuvable."""
    nom = (nom or "").strip()
    if not nom:
        return None
    with _conn() as c:
        cur = c.execute("UPDATE fiches SET nom=? WHERE id=? AND cle_api=?",
                        (nom, fid, cle_api))
        if cur.rowcount == 0:
            return None
    f = lire_fiche(cle_api, fid)
    return {k: f[k] for k in ("id", "nom", "nom_naissance", "archetype", "cree_le")}


def supprimer_fiche(cle_api: str, fid: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM fiches WHERE id=? AND cle_api=?", (fid, cle_api))
    return cur.rowcount > 0
