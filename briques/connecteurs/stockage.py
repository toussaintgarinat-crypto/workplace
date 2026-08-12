"""Stockage SQLite de la brique `connecteurs` (S214).

Trois tables, et une frontière nette avec PyAirbyte :

  • `sources`  — ce que l'opérateur déclare : un connecteur (`source-github`), une
                 configuration **chiffrée** (`coffre.py`), les flux retenus.
  • `syncs`    — la comptabilité d'exécution : début, fin, statut, volume, erreur.
                 C'est CE que l'assistant lit ; il ne voit jamais le cache PyAirbyte.
  • `etats`    — le curseur incrémental sérialisé, par (source, flux).

**Pourquoi `etats` ici alors que PyAirbyte tient déjà l'état dans son cache DuckDB.**
Parce que le critère de sortie du sprint est « l'état est *vérifié* ». Un état qui ne
vit que dans le cache d'une librairie tierce n'est ni inspectable par une route, ni
comparable d'une sync à l'autre, ni sauvegardable avec le reste de la brique. On garde
donc le cache DuckDB comme destination des DONNÉES (décision de l'ADR : pas d'entrepôt)
et on recopie l'ÉTAT ici, à chaque point de reprise. C'est la seule duplication assumée.

Isolation par tenant : motif `veille-info` (S185) — toute lecture est scopée, aucune
route ne peut lister les sources d'un autre.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import coffre

DB_CHEMIN = Path(os.getenv("CONNECTEURS_DB", "/data/connecteurs.db"))

STATUTS_SYNC = ("en_cours", "ok", "echec", "interrompue")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    DB_CHEMIN.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_CHEMIN)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def initialiser() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant          TEXT    NOT NULL,
                nom             TEXT    NOT NULL,
                connecteur      TEXT    NOT NULL,
                config_chiffree TEXT    NOT NULL,
                flux            TEXT    NOT NULL DEFAULT '[]',
                active          INTEGER NOT NULL DEFAULT 1,
                cree_le         TEXT    NOT NULL,
                UNIQUE (tenant, nom)
            );
            CREATE TABLE IF NOT EXISTS syncs (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant             TEXT    NOT NULL,
                source_id          INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                statut             TEXT    NOT NULL,
                debut              TEXT    NOT NULL,
                fin                TEXT,
                nb_enregistrements INTEGER NOT NULL DEFAULT 0,
                erreur             TEXT
            );
            CREATE TABLE IF NOT EXISTS etats (
                source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                flux       TEXT    NOT NULL,
                curseur    TEXT    NOT NULL,
                maj_le     TEXT    NOT NULL,
                PRIMARY KEY (source_id, flux)
            );
            CREATE INDEX IF NOT EXISTS idx_syncs_source ON syncs(source_id, id DESC);
            """
        )
        # Migration S230 : lien source ↔ dossier client (venture Forge), pour que le
        # mappeur best-effort sache où pousser CRM/ROI. NULL = source « ancien format »
        # ou non liée à un dossier — reste valide (motif « ancien format » établi).
        cols = {r["name"] for r in con.execute("PRAGMA table_info(sources)").fetchall()}
        if "venture_id" not in cols:
            con.execute("ALTER TABLE sources ADD COLUMN venture_id TEXT")


# ── Sources ──────────────────────────────────────────────────────────────────

def _vue_source(r: sqlite3.Row) -> dict:
    """Vue publique d'une source : la config est RENDUE MASQUÉE, jamais en clair."""
    return {
        "id": r["id"],
        "nom": r["nom"],
        "connecteur": r["connecteur"],
        "flux": json.loads(r["flux"]),
        "active": bool(r["active"]),
        "cree_le": r["cree_le"],
        "venture_id": r["venture_id"],
        "config": coffre.masquer(coffre.dechiffrer(r["config_chiffree"])),
    }


def creer_source(tenant: str, nom: str, connecteur: str, config: dict,
                 flux: list[str] | None = None, venture_id: str | None = None) -> dict:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO sources (tenant, nom, connecteur, config_chiffree, flux,"
            " venture_id, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant, nom, connecteur, coffre.chiffrer(config),
             json.dumps(flux or []), venture_id, _maintenant()),
        )
        r = con.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _vue_source(r)


def lister_sources(tenant: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM sources WHERE tenant = ? ORDER BY id", (tenant,)).fetchall()
        return [_vue_source(r) for r in rows]


def source_get(tenant: str, source_id: int) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM sources WHERE tenant = ? AND id = ?",
                        (tenant, source_id)).fetchone()
        return _vue_source(r) if r else None


def config_de(tenant: str, source_id: int) -> tuple[str, dict, list[str]] | None:
    """(connecteur, config EN CLAIR, flux) — réservé au pont, jamais rendu par une route."""
    with _conn() as con:
        r = con.execute("SELECT * FROM sources WHERE tenant = ? AND id = ?",
                        (tenant, source_id)).fetchone()
        if r is None:
            return None
        return r["connecteur"], coffre.dechiffrer(r["config_chiffree"]), json.loads(r["flux"])


def venture_id_de(source_id: int) -> str | None:
    """Réservé au mappeur best-effort — appelé APRÈS que `_syncer` a déjà validé
    `(tenant, source_id)` via `config_de`."""
    with _conn() as con:
        r = con.execute("SELECT venture_id FROM sources WHERE id = ?", (source_id,)).fetchone()
        return r["venture_id"] if r else None


def modifier_source(tenant: str, source_id: int, *, config: dict | None = None,
                    flux: list[str] | None = None, active: bool | None = None,
                    venture_id: str | None = None) -> bool:
    champs, valeurs = [], []
    if config is not None:
        champs.append("config_chiffree = ?")
        valeurs.append(coffre.chiffrer(config))
    if flux is not None:
        champs.append("flux = ?")
        valeurs.append(json.dumps(flux))
    if active is not None:
        champs.append("active = ?")
        valeurs.append(int(active))
    if venture_id is not None:
        champs.append("venture_id = ?")
        valeurs.append(venture_id)
    if not champs:
        return source_get(tenant, source_id) is not None
    with _conn() as con:
        cur = con.execute(
            f"UPDATE sources SET {', '.join(champs)} WHERE tenant = ? AND id = ?",
            (*valeurs, tenant, source_id))
        return cur.rowcount > 0


def supprimer_source(tenant: str, source_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM sources WHERE tenant = ? AND id = ?",
                          (tenant, source_id))
        return cur.rowcount > 0


def sources_actives() -> list[tuple[str, int]]:
    """(tenant, source_id) de TOUTES les sources actives — pour la tâche horloge, qui
    traite le parc entier en un appel et n'est donc scopée à aucun tenant."""
    with _conn() as con:
        rows = con.execute(
            "SELECT tenant, id FROM sources WHERE active = 1 ORDER BY id").fetchall()
        return [(r["tenant"], r["id"]) for r in rows]


# ── Syncs ────────────────────────────────────────────────────────────────────

def ouvrir_sync(tenant: str, source_id: int) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO syncs (tenant, source_id, statut, debut) VALUES (?, ?, 'en_cours', ?)",
            (tenant, source_id, _maintenant()))
        return int(cur.lastrowid)


def cloturer_sync(sync_id: int, statut: str, *, nb_enregistrements: int = 0,
                  erreur: str | None = None) -> None:
    if statut not in STATUTS_SYNC:
        raise ValueError(f"statut de sync inconnu : {statut}")
    with _conn() as con:
        con.execute(
            "UPDATE syncs SET statut = ?, fin = ?, nb_enregistrements = ?, erreur = ?"
            " WHERE id = ?",
            (statut, _maintenant(), nb_enregistrements, erreur, sync_id))


def avancer_sync(sync_id: int, nb_enregistrements: int) -> None:
    """Met à jour le volume d'une sync EN COURS — sans quoi une sync interrompue
    rapporterait 0 enregistrement alors qu'elle en a bien transféré (et l'opérateur
    croirait avoir tout perdu)."""
    with _conn() as con:
        con.execute("UPDATE syncs SET nb_enregistrements = ? WHERE id = ?",
                    (nb_enregistrements, sync_id))


def _vue_sync(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "source_id": r["source_id"], "statut": r["statut"],
        "debut": r["debut"], "fin": r["fin"],
        "nb_enregistrements": r["nb_enregistrements"], "erreur": r["erreur"],
    }


def lister_syncs(tenant: str, source_id: int | None = None, limite: int = 50) -> list[dict]:
    where, params = ["tenant = ?"], [tenant]
    if source_id is not None:
        where.append("source_id = ?")
        params.append(source_id)
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM syncs WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
            (*params, limite)).fetchall()
        return [_vue_sync(r) for r in rows]


def sync_get(tenant: str, sync_id: int) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM syncs WHERE tenant = ? AND id = ?",
                        (tenant, sync_id)).fetchone()
        return _vue_sync(r) if r else None


def rouvrir_syncs_orphelines() -> int:
    """Au démarrage : toute sync restée `en_cours` est le vestige d'un processus tué
    (redémarrage du conteneur en plein transfert). Elle est marquée `interrompue`, pas
    laissée à mentir « en cours » pour l'éternité. Renvoie le nombre de sync reprises.

    Ce n'est pas cosmétique : c'est ce qui rend la reprise VISIBLE. Sans ça, l'opérateur
    ne peut pas distinguer une sync qui travaille d'une sync morte il y a trois jours.
    """
    with _conn() as con:
        cur = con.execute(
            "UPDATE syncs SET statut = 'interrompue', fin = ?,"
            " erreur = 'processus interrompu (redémarrage) — la sync suivante reprendra"
            " au dernier curseur enregistré' WHERE statut = 'en_cours'",
            (_maintenant(),))
        return cur.rowcount


# ── États (curseurs incrémentaux) ────────────────────────────────────────────

def enregistrer_etat(source_id: int, flux: str, curseur: dict) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO etats (source_id, flux, curseur, maj_le) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(source_id, flux) DO UPDATE SET curseur = excluded.curseur,"
            " maj_le = excluded.maj_le",
            (source_id, flux, json.dumps(curseur, ensure_ascii=False), _maintenant()))


def lire_etats(source_id: int) -> dict[str, dict]:
    """{flux: curseur} — ce qu'on repasse au connecteur pour qu'il reprenne."""
    with _conn() as con:
        rows = con.execute("SELECT flux, curseur FROM etats WHERE source_id = ?",
                           (source_id,)).fetchall()
        return {r["flux"]: json.loads(r["curseur"]) for r in rows}


def etats_vue(source_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT flux, curseur, maj_le FROM etats WHERE source_id = ? ORDER BY flux",
            (source_id,)).fetchall()
        return [{"flux": r["flux"], "curseur": json.loads(r["curseur"]),
                 "maj_le": r["maj_le"]} for r in rows]


def oublier_etats(source_id: int) -> int:
    """Remise à zéro explicite : la prochaine sync repartira du début (full refresh)."""
    with _conn() as con:
        cur = con.execute("DELETE FROM etats WHERE source_id = ?", (source_id,))
        return cur.rowcount
