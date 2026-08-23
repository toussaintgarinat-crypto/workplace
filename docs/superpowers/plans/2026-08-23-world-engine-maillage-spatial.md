# World Engine — Maillage spatial (Sprint B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à `world-engine` un maillage spatial (mondes Voronoï forkables, biomes/ressources par bruit cohérent) sur lequel les enfants du génome naissent automatiquement.

**Architecture:** Deux nouveaux modules purement additifs (`spatial.py` génération, `stockage_spatial.py` persistance SQLite dans la même base que `stockage.py`), un nouveau routeur `/spatial` dans `main.py`, et une extension ciblée de `POST /genome/croiser` (champ `sexe` sur les parents, `monde_id`, placement automatique). Aucun fichier existant n'est restructuré — uniquement étendu.

**Tech Stack:** FastAPI/Pydantic (existant), SQLite stdlib (existant), `scipy.spatial.Voronoi` (nouveau), `opensimplex.OpenSimplex` (nouveau).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-08-23-world-engine-maillage-spatial-design.md` — toute ambiguïté d'implémentation se résout en priorité par ce document.
- Cloisonnement par `cle_api` sur tous les endpoints `/spatial/*`, même motif que `/genome/*` (existant).
- 404 (jamais 403) sur une ressource absente ou appartenant à une autre `cle_api` — jamais confondu avec un 422 de forme.
- Aucune régression sur les 46 tests existants (Génome + Sprint A persistance).
- Seules nouvelles dépendances : `scipy`, `opensimplex` (ajoutées à `requirements.txt`).
- Espace de génération normalisé `[0, 1000] × [0, 1000]` (constante `spatial.TAILLE_MONDE`).
- 8 biomes fixes : `ocean`, `plaine`, `foret`, `colline`, `montagne`, `desert`, `toundra`, `marais`.
- `nb_cellules` borné `[10, 2000]` au niveau API (`Pydantic Field(ge=10, le=2000)`).
- Tests exécutés via le filet du monorepo (même Python que le `Dockerfile` de la brique, 3.12 — pas le Python du poste) : `scripts/tests_briques.sh world-engine` depuis la racine du repo, ou pour un test ciblé le one-liner Docker donné dans chaque tâche.

---

### Task 1: `spatial.py` — génération procédurale d'un monde (Voronoï + bruit cohérent)

**Files:**
- Create: `briques/world-engine/spatial.py`
- Create: `briques/world-engine/test_spatial.py`
- Modify: `briques/world-engine/requirements.txt`

**Interfaces:**
- Consumes: rien (fonctions pures, aucune dépendance à `stockage.py`/`stockage_spatial.py`/`main.py`).
- Produces (utilisé par Task 2 et Task 3) :
  - `spatial.TAILLE_MONDE: float` (= `1000.0`)
  - `spatial.BIOMES: tuple[str, ...]` (les 8 noms de biomes)
  - `spatial.RESSOURCES_PAR_BIOME: dict[str, list[str]]`
  - `spatial.determiner_biome(altitude: float, humidite: float) -> str`
  - `spatial.generer_monde(nb_cellules: int, seed: int) -> list[dict]` — chaque élément :
    `{"cellule_id": int, "x": float, "y": float, "biome": str, "ressources": list[str], "voisins": list[int]}`

- [ ] **Step 1: Écrire `requirements.txt` avec les 2 nouvelles dépendances**

```
# Brique world-engine — croisement de profils cosmiques + maillage spatial (Sprint B).
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
scipy==1.14.1
opensimplex==0.4.5.1
```

- [ ] **Step 2: Écrire les tests (échouent : `spatial.py` n'existe pas encore)**

Créer `briques/world-engine/test_spatial.py` :

```python
"""Tests de la génération procédurale du maillage spatial (spatial.py) — fonctions
pures et déterministes, aucune dépendance SQLite/FastAPI."""
import spatial


def test_determiner_biome_couvre_les_8_biomes():
    cas = [
        (-0.5, 0.0, "ocean"),
        (-0.1, 0.5, "marais"),
        (-0.1, 0.0, "plaine"),
        (0.2, -0.4, "desert"),
        (0.2, 0.0, "plaine"),
        (0.2, 0.5, "foret"),
        (0.5, -0.2, "toundra"),
        (0.5, 0.2, "colline"),
        (0.8, 0.0, "montagne"),
    ]
    for altitude, humidite, attendu in cas:
        assert spatial.determiner_biome(altitude, humidite) == attendu


def test_generer_monde_produit_le_bon_nombre_de_cellules():
    cellules = spatial.generer_monde(nb_cellules=20, seed=42)
    assert len(cellules) == 20
    assert {c["cellule_id"] for c in cellules} == set(range(20))


def test_generer_monde_cellules_dans_la_bounding_box():
    cellules = spatial.generer_monde(nb_cellules=30, seed=1)
    for c in cellules:
        assert 0.0 <= c["x"] <= spatial.TAILLE_MONDE
        assert 0.0 <= c["y"] <= spatial.TAILLE_MONDE


def test_generer_monde_voisinage_symetrique():
    cellules = spatial.generer_monde(nb_cellules=25, seed=7)
    par_id = {c["cellule_id"]: c for c in cellules}
    for c in cellules:
        for v in c["voisins"]:
            assert c["cellule_id"] in par_id[v]["voisins"], (
                f"{c['cellule_id']} voisin de {v} mais pas réciproque")


def test_generer_monde_pas_de_cellule_orpheline_sauf_cas_degenere():
    cellules = spatial.generer_monde(nb_cellules=25, seed=7)
    assert all(len(c["voisins"]) > 0 for c in cellules)
    # Sous le seuil Qhull (< 4 points), repli explicite sans voisin, sans exception.
    petit = spatial.generer_monde(nb_cellules=2, seed=7)
    assert all(c["voisins"] == [] for c in petit)


def test_generer_monde_deterministe_meme_seed():
    a = spatial.generer_monde(nb_cellules=15, seed=99)
    b = spatial.generer_monde(nb_cellules=15, seed=99)
    assert a == b


def test_generer_monde_seeds_differents_divergent():
    a = spatial.generer_monde(nb_cellules=15, seed=1)
    b = spatial.generer_monde(nb_cellules=15, seed=2)
    assert a != b


def test_ressources_toujours_valides_pour_leur_biome():
    cellules = spatial.generer_monde(nb_cellules=40, seed=3)
    for c in cellules:
        pool = spatial.RESSOURCES_PAR_BIOME[c["biome"]]
        assert all(r in pool for r in c["ressources"])
        assert len(c["ressources"]) <= 2
        assert len(c["ressources"]) == len(set(c["ressources"]))  # jamais de doublon
```

- [ ] **Step 3: Confirmer l'échec**

Run:
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q test_spatial.py"
```
Expected: `ModuleNotFoundError: No module named 'spatial'` (collection error).

- [ ] **Step 4: Écrire `spatial.py`**

```python
"""Génération procédurale d'un monde spatial : maillage Voronoï + biomes/ressources
dérivés d'un bruit cohérent (altitude/humidité). Fonctions pures, déterministes pour
un (nb_cellules, seed) donné — aucune I/O, aucune dépendance à `stockage_spatial`."""
from __future__ import annotations

import random

from opensimplex import OpenSimplex
from scipy.spatial import Voronoi

TAILLE_MONDE = 1000.0  # espace [0, TAILLE_MONDE] x [0, TAILLE_MONDE]

BIOMES = ("ocean", "plaine", "foret", "colline", "montagne", "desert", "toundra", "marais")

RESSOURCES_PAR_BIOME = {
    "ocean": ["poisson", "sel"],
    "plaine": ["ble", "betail"],
    "foret": ["bois", "gibier"],
    "colline": ["pierre", "cuivre"],
    "montagne": ["minerai", "pierre"],
    "desert": ["cristal", "petrole"],
    "toundra": ["fourrure", "gibier"],
    "marais": ["tourbe", "herbes"],
}


def determiner_biome(altitude: float, humidite: float) -> str:
    """Mappe 2 axes de bruit cohérent (chacun dans ~[-1, 1]) vers l'un des 8 biomes."""
    if altitude < -0.3:
        return "ocean"
    if altitude < 0.0:
        return "marais" if humidite > 0.4 else "plaine"
    if altitude < 0.4:
        if humidite < -0.3:
            return "desert"
        if humidite < 0.3:
            return "plaine"
        return "foret"
    if altitude < 0.7:
        return "toundra" if humidite < 0.0 else "colline"
    return "montagne"


def _voisins_par_voronoi(points: list[tuple[float, float]]) -> dict[int, list[int]]:
    """Adjacence des cellules via les arêtes du diagramme de Voronoï (`ridge_points` :
    paires d'index de points séparés par une seule arête, donc voisins directs). En
    dessous de 4 points, Qhull ne peut pas construire de diagramme 2D — repli
    explicite : aucun voisin, jamais une exception."""
    n = len(points)
    if n < 4:
        return {i: [] for i in range(n)}
    voisins: dict[int, set[int]] = {i: set() for i in range(n)}
    vor = Voronoi(points)
    for a, b in vor.ridge_points:
        voisins[int(a)].add(int(b))
        voisins[int(b)].add(int(a))
    return {i: sorted(v) for i, v in voisins.items()}


def _tirer_ressources(biome: str, rng: random.Random) -> list[str]:
    pool = RESSOURCES_PAR_BIOME[biome]
    n = rng.randint(0, min(2, len(pool)))
    return rng.sample(pool, n)


def generer_monde(nb_cellules: int, seed: int) -> list[dict]:
    """Génère `nb_cellules` cellules déterministes pour `seed` : positions Voronoï,
    biome dérivé d'un bruit cohérent, ressources tirées selon le biome. Chaque
    élément : {cellule_id, x, y, biome, ressources, voisins}."""
    rng = random.Random(seed)
    points = [(rng.uniform(0, TAILLE_MONDE), rng.uniform(0, TAILLE_MONDE)) for _ in range(nb_cellules)]
    voisins = _voisins_par_voronoi(points)

    bruit_altitude = OpenSimplex(seed=seed)
    bruit_humidite = OpenSimplex(seed=seed + 1)  # graine décorrélée de l'altitude

    cellules = []
    for i, (x, y) in enumerate(points):
        altitude = bruit_altitude.noise2(x / TAILLE_MONDE, y / TAILLE_MONDE)
        humidite = bruit_humidite.noise2(x / TAILLE_MONDE, y / TAILLE_MONDE)
        biome = determiner_biome(altitude, humidite)
        cellules.append({
            "cellule_id": i, "x": x, "y": y, "biome": biome,
            "ressources": _tirer_ressources(biome, rng), "voisins": voisins[i],
        })
    return cellules
```

- [ ] **Step 5: Confirmer le succès**

Run: même commande que Step 3.
Expected: `9 passed`. Si `pip install` échoue sur `scipy==1.14.1` ou `opensimplex==0.4.5.1` (wheel indisponible pour Python 3.12-slim), relâcher le pin vers la dernière version compatible publiée (`scipy>=1.14,<2`, `opensimplex>=0.4,<0.5`) et reformuler `requirements.txt` en conséquence avant de continuer.

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/spatial.py briques/world-engine/test_spatial.py briques/world-engine/requirements.txt
git commit -m "feat(world-engine): génération procédurale d'un monde spatial (Voronoï + bruit cohérent)"
```

---

### Task 2: `stockage_spatial.py` — persistance SQLite des mondes/cellules/placements

**Files:**
- Create: `briques/world-engine/stockage_spatial.py`
- Create: `briques/world-engine/test_stockage_spatial.py`

**Interfaces:**
- Consumes: `spatial.generer_monde(...)` output shape (Task 1) comme paramètre `cellules` de `creer_monde` ; `stockage.creer(...)` (existant) pour les fixtures de test uniquement.
- Produces (utilisé par Task 3 et Task 4) :
  - `stockage_spatial.creer_monde(cle_api: str, cellules: list[dict], seed: int, forked_from_id: str | None = None) -> dict` (meta : `id, nb_cellules, seed, forked_from_id, cree_le`)
  - `stockage_spatial.lister_mondes(cle_api: str) -> list[dict]`
  - `stockage_spatial.lire_monde(cle_api: str, monde_id: str) -> dict | None` (meta + `cellules: [{cellule_id, x, y, biome, ressources, voisins, enfants}]`)
  - `stockage_spatial.lire_cellule(cle_api: str, monde_id: str, cellule_id: int) -> dict | None`
  - `stockage_spatial.forker_monde(cle_api: str, monde_id: str) -> dict | None`
  - `stockage_spatial.supprimer_monde(cle_api: str, monde_id: str) -> bool`
  - `stockage_spatial.monde_existe(cle_api: str, monde_id: str) -> bool`
  - `stockage_spatial.nb_cellules_monde(monde_id: str) -> int | None`
  - `stockage_spatial.voisins_cellule(monde_id: str, cellule_id: int) -> list[int] | None`
  - `stockage_spatial.placement_cellule(monde_id: str, enfant_id: str) -> int | None`
  - `stockage_spatial.placer(monde_id: str, enfant_id: str, cellule_id: int) -> None`

- [ ] **Step 1: Écrire les tests (échouent : `stockage_spatial.py` n'existe pas encore)**

Créer `briques/world-engine/test_stockage_spatial.py` :

```python
"""Tests du stockage SQLite du maillage spatial (mondes/cellules/placements) —
Sprint B. Même motif que test_stockage.py (DB temporaire posée par conftest.py)."""
import stockage
import stockage_spatial


def _cellules_factices(n=3):
    return [{"cellule_id": i, "x": float(i) * 10, "y": float(i) * 5, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]


def test_creer_monde_puis_lire():
    meta = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=42)
    assert isinstance(meta["id"], str) and meta["id"]
    assert meta["nb_cellules"] == 3
    assert meta["seed"] == 42
    assert meta["forked_from_id"] is None

    monde = stockage_spatial.lire_monde("cle-a", meta["id"])
    assert monde["id"] == meta["id"]
    assert len(monde["cellules"]) == 3
    assert monde["cellules"][0]["biome"] == "plaine"
    assert monde["cellules"][0]["ressources"] == ["ble"]
    assert monde["cellules"][0]["enfants"] == []


def test_lire_monde_introuvable_renvoie_none():
    assert stockage_spatial.lire_monde("cle-a", "id-inconnu") is None


def test_lire_monde_cloisonne_par_cle_api():
    meta = stockage_spatial.creer_monde("cle-b", _cellules_factices(3), seed=1)
    assert stockage_spatial.lire_monde("cle-b", meta["id"]) is not None
    assert stockage_spatial.lire_monde("autre-cle", meta["id"]) is None


def test_lister_mondes_cloisonne_et_ordonne():
    stockage_spatial.creer_monde("cle-c", _cellules_factices(3), seed=1)
    m2 = stockage_spatial.creer_monde("cle-c", _cellules_factices(3), seed=2)
    resultats = stockage_spatial.lister_mondes("cle-c")
    assert resultats[0]["id"] == m2["id"]  # plus récent d'abord
    assert "cellules" not in resultats[0]  # liste allégée
    assert stockage_spatial.lister_mondes("cle-vide") == []


def test_monde_existe():
    meta = stockage_spatial.creer_monde("cle-d", _cellules_factices(3), seed=1)
    assert stockage_spatial.monde_existe("cle-d", meta["id"]) is True
    assert stockage_spatial.monde_existe("autre-cle", meta["id"]) is False
    assert stockage_spatial.monde_existe("cle-d", "id-inconnu") is False


def test_lire_cellule():
    meta = stockage_spatial.creer_monde("cle-e", _cellules_factices(3), seed=1)
    cellule = stockage_spatial.lire_cellule("cle-e", meta["id"], 1)
    assert cellule["cellule_id"] == 1
    assert cellule["voisins"] == [0, 2]
    assert stockage_spatial.lire_cellule("cle-e", meta["id"], 99) is None
    assert stockage_spatial.lire_cellule("autre-cle", meta["id"], 1) is None


def test_voisins_cellule():
    meta = stockage_spatial.creer_monde("cle-f", _cellules_factices(3), seed=1)
    assert stockage_spatial.voisins_cellule(meta["id"], 0) == [1, 2]
    assert stockage_spatial.voisins_cellule(meta["id"], 99) is None


def test_nb_cellules_monde():
    meta = stockage_spatial.creer_monde("cle-g", _cellules_factices(5), seed=1)
    assert stockage_spatial.nb_cellules_monde(meta["id"]) == 5
    assert stockage_spatial.nb_cellules_monde("id-inconnu") is None


def test_placer_et_lire_avec_enfants():
    meta = stockage_spatial.creer_monde("cle-h", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-h", "Nova", "Test", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 1)
    assert stockage_spatial.placement_cellule(meta["id"], eid) == 1

    monde = stockage_spatial.lire_monde("cle-h", meta["id"])
    cellule_1 = next(c for c in monde["cellules"] if c["cellule_id"] == 1)
    assert cellule_1["enfants"] == [{"id": eid, "prenoms": "Nova", "nom": "Test"}]

    cellule = stockage_spatial.lire_cellule("cle-h", meta["id"], 1)
    assert cellule["enfants"] == [{"id": eid, "prenoms": "Nova", "nom": "Test"}]


def test_placement_cellule_absent_renvoie_none():
    meta = stockage_spatial.creer_monde("cle-i", _cellules_factices(3), seed=1)
    assert stockage_spatial.placement_cellule(meta["id"], "enfant-inconnu") is None


def test_placer_remplace_le_placement_precedent():
    meta = stockage_spatial.creer_monde("cle-j", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-j", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 0)
    stockage_spatial.placer(meta["id"], eid, 2)
    assert stockage_spatial.placement_cellule(meta["id"], eid) == 2


def test_forker_monde_copie_cellules_et_placements():
    meta = stockage_spatial.creer_monde("cle-k", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-k", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 1)

    fork = stockage_spatial.forker_monde("cle-k", meta["id"])
    assert fork["forked_from_id"] == meta["id"]
    assert fork["id"] != meta["id"]
    assert fork["nb_cellules"] == 3
    assert fork["seed"] == 1
    assert stockage_spatial.placement_cellule(fork["id"], eid) == 1

    monde_fork = stockage_spatial.lire_monde("cle-k", fork["id"])
    assert len(monde_fork["cellules"]) == 3


def test_forker_monde_independant_de_loriginal():
    meta = stockage_spatial.creer_monde("cle-l", _cellules_factices(3), seed=1)
    fork = stockage_spatial.forker_monde("cle-l", meta["id"])
    eid = stockage.creer("cle-l", "Nouveau", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(fork["id"], eid, 0)  # placement APRÈS le fork, sur le fork seul
    assert stockage_spatial.placement_cellule(fork["id"], eid) == 0
    assert stockage_spatial.placement_cellule(meta["id"], eid) is None  # jamais propagé à l'original


def test_forker_monde_introuvable_renvoie_none():
    assert stockage_spatial.forker_monde("cle-m", "id-inconnu") is None


def test_supprimer_monde_cascade():
    meta = stockage_spatial.creer_monde("cle-n", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-n", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 0)

    assert stockage_spatial.supprimer_monde("cle-n", meta["id"]) is True
    assert stockage_spatial.lire_monde("cle-n", meta["id"]) is None
    assert stockage_spatial.voisins_cellule(meta["id"], 0) is None
    assert stockage_spatial.placement_cellule(meta["id"], eid) is None


def test_supprimer_monde_introuvable_renvoie_false():
    assert stockage_spatial.supprimer_monde("cle-n", "id-inconnu") is False


def test_supprimer_monde_cloisonne_par_cle_api():
    meta = stockage_spatial.creer_monde("cle-o", _cellules_factices(3), seed=1)
    assert stockage_spatial.supprimer_monde("autre-cle", meta["id"]) is False
    assert stockage_spatial.lire_monde("cle-o", meta["id"]) is not None
```

- [ ] **Step 2: Confirmer l'échec**

Run:
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q test_stockage_spatial.py"
```
Expected: `ModuleNotFoundError: No module named 'stockage_spatial'`.

- [ ] **Step 3: Écrire `stockage_spatial.py`**

```python
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
    with _conn() as c:
        r = c.execute("SELECT voisins FROM cellules WHERE monde_id=? AND cellule_id=?",
                       (monde_id, cellule_id)).fetchone()
    return json.loads(r["voisins"]) if r else None


def placement_cellule(monde_id: str, enfant_id: str) -> int | None:
    with _conn() as c:
        r = c.execute("SELECT cellule_id FROM placements WHERE monde_id=? AND enfant_id=?",
                       (monde_id, enfant_id)).fetchone()
    return r["cellule_id"] if r else None


def placer(monde_id: str, enfant_id: str, cellule_id: int) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO placements (enfant_id, monde_id, cellule_id, place_le) "
                   "VALUES (?,?,?,?)",
                   (enfant_id, monde_id, cellule_id, datetime.now(timezone.utc).isoformat()))


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
```

- [ ] **Step 4: Confirmer le succès**

Run: même commande que Step 2, en ciblant les deux fichiers de test :
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q test_stockage_spatial.py test_spatial.py"
```
Expected: `26 passed` (9 de Task 1 + 17 de Task 2).

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/stockage_spatial.py briques/world-engine/test_stockage_spatial.py
git commit -m "feat(world-engine): persistance SQLite des mondes/cellules/placements spatiaux"
```

---

### Task 3: `main.py` — routeur `/spatial` (créer/forker/lister/lire/supprimer)

**Files:**
- Modify: `briques/world-engine/main.py`
- Modify: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `spatial.generer_monde` (Task 1), `stockage_spatial.creer_monde/lister_mondes/lire_monde/lire_cellule/forker_monde/supprimer_monde` (Task 2), `cle_api` dependency (existant dans `main.py`).
- Produces (utilisé par Task 4) : les 6 routes `/spatial/*` sont montées sur `app` ; `import stockage_spatial` et `import spatial` disponibles au niveau module de `main.py`.

- [ ] **Step 1: Ajouter les imports et le modèle Pydantic dans `main.py`**

En tête de fichier, après `import stockage` (ligne 18) :

```python
import spatial
import stockage
import stockage_spatial
```

Après la classe `Croisement` existante (avant `def _detail`), ajouter :

```python
class CreerMonde(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nb_cellules: int = Field(ge=10, le=2000)
    seed: Optional[int] = None
```

- [ ] **Step 2: Écrire les tests API (échouent : routes absentes → 404 générique FastAPI)**

Ajouter en tête de `test_api.py`, après `import stockage` :

```python
import stockage_spatial
```

Ajouter à la fin de `test_api.py` :

```python
def test_spatial_monde_creer_puis_lire():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 42})
    assert r.status_code == 200
    meta = r.json()
    assert meta["nb_cellules"] == 10
    assert meta["seed"] == 42

    r2 = client.get(f"/spatial/mondes/{meta['id']}")
    assert r2.status_code == 200
    monde = r2.json()
    assert len(monde["cellules"]) == 10


def test_spatial_monde_creer_sans_seed_genere_un_seed():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10})
    assert r.status_code == 200
    assert isinstance(r.json()["seed"], int)


def test_spatial_monde_creer_nb_cellules_hors_bornes_422():
    assert client.post("/spatial/mondes", json={"nb_cellules": 5}).status_code == 422
    assert client.post("/spatial/mondes", json={"nb_cellules": 3000}).status_code == 422


def test_spatial_mondes_lister():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1})
    mid = r.json()["id"]
    r2 = client.get("/spatial/mondes")
    assert any(m["id"] == mid for m in r2.json())
    assert "cellules" not in r2.json()[0]


def test_spatial_monde_lire_introuvable_404():
    assert client.get("/spatial/mondes/id-inconnu").status_code == 404


def test_spatial_cellule_lire():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    r = client.get(f"/spatial/mondes/{mid}/cellules/0")
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 0
    assert client.get(f"/spatial/mondes/{mid}/cellules/999").status_code == 404


def test_spatial_monde_forker():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    r = client.post(f"/spatial/mondes/{mid}/forker")
    assert r.status_code == 200
    fork = r.json()
    assert fork["forked_from_id"] == mid
    assert fork["id"] != mid
    assert client.get(f"/spatial/mondes/{fork['id']}").status_code == 200


def test_spatial_monde_forker_introuvable_404():
    assert client.post("/spatial/mondes/id-inconnu/forker").status_code == 404


def test_spatial_monde_supprimer():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    r = client.delete(f"/spatial/mondes/{mid}")
    assert r.status_code == 204
    assert client.get(f"/spatial/mondes/{mid}").status_code == 404


def test_spatial_monde_supprimer_introuvable_404():
    assert client.delete("/spatial/mondes/id-inconnu").status_code == 404


def test_spatial_mondes_cloisonnes_par_cle_api(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                  headers={"X-API-Key": "cle-x"}).json()["id"]
    r_x = c.get(f"/spatial/mondes/{mid}", headers={"X-API-Key": "cle-x"})
    r_y = c.get(f"/spatial/mondes/{mid}", headers={"X-API-Key": "cle-y"})
    assert r_x.status_code == 200
    assert r_y.status_code == 404
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # resynchronise après reload, même motif que les autres
                                    # tests d'auth de ce fichier.
```

- [ ] **Step 3: Confirmer l'échec**

Run:
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q -k spatial_monde or spatial_cellule or spatial_mondes"
```
Expected: échecs 404/405 (routes `/spatial/*` inexistantes).

- [ ] **Step 4: Ajouter les 6 routes dans `main.py`**

Après la fonction `genome_arbre_lire` (fin actuelle du fichier), ajouter :

```python
@app.post("/spatial/mondes", tags=["spatial"])
def spatial_monde_creer(body: CreerMonde, _cle: str = Depends(cle_api)):
    """Génère et persiste un nouveau monde : maillage Voronoï, biomes/ressources
    dérivés d'un bruit cohérent. `seed` généré si absent (renvoyé dans la réponse,
    même (nb_cellules, seed) ⇒ même monde)."""
    seed = body.seed if body.seed is not None else Random().randrange(2**31)
    cellules = spatial.generer_monde(body.nb_cellules, seed)
    return stockage_spatial.creer_monde(_cle, cellules, seed)


@app.post("/spatial/mondes/{mid}/forker", tags=["spatial"])
def spatial_monde_forker(mid: str, _cle: str = Depends(cle_api)):
    """Clone un monde existant (cellules + enfants placés) sous un nouvel id
    indépendant. Le monde source n'est jamais modifié."""
    nouveau = stockage_spatial.forker_monde(_cle, mid)
    if nouveau is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return nouveau


@app.get("/spatial/mondes", tags=["spatial"])
def spatial_mondes_lister(_cle: str = Depends(cle_api)):
    return stockage_spatial.lister_mondes(_cle)


@app.get("/spatial/mondes/{mid}", tags=["spatial"])
def spatial_monde_lire(mid: str, _cle: str = Depends(cle_api)):
    monde = stockage_spatial.lire_monde(_cle, mid)
    if monde is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return monde


@app.get("/spatial/mondes/{mid}/cellules/{cid}", tags=["spatial"])
def spatial_cellule_lire(mid: str, cid: int, _cle: str = Depends(cle_api)):
    cellule = stockage_spatial.lire_cellule(_cle, mid, cid)
    if cellule is None:
        raise HTTPException(404, f"Cellule '{cid}' du monde '{mid}' introuvable.")
    return cellule


@app.delete("/spatial/mondes/{mid}", status_code=204, tags=["spatial"])
def spatial_monde_supprimer(mid: str, _cle: str = Depends(cle_api)):
    if not stockage_spatial.supprimer_monde(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
```

- [ ] **Step 5: Confirmer le succès**

Run:
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q"
```
Expected: tous les tests passent (existants + Task 1/2/3), aucune régression sur les 46 tests Sprint A/Génome.

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): routeur /spatial — créer/forker/lister/lire/supprimer un monde"
```

---

### Task 4: `genome_croiser` — champ `sexe`, `monde_id`, placement automatique

**Files:**
- Modify: `briques/world-engine/main.py`
- Modify: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `stockage_spatial.monde_existe/placement_cellule/voisins_cellule/nb_cellules_monde/placer` (Task 2) ; `FicheParent`/`ReferenceParent`/`Croisement` (existants, modifiés ici).
- Produces: réponse de `POST /genome/croiser` enrichie d'un champ `cellule_id: int | None`.

- [ ] **Step 1: Modifier les modèles Pydantic dans `main.py`**

Modifier la ligne d'import (ligne 10) :
```python
from typing import Optional, Union
```
en :
```python
from typing import Literal, Optional, Union
```

Modifier `FicheParent` (ajouter le champ `sexe`) :
```python
class FicheParent(BaseModel):
    """Même forme que FicheHolistique côté personnages — sous-ensemble minimal
    pour ce prototype (pas de systeme_numerologie/langue_sortie ici, YAGNI).

    heure_naissance/latitude/longitude restent optionnels ICI (comme côté
    personnages, repli honnête), mais sont EFFECTIVEMENT nécessaires : sans eux,
    personnages renvoie un theme_complet dégradé et _exiger_theme_complet() refuse
    la fiche avec un 422 explicite plutôt que de laisser le calcul planter plus loin."""
    model_config = ConfigDict(extra="forbid")

    prenoms: str = ""
    nom: str = ""
    date_naissance: str = ""
    heure_naissance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset: Optional[float] = None
    sexe: Optional[Literal["F", "M"]] = None  # rôle dans CE croisement (placement, Sprint B) —
                                                # pas un trait de la personne, jamais deviné.
```

Modifier `ReferenceParent` (ajouter le champ `sexe`) :
```python
class ReferenceParent(BaseModel):
    """Référence à un enfant déjà stocké (Sprint A), utilisable comme parent d'un
    nouveau croisement — évite de recopier date/heure/lieu de naissance d'un
    enfant déjà généré. `extra="forbid"` sur les deux modèles rend le choix entre
    fiche brute et référence déterministe pour Pydantic (aucun input valide ne
    peut matcher les deux à la fois)."""
    model_config = ConfigDict(extra="forbid")

    id: str
    sexe: Optional[Literal["F", "M"]] = None
```

Modifier `Croisement` (ajouter `monde_id`) :
```python
class Croisement(BaseModel):
    parent_a: ParentInput
    parent_b: ParentInput
    prenoms_enfant: str = ""
    nom_enfant: str = ""
    latitude_enfant: float       # jamais deviné : requis
    longitude_enfant: float      # jamais deviné : requis
    heure_naissance_enfant: str  # "HH:MM" — jamais deviné : requis (sans elle, personnages
                                  # ne calcule qu'un theme_complet dégradé, sans dix_corps)
    utc_offset_enfant: float     # jamais deviné : requis (un défaut à 0 décale l'ascendant
                                  # de 15-30° pour un lieu européen et fausse maisons/dominantes)
    annee_enfant: Optional[int] = Field(default=None, ge=1, le=9999)
    mutation_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    monde_id: Optional[str] = None  # place l'enfant à sa naissance (Sprint B) — absent = non placé
```

- [ ] **Step 2: Écrire les tests (échouent : `sexe`/`monde_id` rejetés par `extra="forbid"`, ou `cellule_id` absent de la réponse)**

Ajouter dans `test_api.py`, juste avant `def test_genome_enfants_lister_et_lire():` :

```python
def _monde_factice(n=10):
    """Monde déterministe pour les tests de placement : chaque cellule i a pour
    SEULE voisine (i+1)%n — évite toute dépendance à la géométrie Voronoï réelle
    (déjà testée dans test_spatial.py/test_stockage_spatial.py)."""
    cellules = [{"cellule_id": i, "x": float(i), "y": float(i), "biome": "plaine",
                 "ressources": [], "voisins": [(i + 1) % n]} for i in range(n)]
    return stockage_spatial.creer_monde("public", cellules, seed=1)


@respx.mock
def test_genome_croiser_place_enfant_voisin_du_parent_si_place():
    monde = _monde_factice()
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid_mere, 0)  # seule voisine de 0 : cellule 1

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_mere, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 1


@respx.mock
def test_genome_croiser_sans_monde_id_pas_de_placement():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    assert r.json()["cellule_id"] is None


@respx.mock
def test_genome_croiser_parent_fiche_brute_placement_aleatoire_borne():
    monde = _monde_factice()
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {**_FICHE_A, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert 0 <= r.json()["cellule_id"] < 10


@respx.mock
def test_genome_croiser_parent_stocke_non_place_placement_aleatoire_borne():
    monde = _monde_factice()
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    # eid_mere n'a jamais été placé sur aucun monde

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_mere, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert 0 <= r.json()["cellule_id"] < 10


@respx.mock
def test_genome_croiser_parent_place_dans_un_autre_monde_placement_aleatoire_borne():
    monde_a = _monde_factice()
    monde_b = _monde_factice()
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde_a["id"], eid_mere, 0)  # placée dans monde_a...

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_mere, "sexe": "F"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde_b["id"]})  # ...mais le croisement cible monde_b
    assert r.status_code == 200
    assert 0 <= r.json()["cellule_id"] < 10


@respx.mock
def test_genome_croiser_monde_id_introuvable_404():
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "monde_id": "id-inconnu"})
    assert r.status_code == 404


@respx.mock
def test_genome_croiser_parent_b_marque_f_devient_reference():
    monde = _monde_factice()
    theme_pere = _portrait_factice("Mars", "Bélier", "Bélier")
    theme_mere = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid_pere = stockage.creer("public", "Pere", "", None, None, theme_pere, "d", {"resume": {}}, False)
    eid_mere = stockage.creer("public", "Mere", "", None, None, theme_mere, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid_mere, 3)  # seule voisine de 3 : cellule 4

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_pere, "sexe": "M"}, "parent_b": {"id": eid_mere, "sexe": "F"},
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 4


@respx.mock
def test_genome_croiser_deux_parents_marques_f_parent_a_gagne():
    monde = _monde_factice()
    theme_a = _portrait_factice("Mercure", "Vierge", "Vierge")
    theme_b = _portrait_factice("Mars", "Bélier", "Bélier")
    eid_a = stockage.creer("public", "A", "", None, None, theme_a, "d", {"resume": {}}, False)
    eid_b = stockage.creer("public", "B", "", None, None, theme_b, "d", {"resume": {}}, False)
    stockage_spatial.placer(monde["id"], eid_a, 0)   # seule voisine de 0 : cellule 1
    stockage_spatial.placer(monde["id"], eid_b, 5)   # seule voisine de 5 : cellule 6 (disjoint de 1)

    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid_a, "sexe": "F"}, "parent_b": {"id": eid_b, "sexe": "F"},
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0,
        "monde_id": monde["id"]})
    assert r.status_code == 200
    assert r.json()["cellule_id"] == 1  # parent_a (0→1), pas parent_b (5→6)
```

- [ ] **Step 3: Confirmer l'échec**

Run:
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q -k placer_ or monde_id or marque_f"
```
Expected: échecs — `sexe`/`monde_id` rejetés en 422 (`extra="forbid"`), ou `cellule_id` absent/`KeyError` dans les assertions.

- [ ] **Step 4: Modifier `genome_croiser` dans `main.py`**

Ajouter avant la fonction `genome_croiser` (après `_noeud_arbre` n'existe pas encore à ce point du fichier — insérer juste après `_theme_parent`, avant `@app.post("/genome/croiser"...)`) :

```python
def _parent_reference_naissance(parent_a: ParentInput, parent_b: ParentInput) -> ParentInput:
    """Parent de référence pour l'héritage de position à la naissance : celui
    marqué sexe="F" ; à défaut (aucun "F", ou les deux marqués "F"), parent_a."""
    if parent_a.sexe == "F" and parent_b.sexe != "F":
        return parent_a
    if parent_b.sexe == "F" and parent_a.sexe != "F":
        return parent_b
    return parent_a


def _cellule_naissance(monde_id: str, parent_ref: ParentInput, rng: Random) -> int:
    """Cellule de naissance dans `monde_id` (déjà vérifié existant par l'appelant) :
    voisine aléatoire de la cellule du parent de référence s'il y est déjà placé
    DANS CE monde, sinon cellule aléatoire bornée du monde."""
    voisins = None
    if isinstance(parent_ref, ReferenceParent):
        cellule_parent = stockage_spatial.placement_cellule(monde_id, parent_ref.id)
        if cellule_parent is not None:
            voisins = stockage_spatial.voisins_cellule(monde_id, cellule_parent)
    if voisins:
        return rng.choice(voisins)
    return rng.randrange(stockage_spatial.nb_cellules_monde(monde_id))
```

Modifier `genome_croiser` : ajouter la validation de `monde_id` juste après le refus d'auto-croisement, et le placement juste après la persistance de l'enfant, et enrichir la réponse finale :

```python
@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel, avec
    un récit d'hérédité en post-traitement — coïncidence assumée, pas une vraie
    génétique astrale (voir `fusion.comparer_dix_corps`). Si `monde_id` est fourni,
    l'enfant est aussi placé sur ce monde spatial (Sprint B) — voisin de la cellule
    du parent de référence (sexe="F", sinon parent_a) s'il y est déjà, sinon cellule
    aléatoire bornée."""
    if (isinstance(body.parent_a, ReferenceParent) and isinstance(body.parent_b, ReferenceParent)
            and body.parent_a.id == body.parent_b.id):
        raise HTTPException(422, "Un enfant ne peut pas être croisé avec lui-même.")
    if body.monde_id is not None and not stockage_spatial.monde_existe(_cle, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    theme_a = await _theme_parent(body.parent_a, _cle, "Parent A")
    theme_b = await _theme_parent(body.parent_b, _cle, "Parent B")

    description, mutation_survenue = fusion.fusionner_description(
        theme_a, theme_b, body.mutation_rate, Random())

    try:
        rri = await personnages_client.recherche_inverse(description)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if rri.status_code != 200:
        _propager_ou_502(rri, "Recherche inverse")
    signes = rri.json().get("signes") or []
    if not signes:
        raise HTTPException(422, "Impossible de dériver un signe pour l'enfant à partir "
                                  "de cette description fusionnée.")

    annee = body.annee_enfant or date.today().year
    date_enfant = fusion.date_pour_signe(signes[0]["signe"], annee)

    fiche_enfant = {
        "prenoms": body.prenoms_enfant, "nom": body.nom_enfant,
        "date_naissance": date_enfant, "heure_naissance": body.heure_naissance_enfant,
        "latitude": body.latitude_enfant, "longitude": body.longitude_enfant,
        "utc_offset": body.utc_offset_enfant,
    }
    try:
        re_ = await personnages_client.portrait(fiche_enfant)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if re_.status_code != 200:
        _propager_ou_502(re_, "Enfant")
    theme_enfant = re_.json()
    _exiger_theme_complet(theme_enfant, "Enfant")

    heredite = fusion.comparer_dix_corps(
        theme_enfant["theme_complet"]["dix_corps"],
        theme_a["theme_complet"]["dix_corps"],
        theme_b["theme_complet"]["dix_corps"])

    parent_a_id = body.parent_a.id if isinstance(body.parent_a, ReferenceParent) else None
    parent_b_id = body.parent_b.id if isinstance(body.parent_b, ReferenceParent) else None
    try:
        enfant_id = stockage.creer(_cle, body.prenoms_enfant, body.nom_enfant,
                                    parent_a_id, parent_b_id, theme_enfant,
                                    description, heredite, mutation_survenue)
        avertissement = None
    except Exception as e:
        enfant_id = None
        avertissement = f"Enfant calculé mais non persisté : {e}"

    cellule_id = None
    if body.monde_id is not None and enfant_id is not None:
        try:
            parent_ref = _parent_reference_naissance(body.parent_a, body.parent_b)
            cellule_id = _cellule_naissance(body.monde_id, parent_ref, Random())
            stockage_spatial.placer(body.monde_id, enfant_id, cellule_id)
        except Exception as e:
            cellule_id = None
            avertissement = f"Enfant persisté mais non placé : {e}"

    return {"parentA": theme_a, "parentB": theme_b, "description_genome": description,
            "enfant": theme_enfant, "heredite": heredite, "mutation_survenue": mutation_survenue,
            "enfant_id": enfant_id, "cellule_id": cellule_id, "avertissement": avertissement}
```

- [ ] **Step 5: Confirmer le succès**

Run:
```bash
docker run --rm -v "$(pwd):/monorepo" -w /monorepo/briques/world-engine \
  -e PYTHONPATH=/monorepo python:3.12-slim sh -c \
  "pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio httpx >/dev/null 2>&1 && python -m pytest -q"
```
Expected: tous les tests passent (existants + Task 1/2/3/4), aucune régression.

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): placement automatique des enfants à la naissance (champ sexe, monde_id)"
```

---

### Task 5: Manifest, README, commentaire docker-compose

**Files:**
- Modify: `briques/world-engine/manifest.json`
- Modify: `briques/world-engine/README.md`
- Modify: `briques/world-engine/docker-compose.yml`

**Interfaces:**
- Consumes: les 6 routes `/spatial/*` (Task 3) et le contrat modifié de `POST /genome/croiser` (Task 4) — doivent déjà exister pour que `test_manifest_capacites.py` (existant) valide les nouvelles entrées.
- Produces: rien consommé par une tâche suivante — dernière tâche du sprint.

- [ ] **Step 1: Mettre à jour `manifest.json`**

Modifier le champ `description` racine (ligne 5) :
```json
  "description": "Prototype exploratoire : croise 2 profils cosmiques (via la brique personnages) pour produire un enfant dont le thème astral est calculé à une vraie date, avec un récit d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents — coïncidence assumée, pas une vraie génétique astrale). Persiste les lignées (arbre généalogique) ET un maillage spatial (mondes Voronoï forkables, biomes/ressources) sur lequel les enfants naissent. Deuxième maillon du rapport d'architecture « World Engine » (Génome + Spatial) : la simulation temporelle (horloge/ticks) et le compilateur de packs restent hors périmètre.",
```

Modifier `offre` (ligne 13) :
```json
  "offre": ["croisement_genome_cosmique", "maillage_spatial"],
```

Dans la capacité `genome_croiser` (première capacité du tableau), modifier les descriptions de `parent_a` et `parent_b` pour documenter `sexe`, et ajouter un paramètre `monde_id` :

```json
        "parent_a": {
          "type": "object",
          "description": "Fiche du parent A : prenoms, nom, date_naissance ('AAAA-MM-JJ', requis), heure_naissance ('HH:MM'), latitude, longitude, utc_offset, sexe ('F'/'M', optionnel — désigne le parent de référence pour l'héritage de position si monde_id est fourni) — OU {\"id\": \"...\"} référençant un enfant déjà stocké (même champ sexe optionnel accepté sur la référence). heure_naissance/latitude/longitude sont EFFECTIVEMENT nécessaires pour une fiche brute : sans eux, personnages renvoie un thème dégradé et l'appel échoue en 422.",
          "requis": true
        },
        "parent_b": {
          "type": "object",
          "description": "Fiche du parent B, même forme que parent_a (fiche brute OU {\"id\": \"...\"}, mêmes contraintes, même champ sexe optionnel).",
          "requis": true
        },
```

Et après le paramètre `mutation_rate` de `genome_croiser`, ajouter :
```json
        "monde_id": {
          "type": "string",
          "description": "Id d'un monde spatial existant où placer l'enfant à sa naissance (optionnel, Sprint B). Absent ⇒ enfant non placé (cellule_id: null dans la réponse). Présent ⇒ l'enfant nait dans une cellule voisine de celle du parent de référence (marqué sexe:'F' ; à défaut parent_a) s'il y est déjà placé DANS CE MÊME monde, sinon dans une cellule aléatoire bornée du monde. monde_id introuvable ou d'une autre clé API → 404."
        }
```

Et dans la description de la capacité `genome_croiser` elle-même, ajouter une phrase sur `cellule_id` :
```json
      "description": "Croise 2 profils cosmiques (fiches parents avec date/heure/lieu de naissance) pour produire un enfant : thème astral calculé à une vraie date indépendante, avec un récit d'hérédité comparant les 10 corps de l'enfant aux 2 parents. Le lieu de naissance de l'enfant est indispensable (jamais deviné). L'enfant produit est automatiquement stocké (enfant_id dans la réponse) et peut être réutilisé comme parent d'un croisement suivant. Si monde_id est fourni, l'enfant est aussi placé sur ce monde (cellule_id dans la réponse, null si monde_id absent).",
```

Ajouter 6 nouvelles capacités à la fin du tableau `capacites` (après `genome_arbre_lire`, avant `genome_enfant_supprimer` ou après — l'ordre n'a pas d'importance fonctionnelle, les ajouter juste après la dernière capacité `genome_enfant_supprimer`) :

```json
    {
      "nom": "spatial_monde_creer",
      "description": "Génère et persiste un nouveau monde spatial : maillage de cellules Voronoï, biomes et ressources dérivés d'un bruit cohérent (altitude/humidité). nb_cellules borné 10-2000. seed optionnel (généré et renvoyé si absent) — mêmes (nb_cellules, seed) ⇒ même monde, reproductible.",
      "methode": "POST",
      "chemin": "/spatial/mondes",
      "params": {
        "nb_cellules": {
          "type": "integer",
          "description": "Nombre de cellules du monde (10 à 2000).",
          "requis": true
        },
        "seed": {
          "type": "integer",
          "description": "Graine de génération (optionnel, générée et renvoyée si absente)."
        }
      },
      "action": true
    },
    {
      "nom": "spatial_monde_forker",
      "description": "Clone un monde existant (mêmes cellules, mêmes biomes/ressources/voisins, mêmes enfants déjà placés) sous un nouvel id indépendant — pour représenter une lignée temporelle qui diverge sans affecter le monde d'origine. Le monde source n'est jamais modifié.",
      "methode": "POST",
      "chemin": "/spatial/mondes/{mid}/forker",
      "params": {
        "mid": {
          "type": "string",
          "description": "Id du monde source à cloner.",
          "requis": true
        }
      },
      "action": true
    },
    {
      "nom": "spatial_mondes_lister",
      "description": "Liste les mondes générés (id, nb_cellules, seed, forked_from_id, date de création). Cloisonné par clé API.",
      "methode": "GET",
      "chemin": "/spatial/mondes",
      "params": {},
      "action": false
    },
    {
      "nom": "spatial_monde_lire",
      "description": "Lit un monde complet : toutes ses cellules (position, biome, ressources, voisins) avec les enfants du génome placés sur chacune.",
      "methode": "GET",
      "chemin": "/spatial/mondes/{mid}",
      "params": {
        "mid": {
          "type": "string",
          "description": "Id du monde à lire.",
          "requis": true
        }
      },
      "action": false
    },
    {
      "nom": "spatial_cellule_lire",
      "description": "Lit une cellule précise d'un monde (position, biome, ressources, voisins, enfants placés dessus).",
      "methode": "GET",
      "chemin": "/spatial/mondes/{mid}/cellules/{cid}",
      "params": {
        "mid": {
          "type": "string",
          "description": "Id du monde.",
          "requis": true
        },
        "cid": {
          "type": "integer",
          "description": "Id de la cellule dans ce monde.",
          "requis": true
        }
      },
      "action": false
    },
    {
      "nom": "spatial_monde_supprimer",
      "description": "Supprime un monde (cascade : ses cellules et les placements d'enfants dessus).",
      "methode": "DELETE",
      "chemin": "/spatial/mondes/{mid}",
      "params": {
        "mid": {
          "type": "string",
          "description": "Id du monde à supprimer.",
          "requis": true
        }
      },
      "action": true
    }
```

(Ne pas oublier la virgule après `genome_enfant_supprimer` pour séparer du bloc ajouté, et vérifier que le JSON reste valide — `python -m json.tool manifest.json` doit réussir.)

- [ ] **Step 2: Mettre à jour `README.md`**

Remplacer le contenu par :

```markdown
# world-engine — Génome Cosmique + Maillage Spatial

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir les specs :
- `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-persistance-lignees-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-maillage-spatial-design.md`

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de la brique `personnages` (port 5900) en HTTP pour
tout calcul astral — pas de duplication du moteur astro.

Génère et persiste aussi des mondes spatiaux (maillage Voronoï, biomes/ressources
par bruit cohérent, forkables pour représenter des lignées temporelles divergentes)
— voir `spatial.py` (génération pure) et `stockage_spatial.py` (persistance). Un
enfant peut être placé sur un monde à sa naissance via `monde_id` sur
`POST /genome/croiser`.

Port : 6220.
```

- [ ] **Step 3: Mettre à jour le commentaire du volume dans `docker-compose.yml`**

Modifier la ligne du volume :
```yaml
    volumes:
      - world_engine_data:/data   # lignées d'enfants (Sprint A) + mondes spatiaux (Sprint B)
```

- [ ] **Step 4: Valider le JSON et lancer le filet complet**

Run:
```bash
python3 -m json.tool briques/world-engine/manifest.json > /dev/null && echo "JSON valide"
scripts/tests_briques.sh world-engine
```
Expected: `JSON valide`, puis `✓ 1 brique(s) au vert : world-engine` et `Aucune régression.` (le test générique `test_manifest_capacites.py` confirme que les 6 nouvelles capacités pointent des routes réelles).

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/manifest.json briques/world-engine/README.md briques/world-engine/docker-compose.yml
git commit -m "docs(world-engine): manifest à jour — 6 nouvelles capacités spatiales + genome_croiser enrichi"
```

---

## Self-Review

**Couverture de la spec** (`2026-08-23-world-engine-maillage-spatial-design.md`) :
- Modèle de données (mondes/cellules/placements, cascade delete) → Task 2. ✓
- Génération Voronoï + bruit cohérent + biomes/ressources → Task 1. ✓
- 6 endpoints `/spatial/*` → Task 3. ✓
- Champ `sexe`, `monde_id`, règle de placement (4 branches), 404 monde invalide → Task 4. ✓
- Fork copie cellules + placements, indépendance de l'original → Task 2 (tests dédiés) + Task 3 (route). ✓
- Repli honnête (404 jamais 403, échec de placement n'empêche jamais un 200) → Task 4. ✓
- Manifest (6 capacités + `genome_croiser` enrichi), dépendances `scipy`/`opensimplex` → Task 1 (deps) + Task 5 (manifest). ✓
- Hors périmètre (habitations, rendu visuel, déplacement post-naissance, horloge) : aucune tâche n'y touche — conforme. ✓

**Cohérence des types entre tâches** : `spatial.generer_monde` renvoie des dicts `{cellule_id, x, y, biome, ressources, voisins}` (Task 1) — `stockage_spatial.creer_monde` consomme exactement ces clés (Task 2). `stockage_spatial.*` renvoie des dicts dont les clés (`id, nb_cellules, seed, forked_from_id, cree_le, cellules, enfants, voisins, cellule_id`) sont utilisées telles quelles par les routes de `main.py` (Task 3/4) sans renommage. `ParentInput`/`ReferenceParent`/`FicheParent.sexe` (Task 4) cohérent entre le Pydantic et `_parent_reference_naissance`.

**Aucun placeholder** : chaque step contient du code complet, aucun TODO/TBD.
