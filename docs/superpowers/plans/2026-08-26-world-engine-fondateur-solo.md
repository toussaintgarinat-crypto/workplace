# World Engine — fondateur solo (pont Studio↔world-engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a capacity to `briques/world-engine` for creating a single "founder" habitant from just a text description (no 2-parent crossing, no real birth data) — the world-engine side of the Studio↔world-engine bridge — plus a way to read one habitant's live simulation state (age/position/alive-or-dead) by id, which the API currently has no route for.

**Architecture:** Extend `genome_moteur.py` with a new Pydantic model `FondationSolo` and function `executer_fondation`, following the exact same internal pattern as the existing `executer_croisement` (call `personnages_client.recherche_inverse` for a plausible sign, `fusion.date_pour_signe` for a birth date, `personnages_client.portrait` for a full real theme, `stockage.creer` to persist, `stockage_spatial.placer` to place on the world). Add one new route `POST /genome/fonder` in `main.py`. Extend the existing `GET /genome/enfants/{eid}` route with a new `simulation` field, backed by a new `stockage_spatial.lire_placement_par_enfant` function.

**Tech Stack:** Python 3, FastAPI, SQLite (stdlib `sqlite3`), pytest + respx (existing test stack, no new dependency).

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-26-pont-studio-world-engine-design.md` — every task below implements a specific part of it; re-read it if a step's rationale is unclear.
- No new pip dependency.
- Every new SQL-backed function follows the file's own established pattern (`_conn()` opens the DB, no DDL migration needed here — `placements` already has all the columns this plan reads).
- `stockage_spatial.py`'s new function does **not** re-check `cle_api` — same convention as every other read helper in that file that takes only an id (`placement_cellule`, `voisins_cellule`, etc.); the HTTP boundary (`main.py`) is what enforces `cle_api`, via `stockage.lire(cle_api, eid)` which is always called first.
- `POST /genome/fonder` follows the exact same error contract as `POST /genome/croiser`: `monde_id` introuvable ou d'une autre clé API → `404`; `personnages` injoignable ou refuse (non-422) → `502`; fiche invalide (422 de `personnages`) → `422` propagé tel quel.
- A fondateur MUST end up with a full, non-degraded `theme_complet` (not just a bare signe) — it must be safely usable later as a `ReferenceParent` in a normal `/genome/croiser` call without crashing `fusion.comparer_dix_corps` (which requires `dix_corps` on both parents). This is why `FondationSolo` requires real birth-data fields (`latitude`, `longitude`, `heure_naissance`, `utc_offset`) exactly like `Croisement`'s `*_enfant` fields, and why `executer_fondation` calls `personnages_client.portrait` (not just `recherche_inverse`) and validates with `_exiger_theme_complet`.
- Run every test command from `briques/world-engine/` (`cd briques/world-engine && pytest ...`).

---

## Task 1: `stockage_spatial.lire_placement_par_enfant`

**Files:**
- Modify: `briques/world-engine/stockage_spatial.py`
- Test: `briques/world-engine/test_stockage_spatial.py`

**Interfaces:**
- Consumes: nothing new (reads the existing `placements` table).
- Produces (used by Task 3): `lire_placement_par_enfant(enfant_id: str) -> dict | None` → `{monde_id, cellule_id, ne_au_tick, vivant, mort_au_tick}` or `None` if this enfant has no placement in any monde.

- [ ] **Step 1: Write the failing tests**

Add to `briques/world-engine/test_stockage_spatial.py` (append at the end of the file):

```python
def test_lire_placement_par_enfant_absent():
    assert stockage_spatial.lire_placement_par_enfant("id-inconnu") is None


def test_lire_placement_par_enfant_vivant():
    monde = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=10)
    eid = stockage.creer("cle-a", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    stockage_spatial.placer(monde["id"], eid, 1, ne_au_tick=5)
    p = stockage_spatial.lire_placement_par_enfant(eid)
    assert p == {"monde_id": monde["id"], "cellule_id": 1, "ne_au_tick": 5,
                 "vivant": 1, "mort_au_tick": None}


def test_lire_placement_par_enfant_mort():
    monde = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=11)
    eid = stockage.creer("cle-a", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=0)
    stockage_spatial.marquer_mort(monde["id"], eid, 7)
    p = stockage_spatial.lire_placement_par_enfant(eid)
    assert p["vivant"] == 0
    assert p["mort_au_tick"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -k lire_placement_par_enfant -v`
Expected: FAIL with `AttributeError: module 'stockage_spatial' has no attribute 'lire_placement_par_enfant'`

- [ ] **Step 3: Implement `lire_placement_par_enfant`**

Add to `briques/world-engine/stockage_spatial.py`, right after `placement_cellule` (after line 239, before `def placer`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -k lire_placement_par_enfant -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/stockage_spatial.py briques/world-engine/test_stockage_spatial.py
git commit -m "feat(world-engine): stockage_spatial.lire_placement_par_enfant"
```

---

## Task 2: `POST /genome/fonder` — fondateur solo

**Files:**
- Modify: `briques/world-engine/genome_moteur.py`
- Modify: `briques/world-engine/main.py`
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `personnages_client.recherche_inverse`, `personnages_client.portrait`, `personnages_client.PersonnagesIndisponible`, `fusion.date_pour_signe`, `stockage.creer`, `stockage_spatial.monde_existe`, `stockage_spatial.nb_cellules_monde`, `stockage_spatial.placer`, `stockage_horloge.lire_horloge` — all already used by `executer_croisement`, same signatures.
- Produces: `genome_moteur.FondationSolo` (Pydantic model), `genome_moteur.executer_fondation(body: FondationSolo, cle_api_val: str) -> dict` → `{"eid": str, "cellule_id": int, "theme": dict}`. Route `POST /genome/fonder` in `main.py`.

- [ ] **Step 1: Write the failing tests**

Add to `briques/world-engine/test_api.py` (append at the end of the file, after the last existing test):

```python
# ── Fondateur solo (pont Studio↔world-engine, sans croisement à 2 parents) ──
@respx.mock
def test_genome_fonder_chemin_heureux():
    monde = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 100}).json()
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Lion", "score": 5}]}))
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice("Soleil", "Lion", "Lion")))
    r = client.post("/genome/fonder", json={
        "monde_id": monde["id"], "description": "Une aventurière rusée et loyale.",
        "prenoms": "Elara", "nom": "", "latitude": 48.85, "longitude": 2.35,
        "heure_naissance": "12:00", "utc_offset": 1.0, "sexe": "F"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["eid"], str) and data["eid"]
    assert 0 <= data["cellule_id"] < 10
    assert data["theme"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Lion"
    stocke = stockage.lire("public", data["eid"])
    assert stocke["prenoms"] == "Elara"
    assert stocke["sexe"] == "F"
    assert stockage_spatial.placement_cellule(monde["id"], data["eid"]) == data["cellule_id"]


def test_genome_fonder_monde_introuvable_404():
    r = client.post("/genome/fonder", json={
        "monde_id": "id-inconnu", "description": "x", "latitude": 48.85, "longitude": 2.35,
        "heure_naissance": "12:00", "utc_offset": 1.0})
    assert r.status_code == 404


@respx.mock
def test_genome_fonder_personnages_injoignable_502():
    monde = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 101}).json()
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        side_effect=httpx.ConnectError("down"))
    r = client.post("/genome/fonder", json={
        "monde_id": monde["id"], "description": "x", "latitude": 48.85, "longitude": 2.35,
        "heure_naissance": "12:00", "utc_offset": 1.0})
    assert r.status_code == 502


@respx.mock
def test_genome_fonder_aucun_signe_derive_422():
    monde = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 102}).json()
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": []}))
    r = client.post("/genome/fonder", json={
        "monde_id": monde["id"], "description": "x", "latitude": 48.85, "longitude": 2.35,
        "heure_naissance": "12:00", "utc_offset": 1.0})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_api.py -k genome_fonder -v`
Expected: FAIL — `404 Not Found` on all of them (`/genome/fonder` doesn't exist yet).

- [ ] **Step 3: Implement `FondationSolo` and `executer_fondation` in `genome_moteur.py`**

Add to `briques/world-engine/genome_moteur.py`, right after the `Croisement` class (after line 72, before `def _detail`):

```python
class FondationSolo(BaseModel):
    """Crée un habitant fondateur SANS croisement à 2 parents (pont Studio↔world-engine,
    voir docs/superpowers/specs/2026-08-26-pont-studio-world-engine-design.md) : un
    personnage de fiction n'a pas de vrais parents à inventer, seulement une description.
    `latitude`/`longitude`/`heure_naissance`/`utc_offset` restent requis pour la même
    raison que les champs `*_enfant` de `Croisement` : sans eux, `personnages` renvoie un
    thème dégradé, ce qui casserait `fusion.comparer_dix_corps` si ce fondateur sert un
    jour de parent (via `ReferenceParent`) dans un croisement normal. Pas de
    `model_config = ConfigDict(extra="forbid")` — même convention que `Croisement` dans
    ce fichier (le `forbid` n'est appliqué qu'aux fiches parent imbriquées, pas au corps
    de route top-level)."""

    monde_id: str
    description: str
    prenoms: str = ""
    nom: str = ""
    latitude: float
    longitude: float
    heure_naissance: str
    utc_offset: float
    annee: Optional[int] = Field(default=None, ge=1, le=9999)
    sexe: Optional[Literal["F", "M"]] = None


async def executer_fondation(body: FondationSolo, cle_api_val: str) -> dict:
    """Dérive un signe plausible de `body.description` (via `personnages`, même
    mécanisme que la mutation d'`executer_croisement`), obtient un thème complet réel
    pour une date de naissance dérivée de ce signe, persiste et place directement
    l'enfant fondateur sur `body.monde_id` — sans les 2 parents d'un croisement normal."""
    if not stockage_spatial.monde_existe(cle_api_val, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")

    try:
        rri = await personnages_client.recherche_inverse(body.description)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if rri.status_code != 200:
        _propager_ou_502(rri, "Recherche inverse")
    signes = rri.json().get("signes") or []
    if not signes:
        raise HTTPException(422, "Impossible de dériver un signe pour ce fondateur "
                                  "à partir de cette description.")

    annee = body.annee or date.today().year
    date_naissance = fusion.date_pour_signe(signes[0]["signe"], annee)
    fiche = {"prenoms": body.prenoms, "nom": body.nom, "date_naissance": date_naissance,
             "heure_naissance": body.heure_naissance, "latitude": body.latitude,
             "longitude": body.longitude, "utc_offset": body.utc_offset}
    try:
        rp = await personnages_client.portrait(fiche)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if rp.status_code != 200:
        _propager_ou_502(rp, "Fondateur")
    theme = rp.json()
    _exiger_theme_complet(theme, "Fondateur")

    eid = stockage.creer(cle_api_val, body.prenoms, body.nom, None, None, theme,
                          description_genome=body.description, heredite={},
                          mutation_survenue=False, sexe=body.sexe)

    nb = stockage_spatial.nb_cellules_monde(body.monde_id)
    if nb is None:
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    cellule_id = Random().randrange(nb)
    horloge_etat = stockage_horloge.lire_horloge(body.monde_id)
    ne_au_tick = horloge_etat["tick_actuel"] if horloge_etat else 0
    stockage_spatial.placer(body.monde_id, eid, cellule_id, ne_au_tick=ne_au_tick)

    return {"eid": eid, "cellule_id": cellule_id, "theme": theme}
```

- [ ] **Step 4: Add the route in `main.py`**

Add to `briques/world-engine/main.py`, right after `genome_croiser` (after line 102, before `@app.get("/genome/enfants"`):

```python
@app.post("/genome/fonder", tags=["genome"])
async def genome_fonder(body: genome_moteur.FondationSolo, _cle: str = Depends(cle_api)):
    """Crée un habitant fondateur sans croisement à 2 parents (pont Studio↔world-engine)
    — voir `genome_moteur.executer_fondation` pour le détail."""
    return await genome_moteur.executer_fondation(body, _cle)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_api.py -k genome_fonder -v`
Expected: PASS (4 tests)

Then run the full suite to check nothing broke: `cd briques/world-engine && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/genome_moteur.py briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): POST /genome/fonder — fondateur solo sans croisement"
```

---

## Task 3: `GET /genome/enfants/{eid}` — champ `simulation`

**Files:**
- Modify: `briques/world-engine/main.py`
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `stockage_spatial.lire_placement_par_enfant` (Task 1), `stockage_horloge.lire_horloge`.
- Produces: `main.py::_simulation_enfant(eid: str) -> dict | None`, and `GET /genome/enfants/{eid}` responses gain a `simulation` key.

- [ ] **Step 1: Write the failing tests**

Add to `briques/world-engine/test_api.py` (append at the end of the file):

```python
def test_genome_enfant_lire_simulation_null_sans_placement():
    eid = stockage.creer("public", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    r = client.get(f"/genome/enfants/{eid}")
    assert r.status_code == 200
    assert r.json()["simulation"] is None


def test_genome_enfant_lire_simulation_vivante():
    monde = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 200}).json()
    eid = stockage.creer("public", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=0)
    r = client.get(f"/genome/enfants/{eid}")
    sim = r.json()["simulation"]
    assert sim["monde_id"] == monde["id"]
    assert sim["cellule_id"] == 0
    assert sim["vivant"] is True
    assert sim["mort_au_tick"] is None
    assert sim["age_actuel_ticks"] == 0


def test_genome_enfant_lire_simulation_morte():
    monde = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 201}).json()
    eid = stockage.creer("public", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=0)
    stockage_spatial.marquer_mort(monde["id"], eid, 6)
    r = client.get(f"/genome/enfants/{eid}")
    sim = r.json()["simulation"]
    assert sim["vivant"] is False
    assert sim["mort_au_tick"] == 6
    assert sim["age_actuel_ticks"] == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/world-engine && python -m pytest test_api.py -k simulation -v`
Expected: FAIL with `KeyError: 'simulation'`

- [ ] **Step 3: Implement `_simulation_enfant` and wire it into `genome_enfant_lire`**

In `briques/world-engine/main.py`, add this function right before `@app.get("/genome/enfants/{eid}"` (before line 110):

```python
def _simulation_enfant(eid: str) -> Optional[dict]:
    """État simulé courant d'un enfant placé (pont Studio↔world-engine) : âge en ticks
    écoulés depuis sa naissance, position, vivant ou mort. `None` si jamais placé sur
    aucun monde. Age calculé jusqu'au tick actuel du monde s'il est vivant, jusqu'à son
    `mort_au_tick` sinon (un mort n'a pas continué à vieillir après sa mort)."""
    p = stockage_spatial.lire_placement_par_enfant(eid)
    if p is None:
        return None
    horloge_etat = stockage_horloge.lire_horloge(p["monde_id"])
    tick_actuel = horloge_etat["tick_actuel"] if horloge_etat else p["ne_au_tick"]
    tick_reference = tick_actuel if p["vivant"] else p["mort_au_tick"]
    return {"monde_id": p["monde_id"], "cellule_id": p["cellule_id"],
            "ne_au_tick": p["ne_au_tick"], "age_actuel_ticks": tick_reference - p["ne_au_tick"],
            "vivant": bool(p["vivant"]), "mort_au_tick": p["mort_au_tick"]}
```

Then modify `genome_enfant_lire` (line 110-115) from:

```python
@app.get("/genome/enfants/{eid}", tags=["genome"])
def genome_enfant_lire(eid: str, _cle: str = Depends(cle_api)):
    enfant = stockage.lire(_cle, eid)
    if enfant is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return enfant
```

to:

```python
@app.get("/genome/enfants/{eid}", tags=["genome"])
def genome_enfant_lire(eid: str, _cle: str = Depends(cle_api)):
    enfant = stockage.lire(_cle, eid)
    if enfant is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    enfant["simulation"] = _simulation_enfant(eid)
    return enfant
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/world-engine && python -m pytest test_api.py -k simulation -v`
Expected: PASS (3 tests)

Then run the full suite: `cd briques/world-engine && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): champ simulation sur GET /genome/enfants/{eid}"
```

---

## Task 4: `manifest.json`

**Files:**
- Modify: `briques/world-engine/manifest.json`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by later tasks — but `test_manifest_capacites.py::test_chaque_capacite_pointe_une_route_reelle` requires every listed capacité to point to a real route, and this task adds the entry for the route added in Task 2.

- [ ] **Step 1: Write the failing test expectation**

No new test file — `briques/world-engine/test_manifest_capacites.py` already exists and already runs against `manifest.json` + `main.app.routes`. Since Task 2 already added a real route without a manifest entry, that test currently still passes (it only checks capacités → routes, not the reverse), so there is nothing to make fail here. Skip straight to Step 2 (this task is documentation completeness, verified by re-running the existing test after editing).

- [ ] **Step 2: Add the `genome_fonder` capacité and update `genome_enfant_lire`'s description**

In `briques/world-engine/manifest.json`, replace the `genome_enfant_lire` entry (lines 88-101):

```json
    {
      "nom": "genome_enfant_lire",
      "description": "Lit la fiche complète d'un enfant stocké : thème astral, récit d'hérédité, description fusionnée, ids des parents, et son état de simulation courant (`simulation`, null si jamais placé sur un monde : monde_id, cellule_id, age_actuel_ticks, vivant, mort_au_tick).",
      "methode": "GET",
      "chemin": "/genome/enfants/{eid}",
      "params": {
        "eid": {
          "type": "string",
          "description": "Id de l'enfant stocké à lire.",
          "requis": true
        }
      },
      "action": false
    },
```

Then, right after the `genome_enfant_supprimer` entry (after line 129, before the `spatial_monde_creer` entry), insert:

```json
    {
      "nom": "genome_fonder",
      "description": "Crée un habitant fondateur SANS croisement à 2 parents (pont Studio↔world-engine) : dérive un signe plausible d'une simple description textuelle, obtient un thème complet réel pour une date de naissance dérivée de ce signe, place l'enfant sur une cellule aléatoire du monde donné. latitude/longitude/heure_naissance/utc_offset restent requis (jamais devinés) pour que le thème obtenu soit complet — sans eux, `personnages` renverrait un thème dégradé qui casserait un usage futur de ce fondateur comme parent d'un croisement normal.",
      "methode": "POST",
      "chemin": "/genome/fonder",
      "params": {
        "monde_id": {
          "type": "string",
          "description": "Id d'un monde spatial existant où placer le fondateur. Introuvable ou d'une autre clé API → 404.",
          "requis": true
        },
        "description": {
          "type": "string",
          "description": "Description libre du personnage (traits, personnalité) — utilisée pour dériver un signe plausible via la brique personnages.",
          "requis": true
        },
        "prenoms": {
          "type": "string",
          "description": "Prénom(s) du fondateur."
        },
        "nom": {
          "type": "string",
          "description": "Nom de famille du fondateur."
        },
        "latitude": {
          "type": "number",
          "description": "Latitude de naissance du fondateur. Obligatoire : jamais deviné.",
          "requis": true
        },
        "longitude": {
          "type": "number",
          "description": "Longitude EST-positive de naissance du fondateur. Obligatoire.",
          "requis": true
        },
        "heure_naissance": {
          "type": "string",
          "description": "Heure de naissance 'HH:MM' du fondateur. Obligatoire : sans elle, thème dégradé.",
          "requis": true
        },
        "utc_offset": {
          "type": "number",
          "description": "Décalage local→UTC au lieu de naissance du fondateur. Obligatoire.",
          "requis": true
        },
        "annee": {
          "type": "integer",
          "description": "Année de naissance du fondateur (optionnel, défaut : année courante, bornée 1-9999)."
        },
        "sexe": {
          "type": "string",
          "description": "Sexe du fondateur ('F'/'M', optionnel) — nécessaire à l'horloge pour l'apparier en couple par la suite."
        }
      },
      "action": true
    },
```

- [ ] **Step 3: Verify the manifest test still passes**

Run: `cd briques/world-engine && python -m pytest test_manifest_capacites.py -v`
Expected: PASS (2 tests — `test_chaque_capacite_pointe_une_route_reelle` now also validates the new `genome_fonder` entry against the real `/genome/fonder` route added in Task 2).

Then run the full suite one last time: `cd briques/world-engine && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add briques/world-engine/manifest.json
git commit -m "docs(world-engine): manifest — genome_fonder + champ simulation"
```
