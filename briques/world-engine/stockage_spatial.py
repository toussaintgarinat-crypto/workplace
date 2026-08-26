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


def _colonne_absente(c: sqlite3.Connection, table: str, colonne: str) -> bool:
    infos = c.execute(f"PRAGMA table_info({table})").fetchall()
    return colonne not in {row[1] for row in infos}


def _ajouter_colonne(c: sqlite3.Connection, table: str, colonne: str, ddl_type: str) -> bool:
    """Migration idempotente : sans le contrôle PRAGMA, `ALTER TABLE ADD COLUMN`
    échouerait sur une base déjà migrée (colonne déjà présente). Renvoie True
    UNIQUEMENT quand la colonne vient d'être ajoutée — permet de brancher un
    remplissage rétroactif qui ne doit tourner qu'une seule fois (voir
    `_seeder_ressources_stock_legacy`)."""
    if _colonne_absente(c, table, colonne):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {ddl_type}")
        return True
    return False


def _seeder_ressources_stock_legacy(c: sqlite3.Connection) -> None:
    """Correctif revue finale (Important) : `ALTER TABLE cellules ADD COLUMN
    ressources_stock ... DEFAULT '{}'` laisse les cellules d'un monde antérieur au
    Sprint C avec un stock VIDE. Or un stock vide rend
    `horloge.cellule_saturee(pop, {})` toujours vrai (somme nulle) et fait
    court-circuiter `horloge.evoluer_ressources_et_technologie` — un tel monde
    serait figé technologiquement et en migration permanente dès son premier tick.
    On sème donc, une seule fois (au moment de l'ALTER, voir `_ajouter_colonne`),
    le stock numérique à partir de la liste qualitative `ressources` déjà présente,
    au même demi-plafond que `creer_monde` pour les mondes neufs.

    Les cellules SANS ressource qualitative (`_tirer_ressources` peut renvoyer une
    liste vide) restent légitimement à `'{}'` — ne pas les re-sémer à chaque
    connexion est précisément la raison du déclenchement one-shot."""
    rows = c.execute("SELECT monde_id, cellule_id, ressources FROM cellules").fetchall()
    if not rows:
        return
    c.executemany(
        "UPDATE cellules SET ressources_stock=? WHERE monde_id=? AND cellule_id=?",
        [(json.dumps({nom: STOCK_INITIAL_PAR_RESSOURCE for nom in json.loads(r["ressources"])},
                      ensure_ascii=False), r["monde_id"], r["cellule_id"]) for r in rows])
    # `commit()` IMMÉDIAT (correctif 2e revue finale, Important) : l'`ALTER TABLE`
    # qui déclenche ce semis est auto-commité tout de suite par le module `sqlite3`,
    # mais cet UPDATE, lui, appartient à la transaction de l'appelant (`with _conn()
    # as c:`). Si ce bloc appelant lève ensuite pour une raison quelconque, l'ALTER
    # survit et l'UPDATE est annulé — or le déclencheur est one-shot (« la colonne
    # vient d'être ajoutée ») et ne se représentera JAMAIS : les cellules legacy
    # resteraient à `ressources_stock={}` définitivement, donc saturées en
    # permanence et figées technologiquement. C'est exactement le bug que ce semis
    # est censé fermer.
    c.commit()


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
        ressources_stock TEXT NOT NULL DEFAULT '{}', niveau_technologie REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (monde_id, cellule_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS placements (
        enfant_id TEXT NOT NULL, monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        place_le TEXT, ne_au_tick INTEGER NOT NULL DEFAULT 0, vivant INTEGER NOT NULL DEFAULT 1,
        mort_au_tick INTEGER, emigre INTEGER NOT NULL DEFAULT 0, emigre_au_tick INTEGER,
        emigre_vers_monde_id TEXT, PRIMARY KEY (enfant_id, monde_id))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_placement_monde ON placements(monde_id)")
    _ajouter_colonne(c, "placements", "ne_au_tick", "INTEGER NOT NULL DEFAULT 0")
    _ajouter_colonne(c, "placements", "vivant", "INTEGER NOT NULL DEFAULT 1")
    _ajouter_colonne(c, "placements", "mort_au_tick", "INTEGER")
    _ajouter_colonne(c, "placements", "emigre", "INTEGER NOT NULL DEFAULT 0")
    _ajouter_colonne(c, "placements", "emigre_au_tick", "INTEGER")
    _ajouter_colonne(c, "placements", "emigre_vers_monde_id", "TEXT")
    if _ajouter_colonne(c, "cellules", "ressources_stock", "TEXT NOT NULL DEFAULT '{}'"):
        _seeder_ressources_stock_legacy(c)
    _ajouter_colonne(c, "cellules", "niveau_technologie", "REAL NOT NULL DEFAULT 0.0")
    # DUPLIQUÉE depuis stockage.py::_conn() (fix latent Task 2 : GET /spatial/mondes/{id}
    # 500ait sur une DB fraîche sans cette table). Le schéma DOIT rester identique entre
    # les deux copies — test_stockage_spatial.py::test_ddl_enfants_identique_a_stockage
    # pince les deux en synchro.
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, sexe TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    _ajouter_colonne(c, "enfants", "sexe", "TEXT")
    return c


def _meta(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nb_cellules": r["nb_cellules"], "seed": r["seed"],
            "forked_from_id": r["forked_from_id"], "cree_le": r["cree_le"]}


STOCK_INITIAL_PAR_RESSOURCE = 50.0  # demi-plafond — voir horloge.PLAFOND_RESSOURCE (100.0), pas
                                     # importé ici pour ne pas coupler le stockage à la mécanique


def creer_monde(cle_api: str, cellules: list[dict], seed: int, forked_from_id: str | None = None) -> dict:
    """Persiste un monde déjà généré (`cellules` = sortie de `spatial.generer_monde`,
    ou une copie lors d'un fork). Renvoie ses métadonnées. Chaque ressource
    qualitative (Sprint B) démarre avec un stock numérique à demi-plafond
    (Sprint C) — voir `horloge.evoluer_ressources_et_technologie`."""
    mid = uuid.uuid4().hex
    cree_le = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("INSERT INTO mondes (id, cle_api, nb_cellules, seed, forked_from_id, cree_le) "
                   "VALUES (?,?,?,?,?,?)",
                   (mid, cle_api, len(cellules), seed, forked_from_id, cree_le))
        c.executemany(
            "INSERT INTO cellules (monde_id, cellule_id, x, y, biome, ressources, voisins, "
            "ressources_stock, niveau_technologie) VALUES (?,?,?,?,?,?,?,?,0.0)",
            [(mid, cel["cellule_id"], cel["x"], cel["y"], cel["biome"],
              json.dumps(cel["ressources"], ensure_ascii=False),
              json.dumps(cel["voisins"]),
              json.dumps({r: STOCK_INITIAL_PAR_RESSOURCE for r in cel["ressources"]}, ensure_ascii=False))
             for cel in cellules])
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
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction (sauf
    migration transfrontière, Sprint D, où le consentement vient du rattachement
    à la fédération, pas de `monde_existe` : `horloge_moteur` interroge ici des
    pays adjacents appartenant délibérément à d'AUTRES tenants)."""
    with _conn() as c:
        r = c.execute("SELECT nb_cellules FROM mondes WHERE id=?", (monde_id,)).fetchone()
    return r["nb_cellules"] if r else None


def proprietaire_monde(monde_id: str) -> str | None:
    """`cle_api` propriétaire de ce monde, par id seul — utilisée par la migration
    transfrontière (Sprint D) pour savoir à quel tenant transférer un habitant qui
    change de pays (voir `stockage.transferer_proprietaire`).

    ⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé que `monde_id`
    est légitime dans son contexte (même motif que `nb_cellules_monde`) — ici le
    consentement vient du rattachement à la fédération, pas de `monde_existe`,
    puisque le pays destination appartient par nature à un autre tenant."""
    with _conn() as c:
        r = c.execute("SELECT cle_api FROM mondes WHERE id=?", (monde_id,)).fetchone()
    return r["cle_api"] if r else None


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
            "ressources_stock": json.loads(r["ressources_stock"]),
            "niveau_technologie": r["niveau_technologie"],
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


def lire_placement_par_enfant(enfant_id: str) -> dict | None:
    """Placement complet (monde, cellule, âge/statut) de cet enfant, quel que soit son
    statut vivant/mort — contrairement à `population_vivante_*`, qui filtre `vivant=1`.
    Utilisé par `main.py::genome_enfant_lire` pour le champ `simulation` (pont
    Studio↔world-engine). ⚠️ Ne vérifie PAS `cle_api` : l'appelant a déjà validé
    l'appartenance de `enfant_id` via `stockage.lire(cle_api, eid)`. Un enfant placé dans
    plusieurs mondes (cas non prévu par le pont, qui n'en fonde qu'un par personnage)
    renvoie son placement le plus récent."""
    with _conn() as c:
        r = c.execute("SELECT monde_id, cellule_id, ne_au_tick, vivant, mort_au_tick "
                       "FROM placements WHERE enfant_id=? ORDER BY place_le DESC LIMIT 1",
                       (enfant_id,)).fetchone()
    if r is None:
        return None
    return {"monde_id": r["monde_id"], "cellule_id": r["cellule_id"],
            "ne_au_tick": r["ne_au_tick"], "vivant": r["vivant"], "mort_au_tick": r["mort_au_tick"]}


def placer(monde_id: str, enfant_id: str, cellule_id: int, ne_au_tick: int = 0) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction (sauf
    migration transfrontière, Sprint D, où le consentement vient du rattachement
    à la fédération, pas de `monde_existe` : le placement de l'arrivant se fait
    dans un pays destination qui peut appartenir à un autre tenant).

    `ne_au_tick` (Sprint C) : tick de l'horloge de ce monde au moment de cette
    naissance — 0 par défaut (placement sans notion de tick, ou monde jamais
    avancé). `vivant=1` toujours à la création d'un placement (une naissance ne
    peut pas naître déjà morte)."""
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO placements "
                   "(enfant_id, monde_id, cellule_id, place_le, ne_au_tick, vivant) "
                   "VALUES (?,?,?,?,?,1)",
                   (enfant_id, monde_id, cellule_id, datetime.now(timezone.utc).isoformat(), ne_au_tick))


def supprimer_placements_enfant(enfant_id: str) -> None:
    """Supprime tous les placements de cet enfant, dans TOUS les mondes — appelée
    après `stockage.supprimer(cle_api, enfant_id)` pour ne pas laisser de rangée
    `placements` orpheline. Pas de cloisonnement `cle_api` ici : l'appartenance de
    `enfant_id` au tenant a déjà été confirmée par `stockage.supprimer()` avant cet
    appel (voir `main.py::genome_enfant_supprimer`)."""
    with _conn() as c:
        c.execute("DELETE FROM placements WHERE enfant_id=?", (enfant_id,))


def population_vivante_cellule(monde_id: str, cellule_id: int) -> list[dict]:
    """Habitants vivants ET NON ÉMIGRÉS placés sur cette cellule, avec leur sexe
    (Sprint C, voir stockage.py) et leur tick de naissance DANS ce monde — snapshot
    utilisé par l'horloge pour décider mortalité/couples/reproduction.

    Sprint D : un émigré reste `vivant=1` mais ne compte plus pour son pays
    d'origine (voir design) — le filtre `emigre=0` s'ajoute au critère `vivant=1`.

    ⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        rows = c.execute(
            "SELECT e.id AS id, e.sexe AS sexe, p.ne_au_tick AS ne_au_tick "
            "FROM placements p JOIN enfants e ON p.enfant_id = e.id "
            "WHERE p.monde_id=? AND p.cellule_id=? AND p.vivant=1 AND p.emigre=0",
            (monde_id, cellule_id)).fetchall()
    return [{"id": r["id"], "sexe": r["sexe"], "ne_au_tick": r["ne_au_tick"]} for r in rows]


def population_vivante_monde(monde_id: str) -> dict[int, list[dict]]:
    """Version « tout le monde en une requête » de `population_vivante_cellule`,
    groupée par `cellule_id` (même motif de regroupement que `_enfants_par_cellule`).

    Correctif revue finale (Critical) : `horloge_moteur.executer_tick` ouvrait une
    connexion SQLite PAR CELLULE (chacune rejouant la DDL complète + plusieurs sondes
    `PRAGMA table_info`) — ~12 s de blocage synchrone dans un `async def` sur un
    monde de 2000 cellules (taille légale), assez pour faire tomber le healthcheck.
    `population_vivante_cellule` reste en place pour les autres appelants/tests.

    Sprint D : filtre `emigre=0` ajouté (un émigré ne compte plus pour son pays
    d'origine). Une cellule sans habitant vivant non-émigré est ABSENTE du dict
    (utiliser `.get(cid, [])` — un `resultat[cid]` direct lève `KeyError`).

    ⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        rows = c.execute(
            "SELECT p.cellule_id AS cid, e.id AS id, e.sexe AS sexe, p.ne_au_tick AS ne_au_tick "
            "FROM placements p JOIN enfants e ON p.enfant_id = e.id "
            "WHERE p.monde_id=? AND p.vivant=1 AND p.emigre=0", (monde_id,)).fetchall()
    par_cellule: dict[int, list[dict]] = {}
    for r in rows:
        par_cellule.setdefault(r["cid"], []).append(
            {"id": r["id"], "sexe": r["sexe"], "ne_au_tick": r["ne_au_tick"]})
    return par_cellule


def deplacer_placement(monde_id: str, enfant_id: str, nouvelle_cellule_id: int) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        c.execute("UPDATE placements SET cellule_id=? WHERE monde_id=? AND enfant_id=?",
                   (nouvelle_cellule_id, monde_id, enfant_id))


def deplacer_placements(monde_id: str, deplacements: list[tuple[str, int]]) -> None:
    """Version lot de `deplacer_placement` (`(enfant_id, nouvelle_cellule_id)`), en
    une seule connexion/transaction — voir `population_vivante_monde` pour le
    pourquoi. ⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        c.executemany("UPDATE placements SET cellule_id=? WHERE monde_id=? AND enfant_id=?",
                       [(cel, monde_id, eid) for eid, cel in deplacements])


def marquer_mort(monde_id: str, enfant_id: str, tick: int) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        c.execute("UPDATE placements SET vivant=0, mort_au_tick=? WHERE monde_id=? AND enfant_id=?",
                   (tick, monde_id, enfant_id))


def marquer_morts(monde_id: str, enfant_ids: list[str], tick: int) -> None:
    """Version lot de `marquer_mort`, en une seule connexion/transaction — voir
    `population_vivante_monde`. ⚠️ Ne vérifie PAS `cle_api` : même motif."""
    with _conn() as c:
        c.executemany(
            "UPDATE placements SET vivant=0, mort_au_tick=? WHERE monde_id=? AND enfant_id=?",
            [(tick, monde_id, eid) for eid in enfant_ids])


def marquer_emigre(monde_id: str, enfant_id: str, tick: int, monde_id_destination: str) -> None:
    """Marque un départ transfrontière (Sprint D) — distinct de la mort : `vivant`
    n'est PAS mis à 0 ici, seul `emigre` change. ⚠️ Ne vérifie PAS `cle_api` :
    même motif que le reste de ce module (appelée par horloge_moteur.py, pas
    depuis une requête HTTP)."""
    with _conn() as c:
        c.execute("UPDATE placements SET emigre=1, emigre_au_tick=?, emigre_vers_monde_id=? "
                   "WHERE monde_id=? AND enfant_id=?",
                   (tick, monde_id_destination, monde_id, enfant_id))


def lire_ressources_stock(monde_id: str, cellule_id: int) -> dict:
    with _conn() as c:
        r = c.execute("SELECT ressources_stock FROM cellules WHERE monde_id=? AND cellule_id=?",
                       (monde_id, cellule_id)).fetchone()
    return json.loads(r["ressources_stock"]) if r else {}


def ecrire_ressources_stock(monde_id: str, cellule_id: int, stock: dict) -> None:
    with _conn() as c:
        c.execute("UPDATE cellules SET ressources_stock=? WHERE monde_id=? AND cellule_id=?",
                   (json.dumps(stock, ensure_ascii=False), monde_id, cellule_id))


def lire_niveau_technologie(monde_id: str, cellule_id: int) -> float:
    with _conn() as c:
        r = c.execute("SELECT niveau_technologie FROM cellules WHERE monde_id=? AND cellule_id=?",
                       (monde_id, cellule_id)).fetchone()
    return r["niveau_technologie"] if r else 0.0


def ecrire_niveau_technologie(monde_id: str, cellule_id: int, niveau: float) -> None:
    with _conn() as c:
        c.execute("UPDATE cellules SET niveau_technologie=? WHERE monde_id=? AND cellule_id=?",
                   (niveau, monde_id, cellule_id))


def ecrire_ressources_et_technologie_monde(monde_id: str,
                                            par_cellule: dict[int, tuple[dict, float]]) -> None:
    """Écrit stock de ressources ET niveau de technologie de PLUSIEURS cellules
    (`{cellule_id: (stock, niveau)}`) en une seule connexion/transaction — voir
    `population_vivante_monde` pour le pourquoi. ⚠️ Ne vérifie PAS `cle_api` :
    même motif que le reste de ce module."""
    with _conn() as c:
        c.executemany(
            "UPDATE cellules SET ressources_stock=?, niveau_technologie=? "
            "WHERE monde_id=? AND cellule_id=?",
            [(json.dumps(stock, ensure_ascii=False), niveau, monde_id, cid)
             for cid, (stock, niveau) in par_cellule.items()])


def forker_monde(cle_api: str, monde_id: str) -> dict | None:
    """Clone un monde : mêmes cellules (mêmes cellule_id, biomes, ressources,
    voisins, stock de ressources, niveau de technologie — pas de régénération) et
    mêmes placements (y compris âge/statut vivant), sous un nouvel id. Le monde
    source n'est jamais modifié."""
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
            "INSERT INTO cellules (monde_id, cellule_id, x, y, biome, ressources, voisins, "
            "ressources_stock, niveau_technologie) VALUES (?,?,?,?,?,?,?,?,?)",
            [(nid, r["cellule_id"], r["x"], r["y"], r["biome"], r["ressources"], r["voisins"],
              r["ressources_stock"], r["niveau_technologie"]) for r in cellules])
        placements = c.execute("SELECT * FROM placements WHERE monde_id=?", (monde_id,)).fetchall()
        c.executemany(
            "INSERT INTO placements (enfant_id, monde_id, cellule_id, place_le, "
            "ne_au_tick, vivant, mort_au_tick, emigre, emigre_au_tick, emigre_vers_monde_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r["enfant_id"], nid, r["cellule_id"], r["place_le"], r["ne_au_tick"],
              r["vivant"], r["mort_au_tick"], r["emigre"], r["emigre_au_tick"],
              r["emigre_vers_monde_id"]) for r in placements])
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
