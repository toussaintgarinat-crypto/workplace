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


def _colonne_absente(c: sqlite3.Connection, table: str, colonne: str) -> bool:
    infos = c.execute(f"PRAGMA table_info({table})").fetchall()
    return colonne not in {row[1] for row in infos}


def _ajouter_colonne(c: sqlite3.Connection, table: str, colonne: str, ddl_type: str) -> None:
    """Migration idempotente : sans le contrôle PRAGMA, `ALTER TABLE ADD COLUMN`
    échouerait sur une base déjà migrée (colonne déjà présente)."""
    if _colonne_absente(c, table, colonne):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {ddl_type}")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    # DUPLIQUÉE dans stockage_spatial.py::_conn() (fix latent Task 2 : GET
    # /spatial/mondes/{id} 500ait sur une DB fraîche sans cette table). Le schéma DOIT
    # rester identique entre les deux copies — test_stockage_spatial.py::
    # test_ddl_enfants_identique_a_stockage pince les deux en synchro.
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, sexe TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    _ajouter_colonne(c, "enfants", "sexe", "TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_enfant_cle ON enfants(cle_api)")
    return c


def _ligne_complete(r: sqlite3.Row) -> dict:
    d = json.loads(r["donnees"])
    return {"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
            "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"], "sexe": r["sexe"],
            "theme": d["theme"], "description_genome": d["description_genome"],
            "heredite": d["heredite"], "mutation_survenue": d["mutation_survenue"],
            "cree_le": r["cree_le"]}


def creer(cle_api: str, prenoms: str, nom: str, parent_a_id: str | None, parent_b_id: str | None,
          theme: dict, description_genome: str, heredite: dict, mutation_survenue: bool,
          sexe: str | None = None) -> str:
    """Persiste un enfant généré par un croisement. Renvoie son id.

    `theme` = snapshot COMPLET renvoyé par `personnages` (traditions/portrait/
    theme_complet) — la même forme qu'une fiche parent en sortie de
    `personnages_client.portrait`, pour pouvoir être réinjecté tel quel comme
    parent d'un croisement suivant sans rappeler `personnages`.

    `sexe` (Sprint C) : trait persistant de l'enfant — nécessaire à l'horloge pour
    apparier des couples F/M au fil des ticks (contrairement au `sexe` transitoire de
    `ParentInput` en Sprint B, qui ne désignait qu'un rôle dans UN croisement, jamais
    stocké). Absent (`None`) ⇒ l'horloge ne pourra jamais apparier cet enfant."""
    eid = uuid.uuid4().hex
    donnees = {"theme": theme, "description_genome": description_genome,
               "heredite": heredite, "mutation_survenue": mutation_survenue}
    with _conn() as c:
        c.execute("""INSERT INTO enfants (id, cle_api, prenoms, nom, parent_a_id, parent_b_id,
                     sexe, donnees, cree_le) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (eid, cle_api, prenoms or "", nom or "", parent_a_id, parent_b_id, sexe,
                   json.dumps(donnees, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return eid


def lister(cle_api: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, prenoms, nom, parent_a_id, parent_b_id, sexe, cree_le FROM enfants "
            "WHERE cle_api=? ORDER BY cree_le DESC", (cle_api,)).fetchall()
    return [{"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
             "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"], "sexe": r["sexe"],
             "cree_le": r["cree_le"]} for r in rows]


def lire(cle_api: str, eid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM enfants WHERE id=? AND cle_api=?", (eid, cle_api)).fetchone()
    return _ligne_complete(r) if r else None


def transferer_proprietaire(enfant_id: str, nouvelle_cle_api: str) -> None:
    """Change le propriétaire (`cle_api`) d'un enfant — utilisé par la migration
    transfrontière (Sprint D) : un habitant émigré devient la propriété du tenant
    du pays destination (« il vit là-bas maintenant »).

    C'est la condition NÉCESSAIRE pour qu'il reste reproductible dans son nouveau
    pays : le tick de destination appelle `genome_moteur.executer_croisement(...,
    cle_api_destination)`, qui résout ses parents par `lire(cle_api, parent_id)`
    — cloisonné. Sans ce transfert, un migrant arrivé chez un tenant différent
    échouait silencieusement à toute naissance (« enfant stocké introuvable »
    dans les `avertissements` du tick) et restait stérile à jamais.

    ⚠️ Ne vérifie PAS le propriétaire actuel : l'appelant (horloge_moteur.py) a
    déjà établi le droit du migrant à partir (adjacence déclarée au sein d'une
    fédération dont son pays est membre, voir design) — jamais appelée depuis une
    requête HTTP."""
    with _conn() as c:
        c.execute("UPDATE enfants SET cle_api=? WHERE id=?", (nouvelle_cle_api, enfant_id))


def supprimer(cle_api: str, eid: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM enfants WHERE id=? AND cle_api=?", (eid, cle_api))
    return cur.rowcount > 0
