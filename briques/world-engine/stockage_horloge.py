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
import random
from datetime import datetime, timedelta, timezone
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


def _monde_existe(c: sqlite3.Connection, monde_id: str) -> bool:
    """Le monde existe-t-il dans la table `mondes` (propriété de
    `stockage_spatial.py`) ? Même hypothèse que `horloges_actives_a_declencher` :
    on LIT `mondes` sans en dupliquer la DDL (voir docstring du module). Repli
    honnête si la table n'existe pas encore (base vierge, aucun monde jamais
    créé) : aucun monde n'existe, donc False — jamais une exception."""
    try:
        return c.execute("SELECT 1 FROM mondes WHERE id=?", (monde_id,)).fetchone() is not None
    except sqlite3.OperationalError:
        return False


def lire_horloge(monde_id: str) -> dict | None:
    """État de l'horloge d'un monde, ou None si le MONDE lui-même n'existe pas.

    Correctif revue finale (Important) — rattrapage paresseux : un monde qui
    existe bien mais n'a AUCUNE ligne `horloges` (monde antérieur au Sprint C, ou
    `initialiser_horloge` échouée après un `creer_monde`/`forker_monde` déjà
    commité) reçoit ici une ligne par défaut (`tick_actuel=0, actif=0`) au lieu de
    faire renvoyer `200 null` à `GET /horloge/{id}` et de laisser
    `demarrer`/`arreter` faire un UPDATE silencieux sur zéro ligne."""
    with _conn() as c:
        r = c.execute("SELECT * FROM horloges WHERE monde_id=?", (monde_id,)).fetchone()
        if r is None:
            if not _monde_existe(c, monde_id):
                return None
            c.execute("INSERT INTO horloges (monde_id, tick_actuel, actif) VALUES (?, 0, 0)",
                       (monde_id,))
            r = c.execute("SELECT * FROM horloges WHERE monde_id=?", (monde_id,)).fetchone()
    return {"monde_id": r["monde_id"], "tick_actuel": r["tick_actuel"], "actif": bool(r["actif"]),
            "intervalle_secondes": r["intervalle_secondes"], "derniere_execution": r["derniere_execution"]}


def demarrer(monde_id: str, intervalle_secondes: int) -> None:
    """`lire_horloge` d'abord : garantit la ligne `horloges` (rattrapage paresseux)
    pour que l'UPDATE ci-dessous ne porte jamais sur zéro ligne en silence.

    Jitter au tout premier démarrage (`derniere_execution` encore `NULL`) : évite
    que plusieurs mondes démarrés ensemble avec le même intervalle restent
    perpétuellement dus au même instant (mesuré en LIVE, Sprint E — voir
    docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md).
    Un monde déjà tické avant garde sa phase existante : `derniere_execution`
    n'est pas modifié dans ce cas."""
    horloge = lire_horloge(monde_id)
    with _conn() as c:
        if horloge["derniere_execution"] is None:
            derniere_execution_initiale = (
                datetime.now(timezone.utc) - timedelta(seconds=random.uniform(0, intervalle_secondes))
            ).isoformat()
            c.execute(
                "UPDATE horloges SET actif=1, intervalle_secondes=?, derniere_execution=? WHERE monde_id=?",
                (intervalle_secondes, derniere_execution_initiale, monde_id))
        else:
            c.execute("UPDATE horloges SET actif=1, intervalle_secondes=? WHERE monde_id=?",
                       (intervalle_secondes, monde_id))


def arreter(monde_id: str) -> None:
    """Même rattrapage paresseux que `demarrer`."""
    lire_horloge(monde_id)
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


def former_couples_lot(monde_id: str, couples: list[tuple[int, str, str]], tick: int) -> list[str]:
    """Version lot de `former_couple` (`(cellule_id, habitant_a_id, habitant_b_id)`),
    en une seule connexion/transaction — voir `couples_actifs_monde` pour le
    pourquoi. Renvoie les ids créés, dans l'ordre reçu."""
    ids = [uuid.uuid4().hex for _ in couples]
    with _conn() as c:
        c.executemany(
            "INSERT INTO couples (id, monde_id, cellule_id, habitant_a_id, habitant_b_id, "
            "forme_au_tick, actif) VALUES (?,?,?,?,?,?,1)",
            [(cid, monde_id, cellule_id, a, b, tick)
             for cid, (cellule_id, a, b) in zip(ids, couples)])
    return ids


def dissoudre_couple(couple_id: str, tick: int) -> None:
    with _conn() as c:
        c.execute("UPDATE couples SET actif=0, dissous_au_tick=? WHERE id=?", (tick, couple_id))


def dissoudre_couples(couple_ids: list[str], tick: int) -> None:
    """Version lot de `dissoudre_couple`, en une seule connexion/transaction — voir
    `couples_actifs_monde`."""
    with _conn() as c:
        c.executemany("UPDATE couples SET actif=0, dissous_au_tick=? WHERE id=?",
                       [(tick, cid) for cid in couple_ids])


def deplacer_couples_habitants(monde_id: str, deplacements: list[tuple[str, int]]) -> None:
    """Recale la `cellule_id` des couples ACTIFS des habitants qui viennent de
    migrer (`(habitant_id, nouvelle_cellule_id)`), en une seule
    connexion/transaction.

    Correctif revue finale (Important) : les couples étant indexés par cellule,
    un migrant dont le couple restait dans la cellule d'origine n'apparaissait plus
    « en couple » dans sa cellule d'arrivée et pouvait y former un SECOND couple
    actif — violation de l'invariant applicatif du design (« un habitant n'a au
    plus qu'un couple actif à la fois »), pendant que son couple d'origine restait
    actif dans une cellule où il n'habite plus.

    ⚠️ Si les DEUX membres d'un couple migrent vers des cellules DIFFÉRENTES le
    même tick, la dernière écriture gagne : le couple suit l'un des deux. Le design
    ne tranche pas ce cas (pas de dissolution pour éloignement) — comportement
    assumé, pas un oubli."""
    with _conn() as c:
        c.executemany(
            "UPDATE couples SET cellule_id=? WHERE monde_id=? AND "
            "(habitant_a_id=? OR habitant_b_id=?) AND actif=1",
            [(cel, monde_id, hid, hid) for hid, cel in deplacements])


def couples_actifs_cellule(monde_id: str, cellule_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM couples WHERE monde_id=? AND cellule_id=? AND actif=1",
                          (monde_id, cellule_id)).fetchall()
    return [dict(r) for r in rows]


def couples_actifs_monde(monde_id: str) -> dict[int, list[dict]]:
    """Version « tout le monde en une requête » de `couples_actifs_cellule`, groupée
    par `cellule_id`.

    Correctif revue finale (Critical) : `horloge_moteur.executer_tick` ouvrait une
    connexion SQLite PAR CELLULE pour lire les couples — voir
    `stockage_spatial.population_vivante_monde` pour la mesure et le détail.
    `couples_actifs_cellule` reste en place pour les autres appelants/tests.

    Une cellule sans couple actif est ABSENTE du dict (utiliser `.get(cid, [])`)."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM couples WHERE monde_id=? AND actif=1",
                          (monde_id,)).fetchall()
    par_cellule: dict[int, list[dict]] = {}
    for r in rows:
        par_cellule.setdefault(r["cellule_id"], []).append(dict(r))
    return par_cellule
