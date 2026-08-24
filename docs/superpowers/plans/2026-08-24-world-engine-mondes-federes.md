# World Engine — Mondes fédérés (Sprint D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `federation` concept to `briques/world-engine` that groups existing mondes (each becoming a « pays ») and enables cross-border migration between adjacent pays during the existing per-monde tick, without ever synchronizing ticks between pays.

**Architecture:** New `stockage_federation.py` module (federations/federation_pays/federation_adjacences tables, same SQLite DB as the rest of the brique). `stockage_spatial.py` gains an `emigre` tri-state on `placements` (distinct from `vivant`/`mort_au_tick`). `horloge.py` gains pure, seeded migration-frontière helpers. `horloge_moteur.py`'s existing per-cellule tick loop gets a new decision branch (cross-border roll before the existing intra-pays migration roll) and a new write phase that locks the destination pays with a timeout before writing across monde boundaries. `main.py` gains a `/federation` router following the exact cloisonnement conventions of `/spatial` and `/horloge`.

**Tech Stack:** Python 3, FastAPI, SQLite (stdlib `sqlite3`), pytest + pytest-asyncio + respx (existing test stack, no new dependency).

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-24-world-engine-mondes-federes-design.md` — every task below implements a specific section of it; re-read it if a step's rationale is unclear.
- No new pip dependency — everything is stdlib `sqlite3`/`asyncio` plus the existing FastAPI/pytest stack.
- Every new SQL-backed function follows the file's own established pattern (`_conn()` opens the DB, `CREATE TABLE IF NOT EXISTS` + `_ajouter_colonne` for migrations, `with _conn() as c:` for a transaction).
- Every new HTTP endpoint is cloisonné: absent resource OR permission refused → `404`, **never** `403`, **never** confused with a `422` validation error.
- `stockage_federation.py`, `stockage_spatial.py`'s internal helpers (e.g. `population_vivante_monde`) do **not** re-check `cle_api` — only `main.py` (the HTTP boundary) and functions explicitly documented as doing so (`rattacher_pays`'s caller in `main.py`) enforce it, exactly like the rest of this brique.
- All new tests run against the temp SQLite DB wired by `conftest.py` — no new fixture needed.
- Run every test command from `briques/world-engine/` (`cd briques/world-engine && pytest ...`).

---

## Task 1: `stockage_federation.py` — persistence for federations/pays/adjacences

**Files:**
- Create: `briques/world-engine/stockage_federation.py`
- Create: `briques/world-engine/test_stockage_federation.py`

**Interfaces:**
- Consumes: nothing new (stdlib only). Reads `placements` (owned by `stockage_spatial.py`, same DB, not re-declared here — same pattern as `stockage_horloge.horloges_actives_a_declencher` reading `mondes`).
- Produces (used by Task 4 and Task 5):
  - `creer_federation(cle_api: str, nom: str | None) -> dict` → `{id, nom, createur_cle_api, cree_le}`
  - `rattacher_pays(federation_id: str, monde_id: str, cle_api: str, nom: str | None) -> dict | None` → `{federation_id, monde_id, nom, rattache_le}` or `None` if federation absent
  - `detacher_pays(federation_id: str, monde_id: str, cle_api: str) -> bool`
  - `membre(federation_id: str, cle_api: str) -> bool`
  - `declarer_adjacence(federation_id: str, monde_id_a: str, monde_id_b: str) -> dict | None` → `{federation_id, monde_id_a, monde_id_b, declaree_le}` (normalized `a < b`) or `None`
  - `lire_federation(federation_id: str) -> dict | None` → `{id, nom, createur_cle_api, cree_le, pays: [{monde_id, nom, cle_api, rattache_le}], adjacences: [{monde_id_a, monde_id_b}]}`
  - `lister_federations(cle_api: str) -> list[dict]`
  - `supprimer_federation(cle_api: str, federation_id: str) -> bool`
  - `pays_adjacents(monde_id: str) -> list[str]` — sorted, union across all federations `monde_id` belongs to
  - `population_vivante_federation(federation_id: str) -> dict | None` → `{federation_id, pays: [{monde_id, population_vivante}], population_totale}`

- [ ] **Step 1: Write failing tests for the DDL + core CRUD (create/rattacher/lire/lister)**

Create `briques/world-engine/test_stockage_federation.py`:

```python
"""Tests du stockage SQLite des fédérations de pays (Sprint D) — même motif que
test_stockage_horloge.py/test_stockage_spatial.py (DB temporaire posée par
conftest.py)."""
import stockage_federation
import stockage_spatial


def test_creer_federation():
    f = stockage_federation.creer_federation("cle-a", "Le Vieux Continent")
    assert f["nom"] == "Le Vieux Continent"
    assert f["createur_cle_api"] == "cle-a"
    assert f["id"]
    assert f["cree_le"]


def test_creer_federation_sans_nom():
    f = stockage_federation.creer_federation("cle-a", None)
    assert f["nom"] is None


def test_rattacher_pays_puis_lire_federation():
    f = stockage_federation.creer_federation("cle-a", "F1")
    monde = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    resultat = stockage_federation.rattacher_pays(f["id"], monde["id"], "cle-a", "France")
    assert resultat == {"federation_id": f["id"], "monde_id": monde["id"],
                         "nom": "France", "rattache_le": resultat["rattache_le"]}
    lu = stockage_federation.lire_federation(f["id"])
    assert lu["pays"] == [{"monde_id": monde["id"], "nom": "France",
                            "cle_api": "cle-a", "rattache_le": resultat["rattache_le"]}]
    assert lu["adjacences"] == []


def test_rattacher_pays_federation_introuvable_renvoie_none():
    monde = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    assert stockage_federation.rattacher_pays("id-inconnu", monde["id"], "cle-a", None) is None


def test_lire_federation_introuvable_renvoie_none():
    assert stockage_federation.lire_federation("id-inconnu") is None


def test_lister_federations_createur_et_membre():
    f1 = stockage_federation.creer_federation("cle-createur", "F1")
    f2 = stockage_federation.creer_federation("cle-autre", "F2")
    monde = stockage_spatial.creer_monde("cle-membre", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f2["id"], monde["id"], "cle-membre", None)
    # cle-createur voit F1 (créatrice) mais pas F2 (ni créatrice ni membre)
    ids_createur = {f["id"] for f in stockage_federation.lister_federations("cle-createur")}
    assert ids_createur == {f1["id"]}
    # cle-membre voit F2 (membre) mais pas F1
    ids_membre = {f["id"] for f in stockage_federation.lister_federations("cle-membre")}
    assert ids_membre == {f2["id"]}


def _cellules(n=2):
    return [{"cellule_id": i, "x": float(i) * 10, "y": 0.0, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_stockage_federation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockage_federation'`

- [ ] **Step 3: Implement `stockage_federation.py` (DDL + core CRUD)**

Create `briques/world-engine/stockage_federation.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_stockage_federation.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/stockage_federation.py briques/world-engine/test_stockage_federation.py
git commit -m "feat(world-engine): stockage_federation.py — DDL + CRUD de base (créer/rattacher/lire/lister)"
```

- [ ] **Step 6: Write failing tests for detacher/membre/adjacence/supprimer**

Append to `briques/world-engine/test_stockage_federation.py`:

```python
def test_detacher_pays_retire_le_pays_et_ses_adjacences():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f["id"], m2["id"], "cle-a", None)
    stockage_federation.declarer_adjacence(f["id"], m1["id"], m2["id"])

    assert stockage_federation.detacher_pays(f["id"], m1["id"], "cle-a") is True

    lu = stockage_federation.lire_federation(f["id"])
    assert [p["monde_id"] for p in lu["pays"]] == [m2["id"]]
    assert lu["adjacences"] == []  # l'adjacence impliquant m1 a disparu avec lui


def test_detacher_pays_mauvaise_cle_api_renvoie_false():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    assert stockage_federation.detacher_pays(f["id"], m1["id"], "cle-autre") is False
    # toujours membre : la mauvaise cle_api n'a rien retiré
    assert [p["monde_id"] for p in stockage_federation.lire_federation(f["id"])["pays"]] == [m1["id"]]


def test_membre_vrai_si_cle_api_possede_un_pays():
    f = stockage_federation.creer_federation("cle-createur", "F1")
    m1 = stockage_spatial.creer_monde("cle-membre", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-membre", None)
    assert stockage_federation.membre(f["id"], "cle-membre") is True
    # le créateur seul (sans pays à lui) n'est PAS "membre" au sens de cette fonction
    assert stockage_federation.membre(f["id"], "cle-createur") is False


def test_declarer_adjacence_normalisee():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f["id"], m2["id"], "cle-a", None)

    a, b = sorted([m1["id"], m2["id"]])
    resultat = stockage_federation.declarer_adjacence(f["id"], m2["id"], m1["id"])  # ordre inversé
    assert (resultat["monde_id_a"], resultat["monde_id_b"]) == (a, b)

    lu = stockage_federation.lire_federation(f["id"])
    assert lu["adjacences"] == [{"monde_id_a": a, "monde_id_b": b}]


def test_declarer_adjacence_pays_non_membre_renvoie_none():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    # m2 n'a jamais été rattaché à f
    assert stockage_federation.declarer_adjacence(f["id"], m1["id"], m2["id"]) is None


def test_pays_adjacents_union_de_plusieurs_federations():
    f1 = stockage_federation.creer_federation("cle-a", "F1")
    f2 = stockage_federation.creer_federation("cle-a", "F2")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    m3 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=3)
    for f in (f1, f2):
        stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f1["id"], m2["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f2["id"], m3["id"], "cle-a", None)
    stockage_federation.declarer_adjacence(f1["id"], m1["id"], m2["id"])
    stockage_federation.declarer_adjacence(f2["id"], m1["id"], m3["id"])

    assert stockage_federation.pays_adjacents(m1["id"]) == sorted([m2["id"], m3["id"]])
    assert stockage_federation.pays_adjacents(m2["id"]) == [m1["id"]]


def test_pays_adjacents_aucune_federation_renvoie_liste_vide():
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    assert stockage_federation.pays_adjacents(m1["id"]) == []


def test_supprimer_federation_ne_touche_jamais_les_mondes():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)

    assert stockage_federation.supprimer_federation("cle-a", f["id"]) is True
    assert stockage_federation.lire_federation(f["id"]) is None
    # le monde sous-jacent existe toujours
    assert stockage_spatial.monde_existe("cle-a", m1["id"]) is True


def test_supprimer_federation_mauvaise_cle_api_renvoie_false():
    f = stockage_federation.creer_federation("cle-a", "F1")
    assert stockage_federation.supprimer_federation("cle-autre", f["id"]) is False
    assert stockage_federation.lire_federation(f["id"]) is not None


def test_population_vivante_federation_agrege_par_pays():
    import stockage
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f["id"], m2["id"], "cle-a", None)
    e1 = stockage.creer("cle-a", "A", "X", None, None, {}, "d", {}, False, sexe="F")
    e2 = stockage.creer("cle-a", "B", "X", None, None, {}, "d", {}, False, sexe="M")
    stockage_spatial.placer(m1["id"], e1, 0)
    stockage_spatial.placer(m2["id"], e2, 0)

    etat = stockage_federation.population_vivante_federation(f["id"])
    assert etat["population_totale"] == 2
    assert {p["monde_id"]: p["population_vivante"] for p in etat["pays"]} == {
        m1["id"]: 1, m2["id"]: 1}


def test_population_vivante_federation_introuvable_renvoie_none():
    assert stockage_federation.population_vivante_federation("id-inconnu") is None
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_stockage_federation.py -v`
Expected: 5 previous tests PASS, 10 new tests FAIL with `AttributeError: module 'stockage_federation' has no attribute 'detacher_pays'` (and similar for the other missing functions)

- [ ] **Step 8: Implement the remaining functions**

Append to `briques/world-engine/stockage_federation.py`:

```python
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
    """Agrégat pour `GET /federation/{id}/etat` : population vivante (hors
    émigrés — `vivant=1 AND emigre=0`) par pays membre + total. Lit `placements`
    (propriété de stockage_spatial.py, même base SQLite) SANS en dupliquer la DDL
    — même hypothèse que stockage_horloge.horloges_actives_a_declencher : un pays
    n'est rattachable (voir rattacher_pays) que s'il existe déjà, donc la table
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
            n = c.execute(
                "SELECT COUNT(*) AS n FROM placements WHERE monde_id=? AND vivant=1 AND emigre=0",
                (mid,)).fetchone()["n"]
            par_pays.append({"monde_id": mid, "population_vivante": n})
            total += n
    return {"federation_id": federation_id, "pays": par_pays, "population_totale": total}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_stockage_federation.py -v`
Expected: PASS (15 tests total)

- [ ] **Step 10: Commit**

```bash
git add briques/world-engine/stockage_federation.py briques/world-engine/test_stockage_federation.py
git commit -m "feat(world-engine): stockage_federation.py — détacher/membre/adjacence/supprimer/agrégat"
```

---

## Task 2: `stockage_spatial.py` — champ `emigre` sur `placements`

**Files:**
- Modify: `briques/world-engine/stockage_spatial.py`
- Test: `briques/world-engine/test_stockage_spatial.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 4):
  - `marquer_emigre(monde_id: str, enfant_id: str, tick: int, monde_id_destination: str) -> None`
  - `population_vivante_cellule`/`population_vivante_monde` now additionally filter `emigre=0` (signature unchanged, behavior change is the point of this task)
  - `forker_monde` now also copies `emigre`/`emigre_au_tick`/`emigre_vers_monde_id`

- [ ] **Step 1: Write failing tests for the new column and its effect on population queries**

Append to `briques/world-engine/test_stockage_spatial.py`:

```python
def test_marquer_emigre_exclut_de_la_population_vivante_sans_le_tuer():
    monde = stockage_spatial.creer_monde("cle-emig1", _cellules_factices(2), seed=1)
    stockage.creer("cle-emig1", "Em", "X", None, None, {}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-emig1")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=0)

    stockage_spatial.marquer_emigre(monde["id"], eid, tick=5, monde_id_destination="monde-dest")

    # exclu de la population vivante du pays d'origine...
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []
    assert stockage_spatial.population_vivante_monde(monde["id"]) == {}
    # ...mais la ligne existe toujours, vivant=1, mort_au_tick NULL (pas mort)
    with stockage_spatial._conn() as c:
        r = c.execute("SELECT * FROM placements WHERE monde_id=? AND enfant_id=?",
                       (monde["id"], eid)).fetchone()
    assert r["vivant"] == 1
    assert r["mort_au_tick"] is None
    assert r["emigre"] == 1
    assert r["emigre_au_tick"] == 5
    assert r["emigre_vers_monde_id"] == "monde-dest"


def test_placer_dans_nouveau_pays_reinitialise_emigre():
    monde_a = stockage_spatial.creer_monde("cle-emig2", _cellules_factices(2), seed=1)
    monde_b = stockage_spatial.creer_monde("cle-emig2", _cellules_factices(2), seed=2)
    stockage.creer("cle-emig2", "Em", "X", None, None, {}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-emig2")[0]["id"]
    stockage_spatial.placer(monde_a["id"], eid, 0, ne_au_tick=0)
    stockage_spatial.marquer_emigre(monde_a["id"], eid, tick=5, monde_id_destination=monde_b["id"])

    stockage_spatial.placer(monde_b["id"], eid, 1, ne_au_tick=3)

    assert stockage_spatial.population_vivante_cellule(monde_b["id"], 1) == [
        {"id": eid, "sexe": "F", "ne_au_tick": 3}]


def test_forker_monde_copie_le_statut_emigre():
    monde = stockage_spatial.creer_monde("cle-emig3", _cellules_factices(2), seed=1)
    stockage.creer("cle-emig3", "Em", "X", None, None, {}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-emig3")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    stockage_spatial.marquer_emigre(monde["id"], eid, tick=2, monde_id_destination="ailleurs")

    fork = stockage_spatial.forker_monde("cle-emig3", monde["id"])

    with stockage_spatial._conn() as c:
        r = c.execute("SELECT * FROM placements WHERE monde_id=? AND enfant_id=?",
                       (fork["id"], eid)).fetchone()
    assert r["emigre"] == 1
    assert r["emigre_au_tick"] == 2
    assert r["emigre_vers_monde_id"] == "ailleurs"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -k emigre -v`
Expected: FAIL — `test_marquer_emigre_...` with `AttributeError: module 'stockage_spatial' has no attribute 'marquer_emigre'`; the other two fail on the same missing attribute or on assertions once that's stubbed (run after Step 3 confirms real behavior).

- [ ] **Step 3: Implement the `emigre` column, `marquer_emigre`, and update population queries + fork**

In `briques/world-engine/stockage_spatial.py`, update the `placements` DDL block inside `_conn()`:

```python
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
```

(This replaces the existing block that ends at `_ajouter_colonne(c, "placements", "mort_au_tick", "INTEGER")` — add the 3 new `_ajouter_colonne` calls right after it, and add the 3 new columns to the `CREATE TABLE IF NOT EXISTS placements (...)` literal for brand-new databases.)

Update `population_vivante_cellule`:

```python
def population_vivante_cellule(monde_id: str, cellule_id: int) -> list[dict]:
    """Habitants vivants ET NON ÉMIGRÉS placés sur cette cellule (Sprint D : un
    émigré reste `vivant=1` mais ne compte plus pour son pays d'origine — voir
    design). ⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        rows = c.execute(
            "SELECT e.id AS id, e.sexe AS sexe, p.ne_au_tick AS ne_au_tick "
            "FROM placements p JOIN enfants e ON p.enfant_id = e.id "
            "WHERE p.monde_id=? AND p.cellule_id=? AND p.vivant=1 AND p.emigre=0",
            (monde_id, cellule_id)).fetchall()
    return [{"id": r["id"], "sexe": r["sexe"], "ne_au_tick": r["ne_au_tick"]} for r in rows]
```

Update `population_vivante_monde` the same way (add `AND p.emigre=0` to its `WHERE`):

```python
def population_vivante_monde(monde_id: str) -> dict[int, list[dict]]:
    """Version « tout le monde en une requête » de `population_vivante_cellule`
    (même filtre `emigre=0` ajouté en Sprint D), groupée par `cellule_id`."""
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
```

Add `marquer_emigre` right after `marquer_morts`:

```python
def marquer_emigre(monde_id: str, enfant_id: str, tick: int, monde_id_destination: str) -> None:
    """Marque un départ transfrontière (Sprint D) — distinct de la mort : `vivant`
    n'est PAS mis à 0 ici, seul `emigre` change. ⚠️ Ne vérifie PAS `cle_api` :
    même motif que le reste de ce module (appelée par horloge_moteur.py, pas
    depuis une requête HTTP)."""
    with _conn() as c:
        c.execute("UPDATE placements SET emigre=1, emigre_au_tick=?, emigre_vers_monde_id=? "
                   "WHERE monde_id=? AND enfant_id=?",
                   (tick, monde_id_destination, monde_id, enfant_id))
```

Update `forker_monde`'s placements copy (both the SELECT-implicit `*` already covers new columns, but the explicit INSERT column list and the tuple must be extended):

```python
        placements = c.execute("SELECT * FROM placements WHERE monde_id=?", (monde_id,)).fetchall()
        c.executemany(
            "INSERT INTO placements (enfant_id, monde_id, cellule_id, place_le, "
            "ne_au_tick, vivant, mort_au_tick, emigre, emigre_au_tick, emigre_vers_monde_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r["enfant_id"], nid, r["cellule_id"], r["place_le"], r["ne_au_tick"],
              r["vivant"], r["mort_au_tick"], r["emigre"], r["emigre_au_tick"],
              r["emigre_vers_monde_id"]) for r in placements])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -v`
Expected: PASS (all tests, including the 3 new ones and all pre-existing ones — confirms the `emigre=0` filter didn't break any Sprint B/C behavior since `emigre` defaults to 0)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/stockage_spatial.py briques/world-engine/test_stockage_spatial.py
git commit -m "feat(world-engine): stockage_spatial — champ emigre sur placements, distinct de la mort"
```

---

## Task 3: `horloge.py` — mécanique pure de la migration transfrontière

**Files:**
- Modify: `briques/world-engine/horloge.py`
- Test: `briques/world-engine/test_horloge.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 4):
  - `PROBABILITE_MIGRATION_FRONTIERE: float` (constant, `0.05`)
  - `migre_frontiere(rng: Random) -> bool`
  - `tirer_pays_destination(pays_adjacents: list[str], rng: Random) -> str`
  - `tirer_cellule_destination(nb_cellules_destination: int, rng: Random) -> int`

- [ ] **Step 1: Write failing tests**

Append to `briques/world-engine/test_horloge.py`:

```python
def test_migre_frontiere_deterministe_avec_seed_fixe():
    a = horloge.migre_frontiere(Random(7))
    b = horloge.migre_frontiere(Random(7))
    assert a == b


def test_migre_frontiere_moins_probable_que_migre_intra_pays():
    # Sur un grand nombre de tirages avec le MÊME flux de random, la fréquence de
    # succès de migre_frontiere doit rester nettement sous celle de migre (Sprint C)
    # — traduit "franchir une frontière est un choix plus lourd" (design).
    rng_a, rng_b = Random(123), Random(123)
    n = 5000
    freq_frontiere = sum(horloge.migre_frontiere(rng_a) for _ in range(n)) / n
    freq_intra = sum(horloge.migre(rng_b) for _ in range(n)) / n
    assert freq_frontiere < freq_intra


def test_tirer_pays_destination_choisit_parmi_la_liste():
    rng = Random(1)
    pays = ["m1", "m2", "m3"]
    for _ in range(20):
        assert horloge.tirer_pays_destination(pays, rng) in pays


def test_tirer_cellule_destination_bornee():
    rng = Random(1)
    for _ in range(50):
        cid = horloge.tirer_cellule_destination(7, rng)
        assert 0 <= cid < 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_horloge.py -k frontiere -v`
Expected: FAIL with `AttributeError: module 'horloge' has no attribute 'migre_frontiere'` (and similarly for the other two new functions)

- [ ] **Step 3: Implement the pure functions**

In `briques/world-engine/horloge.py`, add right after the existing `# --- Migration ---` block (after `def migre(rng: Random) -> bool:`):

```python
# --- Migration transfrontière (Sprint D) ---
PROBABILITE_MIGRATION_FRONTIERE = 0.05  # plus faible que PROBABILITE_MIGRATION_SI_SATURE (0.20) —
                                          # franchir une frontière est un choix plus lourd que
                                          # changer de cellule voisine (voir design)


def migre_frontiere(rng: Random) -> bool:
    return rng.random() < PROBABILITE_MIGRATION_FRONTIERE


def tirer_pays_destination(pays_adjacents: list[str], rng: Random) -> str:
    return rng.choice(pays_adjacents)


def tirer_cellule_destination(nb_cellules_destination: int, rng: Random) -> int:
    """Cellule aléatoire bornée dans le pays destination — pas de notion de
    cellule-frontière géométrique entre deux maillages Voronoï séparés (voir
    design), même repli que le placement d'un parent sans position connue
    (Sprint B)."""
    return rng.randrange(nb_cellules_destination)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_horloge.py -v`
Expected: PASS (all tests, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/horloge.py briques/world-engine/test_horloge.py
git commit -m "feat(world-engine): horloge.py — mécanique pure de la migration transfrontière"
```

---

## Task 4: `horloge_moteur.py` — intégration de la migration transfrontière au tick

**Files:**
- Modify: `briques/world-engine/horloge_moteur.py`
- Test: `briques/world-engine/test_horloge_moteur.py`

**Interfaces:**
- Consumes:
  - `stockage_federation.pays_adjacents(monde_id: str) -> list[str]` (Task 1)
  - `stockage_spatial.nb_cellules_monde(monde_id: str) -> int | None` (existing)
  - `stockage_spatial.marquer_emigre(monde_id, enfant_id, tick, monde_id_destination) -> None` (Task 2)
  - `stockage_spatial.placer(monde_id, enfant_id, cellule_id, ne_au_tick=0) -> None` (existing — reused as-is for the destination insert)
  - `horloge.migre_frontiere/tirer_pays_destination/tirer_cellule_destination` (Task 3)
- Produces: `executer_tick`'s response dict gains a `migrations_transfrontieres: int` field (in addition to existing `migrations` which now counts ONLY intra-pays migrations, unchanged in meaning).

- [ ] **Step 1: Write failing tests for the core cross-border mechanic**

Append to `briques/world-engine/test_horloge_moteur.py`:

```python
# --- Sprint D : migration transfrontière ---

import stockage_federation


def _crf_pair(cle="cle-fed"):
    """2 pays d'1 cellule chacun, rattachés à une fédération et déclarés adjacents
    — topologie minimale pour exercer une émigration."""
    origine = _monde_avec_habitants(cle, n_cellules=1)
    destination = _monde_avec_habitants(cle, n_cellules=1)
    f = stockage_federation.creer_federation(cle, "F")
    stockage_federation.rattacher_pays(f["id"], origine["id"], cle, None)
    stockage_federation.rattacher_pays(f["id"], destination["id"], cle, None)
    stockage_federation.declarer_adjacence(f["id"], origine["id"], destination["id"])
    return origine, destination


@pytest.mark.asyncio
async def test_tick_emigre_habitant_cellule_saturee_pays_adjacent(monkeypatch):
    origine, destination = _crf_pair("cle-fed1")
    eid = _ajouter_habitant("cle-fed1", origine["id"], 0, "F", ne_au_tick=-20)

    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed1")

    assert resultat["migrations_transfrontieres"] == 1
    assert resultat["migrations"] == 0  # jamais les deux à la fois pour le même habitant
    assert stockage_spatial.population_vivante_cellule(origine["id"], 0) == []
    assert stockage_spatial.population_vivante_cellule(destination["id"], 0) == [
        {"id": eid, "sexe": "F", "ne_au_tick": stockage_spatial.population_vivante_cellule(
            destination["id"], 0)[0]["ne_au_tick"]}]


@pytest.mark.asyncio
async def test_emigration_preserve_lage_reel(monkeypatch):
    origine, destination = _crf_pair("cle-fed2")
    # habitant né au tick -20 : âgé de 21 au tick 1 (tick_suivant=1, age=1-(-20)=21)
    eid = _ajouter_habitant("cle-fed2", origine["id"], 0, "F", ne_au_tick=-20)
    # avance la destination de 10 ticks AVANT l'émigration, pour que ne_au_tick ne
    # puisse pas coïncider par hasard entre les 2 pays si le recalcul était omis
    for _ in range(10):
        await horloge_moteur.executer_tick(destination["id"], "cle-fed2")

    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)
    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed2")

    assert resultat["migrations_transfrontieres"] == 1
    arrive = stockage_spatial.population_vivante_cellule(destination["id"], 0)[0]
    assert arrive["id"] == eid
    # âge réel au départ = 1 - (-20) = 21 ; horloge destination était à 10, donc
    # ne_au_tick attendu = 10 - 21 = -11 (peut être négatif, comme n'importe quel
    # habitant "déjà adulte" injecté directement — voir _ajouter_habitant)
    assert arrive["ne_au_tick"] == -11


@pytest.mark.asyncio
async def test_emigration_dissout_le_couple_actif_avant_le_depart(monkeypatch):
    origine, destination = _crf_pair("cle-fed3")
    a = _ajouter_habitant("cle-fed3", origine["id"], 0, "F", ne_au_tick=-30)
    b = _ajouter_habitant("cle-fed3", origine["id"], 0, "M", ne_au_tick=-30)
    couple_id = stockage_horloge.former_couple(origine["id"], 0, a, b, tick=0)

    monkeypatch.setattr(horloge_moteur.horloge, "meurt", lambda *a_, **k: False)
    monkeypatch.setattr(horloge_moteur.horloge, "dissout", lambda rng: False)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    # seul `a` émigre (ordre de population_vivante_monde : a avant b, voir tests Sprint C)
    ordre = iter([True, False])
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: next(ordre))

    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed3")

    assert resultat["migrations_transfrontieres"] == 1
    assert resultat["couples_dissous"] == 1
    assert stockage_horloge.couples_actifs_monde(origine["id"]) == {}


@pytest.mark.asyncio
async def test_ligne_origine_conservee_marquee_emigre_jamais_supprimee(monkeypatch):
    origine, destination = _crf_pair("cle-fed4")
    eid = _ajouter_habitant("cle-fed4", origine["id"], 0, "F", ne_au_tick=-20)

    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)
    resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed4")

    with stockage_spatial._conn() as c:
        r = c.execute("SELECT * FROM placements WHERE monde_id=? AND enfant_id=?",
                       (origine["id"], eid)).fetchone()
    assert r is not None, "la ligne d'origine ne doit jamais être supprimée"
    assert r["vivant"] == 1
    assert r["mort_au_tick"] is None
    assert r["emigre"] == 1
    assert r["emigre_vers_monde_id"] == destination["id"]


@pytest.mark.asyncio
async def test_emigration_timeout_verrou_destination_echoue_proprement(monkeypatch):
    """Le pays destination a son verrou déjà tenu (simulé directement, sans passer
    par un vrai tick concurrent) : l'émigration doit échouer PROPREMENT (capturée
    dans avertissements), jamais planter le tick ni bloquer indéfiniment — voir
    design, correction sur le verrouillage inter-pays."""
    origine, destination = _crf_pair("cle-fed6")
    eid = _ajouter_habitant("cle-fed6", origine["id"], 0, "F", ne_au_tick=-20)

    monkeypatch.setattr(horloge_moteur, "VERROU_DESTINATION_TIMEOUT_S", 0.05)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    verrou_destination = horloge_moteur._verrou_tick(destination["id"])
    await verrou_destination.acquire()
    try:
        resultat = await horloge_moteur.executer_tick(origine["id"], "cle-fed6")
    finally:
        verrou_destination.release()

    assert resultat["migrations_transfrontieres"] == 0
    assert any("verrou" in a.lower() for a in resultat["avertissements"])
    # l'habitant reste dans son pays d'origine, jamais marqué émigré
    assert stockage_spatial.population_vivante_cellule(origine["id"], 0)[0]["id"] == eid


@pytest.mark.asyncio
async def test_pas_de_pays_adjacent_jamais_d_emigration(monkeypatch):
    """Un pays hors fédération (ou sans adjacence déclarée) ne doit jamais tenter
    de migration transfrontière, même si le jet aurait toujours réussi."""
    monde = _monde_avec_habitants("cle-fed5", n_cellules=1)
    _ajouter_habitant("cle-fed5", monde["id"], 0, "F", ne_au_tick=-20)
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    monkeypatch.setattr(horloge_moteur.horloge, "migre_frontiere", lambda rng: True)

    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-fed5")

    assert resultat["migrations_transfrontieres"] == 0


@pytest.mark.asyncio
async def test_determinisme_migration_transfrontiere_meme_seed(monkeypatch):
    """Même motif que le déterminisme Sprint C : même (seed, tick, cellule) ⇒
    mêmes décisions de migration transfrontière sur 2 exécutions isolées (2
    fédérations parallèles indépendantes avec le même seed d'origine)."""
    monkeypatch.setattr(horloge_moteur.horloge, "cellule_saturee", lambda *a, **k: True)
    resultats = []
    for suffixe in ("x", "y"):
        cle = f"cle-fed-det-{suffixe}"
        cellules = [{"cellule_id": 0, "x": 0.0, "y": 0.0, "biome": "plaine",
                     "ressources": ["ble"], "voisins": []}]
        origine = stockage_spatial.creer_monde(cle, cellules, seed=999)
        stockage_horloge.initialiser_horloge(origine["id"])
        destination = stockage_spatial.creer_monde(cle, cellules, seed=1)
        stockage_horloge.initialiser_horloge(destination["id"])
        f = stockage_federation.creer_federation(cle, "F")
        stockage_federation.rattacher_pays(f["id"], origine["id"], cle, None)
        stockage_federation.rattacher_pays(f["id"], destination["id"], cle, None)
        stockage_federation.declarer_adjacence(f["id"], origine["id"], destination["id"])
        for i in range(10):
            _ajouter_habitant(cle, origine["id"], 0, "F" if i % 2 == 0 else "M", ne_au_tick=-20)

        resultat = await horloge_moteur.executer_tick(origine["id"], cle)
        resultats.append(resultat["migrations_transfrontieres"])

    assert resultats[0] == resultats[1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -k fed -v`
Expected: FAIL — `resultat["migrations_transfrontieres"]` raises `KeyError` (key doesn't exist yet in the response dict), on every new test.

- [ ] **Step 3: Implement the cross-border migration mechanic in `horloge_moteur.py`**

Add the import at the top of `briques/world-engine/horloge_moteur.py` (alongside the existing imports):

```python
import stockage_federation
```

Add a timeout constant and a helper near `_verrou_tick` (right after its definition):

```python
VERROU_DESTINATION_TIMEOUT_S = 5.0


async def _acquerir_verrou_destination(monde_id: str) -> asyncio.Lock | None:
    """Tente d'acquérir le verrou de tick du pays DESTINATION d'une migration
    transfrontière, avec un timeout court.

    Un ordre d'acquisition trié par `monde_id` ne suffirait PAS à éliminer
    l'interblocage ici : le verrou du pays D'ORIGINE est déjà tenu en entrée du
    tick (`executer_tick`), avant même de savoir qu'une migration transfrontière
    aura lieu — l'ordre n'est donc jamais neutre, et 2 tics concurrents faisant le
    mouvement inverse l'un de l'autre (A→B et B→A au même instant) resteraient en
    interblocage classique malgré un tri (voir design, section corrigée).

    Renvoie le verrou ACQUIS (à libérer par l'appelant), ou None si le timeout est
    dépassé — dans ce cas CETTE émigration précise échoue proprement (capturée
    dans `avertissements` par l'appelant), sans jamais bloquer indéfiniment."""
    verrou = _verrou_tick(monde_id)
    try:
        await asyncio.wait_for(verrou.acquire(), timeout=VERROU_DESTINATION_TIMEOUT_S)
        return verrou
    except asyncio.TimeoutError:
        return None
```

In `_executer_tick`, right after `seed = monde["seed"]`, resolve the adjacent pays and their sizes ONCE for the whole tick (not per cellule):

```python
    pays_adjacents_ids = stockage_federation.pays_adjacents(monde_id)
    nb_cellules_adjacents = {pid: stockage_spatial.nb_cellules_monde(pid) for pid in pays_adjacents_ids}
```

Add a counter next to the existing counters (`naissances = morts = migrations = couples_formes = couples_dissous = 0`):

```python
    naissances = morts = migrations = migrations_transfrontieres = couples_formes = couples_dissous = 0
```

Add an accumulator next to the other `*_a_appliquer` lists (near `migrations_a_appliquer: list[tuple[str, int]] = []`):

```python
    emigrations_a_appliquer: list[tuple[str, str, int, int]] = []  # eid, monde_id_dest, cellule_id_dest, age
```

Replace the existing migration block inside the passe 2a `for cel in cellules_triees:` loop:

```python
        # 4) Migration — décidée sur l'état du DÉBUT de tick ; un habitant qui migre
        # reste éligible couples/reproduction dans SA cellule d'origine ce même tick.
        rng_mig = _rng(seed, tick_suivant, cid, "migration")
        if cel["voisins"] and horloge.cellule_saturee(len(vivants), stock_cellule):
            for h in vivants:
                if horloge.migre(rng_mig):
                    migrations_a_appliquer.append((h["id"], rng_mig.choice(cel["voisins"])))
```

with:

```python
        # 4) Migration — décidée sur l'état du DÉBUT de tick.
        #
        # 4a) Transfrontière (Sprint D) D'ABORD, repli sur l'intra-pays existant
        # ENSUITE — jamais les deux pour le même habitant le même tick. Contrairement
        # à un migrant intra-pays, un émigrant est retiré de `vivants` MAINTENANT :
        # il ne participe plus aux couples/reproduction de sa cellule d'origine ce
        # tick (franchir une frontière est un choix plus lourd que changer de
        # cellule voisine — voir design). Son couple actif éventuel est dissous via
        # le mécanisme de dissolution mondiale ci-dessous (5b), pas ici.
        rng_front = _rng(seed, tick_suivant, cid, "migration_frontiere")
        cellule_saturee_ici = horloge.cellule_saturee(len(vivants), stock_cellule)
        if cellule_saturee_ici and pays_adjacents_ids:
            restants = []
            for h in vivants:
                if horloge.migre_frontiere(rng_front):
                    dest_pays = horloge.tirer_pays_destination(pays_adjacents_ids, rng_front)
                    nb_dest = nb_cellules_adjacents.get(dest_pays)
                    if nb_dest:  # défensif : un pays adjacent supprimé (DELETE /spatial/mondes)
                                 # entre le rattachement et ce tick renverrait None ici — la
                                 # fédération ne cascade pas sur la suppression d'un monde (le
                                 # monde reste l'entité première, voir design) ; l'habitant reste
                                 # alors simplement dans son pays d'origine ce tick.
                        dest_cellule = horloge.tirer_cellule_destination(nb_dest, rng_front)
                        age = tick_suivant - h["ne_au_tick"]
                        emigrations_a_appliquer.append((h["id"], dest_pays, dest_cellule, age))
                        continue
                restants.append(h)
            vivants = restants

        # 4b) Intra-pays (Sprint C, inchangé) — sur les habitants NON émigrés ci-dessus.
        rng_mig = _rng(seed, tick_suivant, cid, "migration")
        if cel["voisins"] and cellule_saturee_ici:
            for h in vivants:
                if horloge.migre(rng_mig):
                    migrations_a_appliquer.append((h["id"], rng_mig.choice(cel["voisins"])))
```

Right after the passe 2a loop ends (before the `# 5b) Dissolution par décès` block), compute the set of emigrant ids and fold it into the existing mondial dissolution:

```python
    emigrants_tous = {eid for eid, _, _, _ in emigrations_a_appliquer}
```

Update the existing 5b line from:

```python
    dissous_ids |= {c["id"] for c in tous_couples_actifs
                    if c["habitant_a_id"] in morts_tous or c["habitant_b_id"] in morts_tous}
```

to:

```python
    dissous_ids |= {c["id"] for c in tous_couples_actifs
                    if c["habitant_a_id"] in morts_tous or c["habitant_b_id"] in morts_tous
                    or c["habitant_a_id"] in emigrants_tous or c["habitant_b_id"] in emigrants_tous}
```

Finally, add the write phase at the very end of Phase 3, right after the existing `if migrations_a_appliquer:` block (after its `deplacer_couples_habitants` call), and update the return dict:

```python
    if emigrations_a_appliquer:
        for eid, dest_monde_id, dest_cellule_id, age in emigrations_a_appliquer:
            verrou_dest = await _acquerir_verrou_destination(dest_monde_id)
            if verrou_dest is None:
                avertissements.append(
                    f"Émigration de {eid} vers {dest_monde_id} non appliquée : "
                    "verrou du pays destination indisponible (retentera au tick suivant).")
                continue
            try:
                horloge_dest = stockage_horloge.lire_horloge(dest_monde_id)
                tick_dest = horloge_dest["tick_actuel"] if horloge_dest else 0
                stockage_spatial.marquer_emigre(monde_id, eid, tick_suivant, dest_monde_id)
                stockage_spatial.placer(dest_monde_id, eid, dest_cellule_id,
                                          ne_au_tick=tick_dest - age)
                migrations_transfrontieres += 1
            except Exception as e:
                avertissements.append(f"Émigration de {eid} vers {dest_monde_id} non appliquée : {e}")
            finally:
                verrou_dest.release()

    return {
        "monde_id": monde_id, "tick_actuel": tick_suivant,
        "naissances": naissances, "morts": morts, "migrations": migrations,
        "migrations_transfrontieres": migrations_transfrontieres,
        "couples_formes": couples_formes, "couples_dissous": couples_dissous,
        "niveau_technologie_moyen": (sum(niveaux_tech) / len(niveaux_tech)) if niveaux_tech else 0.0,
        "avertissements": avertissements,
    }
```

(This replaces the existing `return {...}` block — add the `migrations_transfrontieres` key.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -v`
Expected: PASS (all tests, including every Sprint C test — confirms `migrations_transfrontieres` addition and the vivants-filtering change don't regress intra-pays behavior when no federation exists, since `pays_adjacents_ids` is `[]` for any unfederated monde)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/horloge_moteur.py briques/world-engine/test_horloge_moteur.py
git commit -m "feat(world-engine): horloge_moteur — migration transfrontière (âge préservé, verrou par timeout)"
```

---

## Task 5: `main.py` — routeur `/federation`

**Files:**
- Modify: `briques/world-engine/main.py`
- Create: `briques/world-engine/test_federation.py`

**Interfaces:**
- Consumes: every `stockage_federation.*` function from Task 1, plus existing `stockage_spatial.monde_existe`.
- Produces: the 8 HTTP endpoints described in the design's contract API section.

- [ ] **Step 1: Write failing HTTP-level tests**

Create `briques/world-engine/test_federation.py`:

```python
"""Tests HTTP du routeur /federation (Sprint D) — même motif que les blocs
/spatial et /horloge de test_api.py (DB temporaire posée par conftest.py)."""
import importlib

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_federation_creer_et_lire():
    r = client.post("/federation", json={"nom": "F1"})
    assert r.status_code == 200
    fid = r.json()["id"]
    assert r.json()["nom"] == "F1"

    lu = client.get(f"/federation/{fid}")
    assert lu.status_code == 200
    assert lu.json()["pays"] == []
    assert lu.json()["adjacences"] == []


def test_federation_lire_introuvable_404():
    assert client.get("/federation/id-inconnu").status_code == 404


def test_federation_rattacher_puis_lire():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]

    r = client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid, "nom": "France"})
    assert r.status_code == 200

    lu = client.get(f"/federation/{fid}").json()
    assert lu["pays"] == [{"monde_id": mid, "nom": "France", "cle_api": "public",
                            "rattache_le": lu["pays"][0]["rattache_le"]}]


def test_federation_rattacher_monde_introuvable_404():
    fid = client.post("/federation", json={}).json()["id"]
    assert client.post(f"/federation/{fid}/rattacher",
                        json={"monde_id": "inconnu"}).status_code == 404


def test_federation_rattacher_federation_introuvable_404():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    assert client.post("/federation/id-inconnu/rattacher",
                        json={"monde_id": mid}).status_code == 404


def test_federation_detacher():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid})

    r = client.post(f"/federation/{fid}/detacher", json={"monde_id": mid})
    assert r.status_code == 200
    assert client.get(f"/federation/{fid}").json()["pays"] == []


def test_federation_adjacence():
    fid = client.post("/federation", json={}).json()["id"]
    m1 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    m2 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 2}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m1})
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m2})

    r = client.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2})
    assert r.status_code == 200

    lu = client.get(f"/federation/{fid}").json()
    assert len(lu["adjacences"]) == 1


def test_federation_adjacence_pays_non_membre_404():
    fid = client.post("/federation", json={}).json()["id"]
    m1 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m1})
    assert client.post(f"/federation/{fid}/adjacence",
                        json={"monde_id_a": m1, "monde_id_b": "inconnu"}).status_code == 404


def test_federation_etat_population_agregee():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid})

    r = client.get(f"/federation/{fid}/etat")
    assert r.status_code == 200
    assert r.json() == {"federation_id": fid, "pays": [{"monde_id": mid, "population_vivante": 0}],
                         "population_totale": 0}


def test_federation_lister():
    fid = client.post("/federation", json={"nom": "Listee"}).json()["id"]
    noms = [f["nom"] for f in client.get("/federation").json()]
    assert "Listee" in noms


def test_federation_supprimer_ne_touche_pas_le_monde():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid})

    r = client.delete(f"/federation/{fid}")
    assert r.status_code == 204
    assert client.get(f"/federation/{fid}").status_code == 404
    assert client.get(f"/spatial/mondes/{mid}").status_code == 200


def test_federation_supprimer_introuvable_404():
    assert client.delete("/federation/id-inconnu").status_code == 404


def test_federation_cloisonnement_rattacher_exige_proprietaire_du_pays(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                 headers={"X-API-Key": "cle-y"}).json()["id"]
    # cle-x (créatrice de la fédération) essaie de rattacher un pays de cle-y : refusé
    r = c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid},
               headers={"X-API-Key": "cle-x"})
    assert r.status_code == 404
    # cle-y (propriétaire du pays) peut le rattacher elle-même
    r2 = c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid},
                headers={"X-API-Key": "cle-y"})
    assert r2.status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # resynchronise, même motif que test_api.py


def test_federation_multi_cle_api_visible_par_les_membres(monkeypatch):
    """Une fédération peut mélanger des cle_api différentes (voir design) : le
    créateur ET tout propriétaire d'un pays membre peuvent la voir, un tiers non
    plante en 404."""
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y,cle-z")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                 headers={"X-API-Key": "cle-y"}).json()["id"]
    c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid}, headers={"X-API-Key": "cle-y"})

    assert c.get(f"/federation/{fid}", headers={"X-API-Key": "cle-x"}).status_code == 200  # créatrice
    assert c.get(f"/federation/{fid}", headers={"X-API-Key": "cle-y"}).status_code == 200  # membre
    assert c.get(f"/federation/{fid}", headers={"X-API-Key": "cle-z"}).status_code == 404  # tiers
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)


def test_federation_adjacence_exige_etre_membre_pas_seulement_createur(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    m1 = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                headers={"X-API-Key": "cle-y"}).json()["id"]
    m2 = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 2},
                headers={"X-API-Key": "cle-y"}).json()["id"]
    c.post(f"/federation/{fid}/rattacher", json={"monde_id": m1}, headers={"X-API-Key": "cle-y"})
    c.post(f"/federation/{fid}/rattacher", json={"monde_id": m2}, headers={"X-API-Key": "cle-y"})

    # cle-x est créatrice mais possède 0 pays dans cette fédération → pas "membre"
    r = c.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2},
               headers={"X-API-Key": "cle-x"})
    assert r.status_code == 404
    r2 = c.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2},
                headers={"X-API-Key": "cle-y"})
    assert r2.status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)


def test_federation_supprimer_exige_le_createur(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    assert c.delete(f"/federation/{fid}", headers={"X-API-Key": "cle-y"}).status_code == 404
    assert c.delete(f"/federation/{fid}", headers={"X-API-Key": "cle-x"}).status_code == 204
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_federation.py -v`
Expected: FAIL — every test gets `404 Not Found` from FastAPI itself (no `/federation` route registered yet) instead of the expected status codes.

- [ ] **Step 3: Implement the `/federation` router in `main.py`**

Add the import (alongside the existing `import stockage_horloge` / `import stockage_spatial`):

```python
import stockage_federation
```

Add the Pydantic request bodies (alongside `CreerMonde`/`DemarrerHorloge`):

```python
class CreerFederation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: Optional[str] = None


class RattacherPays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monde_id: str
    nom: Optional[str] = None


class DetacherPays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monde_id: str


class DeclarerAdjacence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monde_id_a: str
    monde_id_b: str
```

Add the routes at the end of the file (after the `/horloge` routes, before `SCHEDULER_INTERVALLE_S`):

```python
def _federation_visible(federation_id: str, cle_api_val: str) -> dict | None:
    """Créateur OU tout propriétaire d'au moins un pays membre peuvent VOIR une
    fédération (voir design) — dérivé directement de `lire_federation` (déjà lu
    intégralement), pas d'une requête `membre()` séparée."""
    federation = stockage_federation.lire_federation(federation_id)
    if federation is None:
        return None
    if (federation["createur_cle_api"] != cle_api_val
            and not any(p["cle_api"] == cle_api_val for p in federation["pays"])):
        return None
    return federation


@app.post("/federation", tags=["federation"])
def federation_creer(body: CreerFederation, _cle: str = Depends(cle_api)):
    return stockage_federation.creer_federation(_cle, body.nom)


@app.post("/federation/{fid}/rattacher", tags=["federation"])
def federation_rattacher(fid: str, body: RattacherPays, _cle: str = Depends(cle_api)):
    """Exige que `_cle` soit propriétaire de `body.monde_id` — seul le propriétaire
    d'un pays peut le rattacher (voir design, consentement fort)."""
    if not stockage_spatial.monde_existe(_cle, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    resultat = stockage_federation.rattacher_pays(fid, body.monde_id, _cle, body.nom)
    if resultat is None:
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
    return resultat


@app.post("/federation/{fid}/detacher", tags=["federation"])
def federation_detacher(fid: str, body: DetacherPays, _cle: str = Depends(cle_api)):
    if not stockage_federation.detacher_pays(fid, body.monde_id, _cle):
        raise HTTPException(404, f"Pays '{body.monde_id}' non membre de la fédération '{fid}' pour cette clé.")
    return {"federation_id": fid, "monde_id": body.monde_id, "detache": True}


@app.post("/federation/{fid}/adjacence", tags=["federation"])
def federation_adjacence(fid: str, body: DeclarerAdjacence, _cle: str = Depends(cle_api)):
    if not stockage_federation.membre(fid, _cle):
        raise HTTPException(404, f"Fédération '{fid}' introuvable ou vous n'y êtes pas membre.")
    resultat = stockage_federation.declarer_adjacence(fid, body.monde_id_a, body.monde_id_b)
    if resultat is None:
        raise HTTPException(404, "Un des deux pays n'est pas membre de cette fédération.")
    return resultat


@app.get("/federation/{fid}", tags=["federation"])
def federation_lire(fid: str, _cle: str = Depends(cle_api)):
    federation = _federation_visible(fid, _cle)
    if federation is None:
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
    return federation


@app.get("/federation/{fid}/etat", tags=["federation"])
def federation_etat(fid: str, _cle: str = Depends(cle_api)):
    if _federation_visible(fid, _cle) is None:
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
    return stockage_federation.population_vivante_federation(fid)


@app.get("/federation", tags=["federation"])
def federation_lister(_cle: str = Depends(cle_api)):
    return stockage_federation.lister_federations(_cle)


@app.delete("/federation/{fid}", status_code=204, tags=["federation"])
def federation_supprimer(fid: str, _cle: str = Depends(cle_api)):
    if not stockage_federation.supprimer_federation(_cle, fid):
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_federation.py -v`
Expected: PASS (all 18 tests)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS (every test in the brique, Sprint A through D)

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_federation.py
git commit -m "feat(world-engine): routes /federation — créer/rattacher/détacher/adjacence/lire/état/lister/supprimer"
```

---

## Task 6: `manifest.json` — capacités `federation_*`

**Files:**
- Modify: `briques/world-engine/manifest.json`

**Interfaces:**
- Consumes: the 8 routes registered in Task 5 (`test_manifest_capacites.py`, already in the repo, will fail if a capacity points to a non-existent route).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Run the existing manifest filet test to confirm it currently passes (baseline)**

Run: `cd briques/world-engine && python -m pytest test_manifest_capacites.py -v`
Expected: PASS (2 tests — no `federation_*` capacity exists yet, so nothing to mismatch)

- [ ] **Step 2: Add the 8 new capacities to `manifest.json`**

In `briques/world-engine/manifest.json`, insert the following 8 objects into the `"capacites"` array, right after the last `horloge_lire` entry (before the closing `]`):

```json
    {
      "nom": "federation_creer",
      "description": "Crée une fédération de pays vide (nom optionnel). N'importe quelle clé API peut créer une fédération ; elle en devient créatrice.",
      "methode": "POST",
      "chemin": "/federation",
      "params": {
        "nom": {"type": "string", "description": "Nom d'affichage de la fédération (optionnel)."}
      },
      "action": true
    },
    {
      "nom": "federation_rattacher",
      "description": "Rattache un monde spatial existant à une fédération, où il devient un « pays ». Seul le propriétaire de ce monde peut le rattacher (jamais le créateur de la fédération pour le compte d'un tiers). Un nom d'affichage optionnel peut être donné, propre à cette fédération.",
      "methode": "POST",
      "chemin": "/federation/{fid}/rattacher",
      "params": {
        "fid": {"type": "string", "description": "Id de la fédération.", "requis": true},
        "monde_id": {"type": "string", "description": "Id du monde à rattacher comme pays.", "requis": true},
        "nom": {"type": "string", "description": "Nom d'affichage du pays dans cette fédération (optionnel)."}
      },
      "action": true
    },
    {
      "nom": "federation_detacher",
      "description": "Détache un pays d'une fédération (retire aussi ses adjacences dans cette fédération). Seul le propriétaire du pays peut le détacher, à tout moment. Le monde sous-jacent n'est jamais supprimé.",
      "methode": "POST",
      "chemin": "/federation/{fid}/detacher",
      "params": {
        "fid": {"type": "string", "description": "Id de la fédération.", "requis": true},
        "monde_id": {"type": "string", "description": "Id du pays à détacher.", "requis": true}
      },
      "action": true
    },
    {
      "nom": "federation_adjacence_declarer",
      "description": "Déclare que 2 pays déjà membres d'une même fédération sont adjacents, ouvrant la migration transfrontière entre eux lors des ticks. N'importe quel membre de la fédération (possédant au moins un pays dedans) peut déclarer ce lien.",
      "methode": "POST",
      "chemin": "/federation/{fid}/adjacence",
      "params": {
        "fid": {"type": "string", "description": "Id de la fédération.", "requis": true},
        "monde_id_a": {"type": "string", "description": "Id du premier pays (déjà membre).", "requis": true},
        "monde_id_b": {"type": "string", "description": "Id du second pays (déjà membre).", "requis": true}
      },
      "action": true
    },
    {
      "nom": "federation_lire",
      "description": "Lit une fédération : nom, créateur, liste des pays membres (avec leur nom d'affichage dans cette fédération) et des adjacences déclarées entre eux. Visible par le créateur ou tout propriétaire d'un pays membre.",
      "methode": "GET",
      "chemin": "/federation/{fid}",
      "params": {
        "fid": {"type": "string", "description": "Id de la fédération.", "requis": true}
      },
      "action": false
    },
    {
      "nom": "federation_etat_lire",
      "description": "Population vivante (hors habitants émigrés vers un autre pays) par pays membre d'une fédération, et le total agrégé. Même visibilité que federation_lire.",
      "methode": "GET",
      "chemin": "/federation/{fid}/etat",
      "params": {
        "fid": {"type": "string", "description": "Id de la fédération.", "requis": true}
      },
      "action": false
    },
    {
      "nom": "federation_lister",
      "description": "Liste les fédérations où la clé API appelante est créatrice ou possède au moins un pays membre.",
      "methode": "GET",
      "chemin": "/federation",
      "params": {},
      "action": false
    },
    {
      "nom": "federation_supprimer",
      "description": "Supprime une fédération (détache tous ses pays, jamais de suppression des mondes sous-jacents). Seule la clé API créatrice peut supprimer.",
      "methode": "DELETE",
      "chemin": "/federation/{fid}",
      "params": {
        "fid": {"type": "string", "description": "Id de la fédération à supprimer.", "requis": true}
      },
      "action": true
    }
```

Also update the top-level `description` field of `manifest.json` to reflect Sprint D — replace the sentence `"les mondes fédérés (pays→monde) et la mise à l'échelle (queue Redis/RabbitMQ) restent hors périmètre."` with:

```
"ET une fédération de mondes (chacun devenant un « pays ») avec migration transfrontière entre pays adjacents. Quatrième maillon du rapport d'architecture « World Engine » (Génome + Spatial + Horloge + Fédération) : la mise à l'échelle (queue Redis/RabbitMQ) reste hors périmètre."
```

And add `"federation_pays"` to the top-level `"offre"` array (alongside `"croisement_genome_cosmique"`, `"maillage_spatial"`, `"horloge_simulation"`).

- [ ] **Step 3: Run tests to verify the manifest filet still passes**

Run: `cd briques/world-engine && python -m pytest test_manifest_capacites.py -v`
Expected: PASS (2 tests — every new capacity's `(methode, chemin)` now matches a real route registered in Task 5; `test_noms_de_capacites_uniques` confirms no name collision)

- [ ] **Step 4: Run the full test suite one final time**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS (every test in the brique)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/manifest.json
git commit -m "docs(world-engine): manifest — 8 nouvelles capacités federation_*, Sprint D"
```

---

## Final check (not a task, run after Task 6)

- [ ] Re-read `docs/superpowers/specs/2026-08-24-world-engine-mondes-federes-design.md` top to bottom and confirm every decision has a corresponding implemented behavior (spec coverage self-check, done once at plan-writing time — see below).
- [ ] `cd briques/world-engine && python -m pytest -v` — full green suite.
- [ ] Update the project memory (`backlog-world-engine-genome-cosmique-phases-suivantes.md`) to mark Sprint D done, once code review is complete — not part of this plan (memory is updated by the conversation, not the implementation).
