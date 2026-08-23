"""Persistance SQLite de l'horloge de simulation (Sprint C) : état de l'horloge
d'un monde (tick_actuel, actif, intervalle) et couples d'habitants. Même base
(`WORLD_ENGINE_DB`) que stockage.py/stockage_spatial.py, tables séparées.

⚠️ `horloges_actives_a_declencher` JOINT avec la table `mondes` (pour connaître
`cle_api`, nécessaire au scheduler qui n'a pas de contexte de requête) sans en
dupliquer la DDL ici : ce module suppose qu'un monde existe TOUJOURS avant que son
horloge ne soit créée (`initialiser_horloge` n'est appelée qu'après
`stockage_spatial.creer_monde`, voir `main.py`), donc la table `mondes` existe déjà
par construction au moment où cette jointure s'exécute."""
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
    c.execute("""CREATE TABLE IF NOT EXISTS horloges (
        monde_id TEXT PRIMARY KEY, tick_actuel INTEGER NOT NULL DEFAULT 0,
        actif INTEGER NOT NULL DEFAULT 0, intervalle_secondes INTEGER,
        derniere_execution TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS couples (
        id TEXT PRIMARY KEY, monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        habitant_a_id TEXT NOT NULL, habitant_b_id TEXT NOT NULL,
        forme_au_tick INTEGER NOT NULL, actif INTEGER NOT NULL DEFAULT 1,
        dissous_au_tick INTEGER)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_couple_monde ON couples(monde_id)")
    return c


def initialiser_horloge(monde_id: str) -> None:
    """Appelée juste après la création (ou le fork, via `copier_pour_fork`) d'un
    monde — un monde a TOUJOURS une horloge, en tick manuel (`actif=0`) par défaut."""
    with _conn() as c:
        c.execute("INSERT INTO horloges (monde_id, tick_actuel, actif) VALUES (?, 0, 0)", (monde_id,))


def lire_horloge(monde_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM horloges WHERE monde_id=?", (monde_id,)).fetchone()
    if r is None:
        return None
    return {"monde_id": r["monde_id"], "tick_actuel": r["tick_actuel"], "actif": bool(r["actif"]),
            "intervalle_secondes": r["intervalle_secondes"], "derniere_execution": r["derniere_execution"]}


def demarrer(monde_id: str, intervalle_secondes: int) -> None:
    with _conn() as c:
        c.execute("UPDATE horloges SET actif=1, intervalle_secondes=? WHERE monde_id=?",
                   (intervalle_secondes, monde_id))


def arreter(monde_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE horloges SET actif=0 WHERE monde_id=?", (monde_id,))


def marquer_execution(monde_id: str, tick_actuel: int) -> None:
    """Avance `tick_actuel` et horodate `derniere_execution` — appelée après CHAQUE
    tick, manuel ou automatique : un tick manuel repousse aussi la prochaine
    échéance du scheduler (comportement volontaire, pas un oubli)."""
    with _conn() as c:
        c.execute("UPDATE horloges SET tick_actuel=?, derniere_execution=? WHERE monde_id=?",
                   (tick_actuel, datetime.now(timezone.utc).isoformat(), monde_id))


def horloges_actives_a_declencher(maintenant_iso: str) -> list[dict]:
    """Horloges en mode automatique (`actif=1`) dont l'intervalle est écoulé (ou
    jamais encore exécutées) — jointure avec `mondes` pour connaître `cle_api` (le
    scheduler n'a pas de contexte de requête HTTP)."""
    maintenant = datetime.fromisoformat(maintenant_iso)
    with _conn() as c:
        rows = c.execute(
            "SELECT h.monde_id AS monde_id, h.tick_actuel AS tick_actuel, "
            "h.intervalle_secondes AS intervalle_secondes, h.derniere_execution AS derniere_execution, "
            "m.cle_api AS cle_api FROM horloges h JOIN mondes m ON h.monde_id = m.id WHERE h.actif=1"
        ).fetchall()
    dues = []
    for r in rows:
        if r["derniere_execution"] is None:
            dues.append(dict(r))
            continue
        ecart = (maintenant - datetime.fromisoformat(r["derniere_execution"])).total_seconds()
        if ecart >= r["intervalle_secondes"]:
            dues.append(dict(r))
    return dues


def copier_pour_fork(monde_source_id: str, nouveau_monde_id: str) -> None:
    """Copie l'état de l'horloge source (`tick_actuel`) dans le fork, mais force
    `actif=0` : un fork ne démarre jamais silencieusement son propre scheduler.
    Copie aussi les couples ACTIFS du monde source (référencent des habitants qui
    existent bien dans le fork, puisque `stockage_spatial.forker_monde` duplique
    déjà les placements)."""
    with _conn() as c:
        source = c.execute("SELECT tick_actuel FROM horloges WHERE monde_id=?",
                            (monde_source_id,)).fetchone()
        tick_actuel = source["tick_actuel"] if source else 0
        c.execute("INSERT INTO horloges (monde_id, tick_actuel, actif) VALUES (?, ?, 0)",
                   (nouveau_monde_id, tick_actuel))
        actifs = c.execute("SELECT * FROM couples WHERE monde_id=? AND actif=1",
                            (monde_source_id,)).fetchall()
        c.executemany(
            "INSERT INTO couples (id, monde_id, cellule_id, habitant_a_id, habitant_b_id, "
            "forme_au_tick, actif) VALUES (?,?,?,?,?,?,1)",
            [(uuid.uuid4().hex, nouveau_monde_id, r["cellule_id"], r["habitant_a_id"],
              r["habitant_b_id"], r["forme_au_tick"]) for r in actifs])


def supprimer_pour_monde(monde_id: str) -> None:
    """Cascade appelée par `main.py` après un `stockage_spatial.supprimer_monde`
    réussi (même motif que `stockage_spatial.supprimer_placements_enfant`)."""
    with _conn() as c:
        c.execute("DELETE FROM horloges WHERE monde_id=?", (monde_id,))
        c.execute("DELETE FROM couples WHERE monde_id=?", (monde_id,))


def former_couple(monde_id: str, cellule_id: int, habitant_a_id: str, habitant_b_id: str,
                   tick: int) -> str:
    cid = uuid.uuid4().hex
    with _conn() as c:
        c.execute("INSERT INTO couples (id, monde_id, cellule_id, habitant_a_id, habitant_b_id, "
                   "forme_au_tick, actif) VALUES (?,?,?,?,?,?,1)",
                   (cid, monde_id, cellule_id, habitant_a_id, habitant_b_id, tick))
    return cid


def dissoudre_couple(couple_id: str, tick: int) -> None:
    with _conn() as c:
        c.execute("UPDATE couples SET actif=0, dissous_au_tick=? WHERE id=?", (tick, couple_id))


def couples_actifs_cellule(monde_id: str, cellule_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM couples WHERE monde_id=? AND cellule_id=? AND actif=1",
                          (monde_id, cellule_id)).fetchall()
    return [dict(r) for r in rows]
