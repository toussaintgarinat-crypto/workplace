# Studio — pont vers world-engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a recurring Studio character become a persistent "habitant" of a world-engine world dedicated to its série, on explicit user validation, and let that history (age, position, death) come back as a proposed fact before a later chapter is written — never automatically.

**Architecture:** A new counter (`canon.apparitions`) makes recurrence measurable. A new file-based store (`stockage_pont.py`, one JSON file per série, matching Studio's existing per-concept JSON persistence — there is no SQLite in this brique) holds the série↔monde and personnage↔habitant links, kept separate from both `serie.personnages` and the world-engine enfant record. A handful of new `_pont_*`/`_appeler_world_engine` functions in `studio.py` call world-engine over HTTP, following the exact same pattern already used for the `images`/`video` sibling briques (`_appeler_images`/`_appeler_video`): best-effort, `None` on any failure, caller decides whether to surface a 502 or stay silent. Three new routes in `main.py` expose entry (`/pont/fonder`), and return-suggestions (`/pont/suggestions`, `/pont/accepter`); the 2 existing chapter-generation routes get a small addition each (tick + eligibility list).

**Tech Stack:** Python 3, FastAPI, JSON files (stdlib `json`/`os`), pytest (existing test stack, no new dependency — this brique doesn't use `respx`; sibling-brique HTTP calls are tested by monkeypatching `httpx.AsyncClient` directly, see `test_images.py`).

**Depends on:** `docs/superpowers/plans/2026-08-26-world-engine-fondateur-solo.md` must be implemented first — this plan's Task 4 and Task 6 call `POST /genome/fonder` and read the `simulation` field of `GET /genome/enfants/{eid}`, both added there.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-26-pont-studio-world-engine-design.md` — every task below implements a specific part of it; re-read it if a step's rationale is unclear.
- No new pip dependency.
- `briques/studio` has **no SQLite** anywhere — all persistence is JSON files, one per concept (`studio.py:74-164`: `_path`/`_load`/`_save` for séries, `_profil_path` for profiles, `_compte_path` for comptes). `stockage_pont.py` follows this exact idiom: one JSON file per série under `ATELIERS_DIR/pont/`.
- Calls to world-engine follow Studio's existing sibling-brique idiom (`_appeler_images`/`_appeler_video`, `studio.py:791-825`): a bare `try/except Exception: return None`, never propagated as an exception to the route. The route decides: an explicit user action (fonder un personnage) surfaces a `502` on `None` (same as `couverture_episode`/`teaser_episode`, `main.py:1121`); a background/best-effort action (tick after a chapter, suggestions before one) stays silent on `None`.
- `_cle_perso` (already defined, `studio.py:540-542`) is the ONE normalization used everywhere a personnage name is compared or used as a dict key — in `canon.apparitions`, in `stockage_pont.py`'s `habitants` keys, in the new éligibilité helper. Never re-implement name normalization.
- Every new route is added to `manifest.json` (Task 7) — `test_manifest_capacites.py` only checks capacités → routes, not the reverse, but the manifest is what the Cœur reads to pilot this brique; an unlisted route is invisible to it.
- Run every test command from `briques/studio/` (`cd briques/studio && pytest ...`).

---

## Task 1: `canon.apparitions` — compteur d'apparitions par personnage

**Files:**
- Modify: `briques/studio/studio.py`
- Test: `briques/studio/test_continuite.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 2): `serie["canon"]["apparitions"]` — `dict[str, int]`, keyed by `_cle_perso(nom)`, incremented once per chapter a name is mentioned in (never more than once per chapter, even if the LLM extraction lists a name twice for the same chapter).

- [ ] **Step 1: Write the failing tests**

`test_normaliser_cree_le_canon_vide` (line 15-17 of `test_continuite.py`) currently asserts the OLD canon shape and will need updating — this is expected, not a regression:

```python
def test_normaliser_cree_le_canon_vide():
    s = A._normaliser({"titre": "T", "episodes": []})
    assert s["canon"] == {"personnages": [], "acquis": [], "apparitions": {}}
```

Add new tests right after `test_fusion_canon_plafonne_les_acquis` (after line 80) in `test_continuite.py`:

```python
def test_fusion_canon_compte_les_apparitions():
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["Elara"], [])
    A._fusion_canon(serie, ["elara", "Kaël"], [])
    A._fusion_canon(serie, ["ELARA"], [])
    assert serie["canon"]["apparitions"] == {"ELARA": 3, "KAËL": 1}


def test_fusion_canon_compte_une_seule_fois_par_chapitre():
    """Une même personne mentionnée plusieurs fois DANS UN MÊME chapitre ne doit
    compter que pour UNE apparition — sinon le seuil de récurrence du pont
    world-engine (3 CHAPITRES distincts) serait faussé par le style d'écriture."""
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["Elara", "Elara", "elara"], [])
    assert serie["canon"]["apparitions"] == {"ELARA": 1}


def test_fusion_canon_apparitions_ignore_narrateur():
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["NARRATEUR"], [])
    assert serie["canon"]["apparitions"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/studio && python -m pytest test_continuite.py -k "canon_vide or compte_les_apparitions or compte_une_seule_fois or apparitions_ignore" -v`
Expected: FAIL — `test_normaliser_cree_le_canon_vide` fails on the dict comparison (missing `"apparitions"` key), the 3 new tests fail with `KeyError: 'apparitions'`.

- [ ] **Step 3: Implement**

In `briques/studio/studio.py`, modify `_normaliser` (lines 241-243):

```python
    canon = serie.setdefault("canon", {})
    canon.setdefault("personnages", [])
    canon.setdefault("acquis", [])
```

to:

```python
    canon = serie.setdefault("canon", {})
    canon.setdefault("personnages", [])
    canon.setdefault("acquis", [])
    canon.setdefault("apparitions", {})
```

Then modify `_fusion_canon` (lines 600-619) from:

```python
def _fusion_canon(serie: dict, personnages, acquis) -> None:
    """Fusionne (idempotent, dédoublonné, plafonné) des noms/faits dans le canon."""
    canon = serie.setdefault("canon", {})
    cps = canon.setdefault("personnages", [])
    vus = {_cle_perso(n) for n in cps}
    for nom in personnages or []:
        cle = _cle_perso(nom)
        if cle and cle != "NARRATEUR" and cle not in vus:
            vus.add(cle)
            cps.append(re.sub(r"\s+", " ", str(nom).strip()))
    canon["personnages"] = cps[:CANON_MAX_PERSOS]

    cac = canon.setdefault("acquis", [])
```

to:

```python
def _fusion_canon(serie: dict, personnages, acquis) -> None:
    """Fusionne (idempotent, dédoublonné, plafonné) des noms/faits dans le canon.

    `canon.apparitions` (pont Studio↔world-engine) compte le nombre de CHAPITRES
    DISTINCTS où chaque nom a été vu — jamais plus d'une fois par appel, même si le
    script en mentionne le nom plusieurs fois : c'est ce qui rend le seuil de
    récurrence (`SEUIL_RECURRENCE_PONT`) vérifiable objectivement."""
    canon = serie.setdefault("canon", {})
    cps = canon.setdefault("personnages", [])
    apparitions = canon.setdefault("apparitions", {})
    vus = {_cle_perso(n) for n in cps}
    cles_du_chapitre = set()
    for nom in personnages or []:
        cle = _cle_perso(nom)
        if not cle or cle == "NARRATEUR":
            continue
        cles_du_chapitre.add(cle)
        if cle not in vus:
            vus.add(cle)
            cps.append(re.sub(r"\s+", " ", str(nom).strip()))
    for cle in cles_du_chapitre:
        apparitions[cle] = apparitions.get(cle, 0) + 1
    canon["personnages"] = cps[:CANON_MAX_PERSOS]
    canon["apparitions"] = apparitions

    cac = canon.setdefault("acquis", [])
```

(the rest of `_fusion_canon`, handling `acquis`, is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/studio && python -m pytest test_continuite.py -v`
Expected: all PASS (existing tests + the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_continuite.py
git commit -m "feat(studio): canon.apparitions — compteur de récurrence par personnage"
```

---

## Task 2: `_personnages_eligibles_pont` — helper d'éligibilité (fonction pure)

**Files:**
- Modify: `briques/studio/studio.py`
- Test: `briques/studio/test_continuite.py`

**Interfaces:**
- Consumes: `serie["personnages"]`, `serie["canon"]["apparitions"]`, `serie["canon"]["personnages"]` (all from Task 1 / already existing), `_cle_perso`.
- Produces (used by Task 5): `SEUIL_RECURRENCE_PONT: int = 3`, `_personnages_eligibles_pont(serie: dict, pont: dict) -> list[str]` → display names not yet linked in `pont["habitants"]`, either formally casted or past the recurrence threshold.

- [ ] **Step 1: Write the failing tests**

Add to `briques/studio/test_continuite.py` (append at the end of the file):

```python
# ── Éligibilité pont world-engine ─────────────────────────────────
def test_eligibles_pont_personnage_caste_immediat():
    serie = {"personnages": [{"nom": "Elara"}], "canon": {"apparitions": {}, "personnages": []}}
    pont = {"habitants": {}}
    assert A._personnages_eligibles_pont(serie, pont) == ["Elara"]


def test_eligibles_pont_seuil_apparitions():
    serie = {"personnages": [],
             "canon": {"apparitions": {"KAEL": 2}, "personnages": ["Kael"]}}
    pont = {"habitants": {}}
    assert A._personnages_eligibles_pont(serie, pont) == []
    serie["canon"]["apparitions"]["KAEL"] = A.SEUIL_RECURRENCE_PONT
    assert A._personnages_eligibles_pont(serie, pont) == ["Kael"]


def test_eligibles_pont_exclut_deja_lies():
    serie = {"personnages": [{"nom": "Elara"}], "canon": {"apparitions": {}, "personnages": []}}
    pont = {"habitants": {"ELARA": {"eid": "x"}}}
    assert A._personnages_eligibles_pont(serie, pont) == []


def test_eligibles_pont_pas_de_doublon_caste_et_apparitions():
    serie = {"personnages": [{"nom": "Elara"}],
             "canon": {"apparitions": {"ELARA": A.SEUIL_RECURRENCE_PONT}, "personnages": ["Elara"]}}
    pont = {"habitants": {}}
    assert A._personnages_eligibles_pont(serie, pont) == ["Elara"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/studio && python -m pytest test_continuite.py -k eligibles_pont -v`
Expected: FAIL with `AttributeError: module 'studio' has no attribute '_personnages_eligibles_pont'`

- [ ] **Step 3: Implement**

In `briques/studio/studio.py`, add right after `CANON_MAX_ACQUIS = 30` (line 564):

```python
SEUIL_RECURRENCE_PONT = 3   # apparitions distinctes minimum pour un perso non casté (pont)
```

Add right after `_fusion_canon` (after its closing, before `async def _recolter_canon`, i.e. after line 619 as amended by Task 1):

```python
def _personnages_eligibles_pont(serie: dict, pont: dict) -> list:
    """Noms (affichage) éligibles à une proposition d'entrée dans world-engine, pas
    encore liés (pont Studio↔world-engine) : castés formellement (`serie.personnages`),
    OU vus dans `SEUIL_RECURRENCE_PONT` chapitres distincts (`canon.apparitions`) sans
    casting. Jamais les deux fois pour un même personnage."""
    deja_lies = set((pont or {}).get("habitants") or {})
    vus, eligibles = set(), []
    for p in serie.get("personnages") or []:
        nom = (p.get("nom") or "").strip()
        cle = _cle_perso(nom)
        if cle and cle not in deja_lies and cle not in vus:
            vus.add(cle)
            eligibles.append(nom)
    apparitions = (serie.get("canon") or {}).get("apparitions") or {}
    cps = (serie.get("canon") or {}).get("personnages") or []
    nom_par_cle = {_cle_perso(n): n for n in cps}
    for cle, n in apparitions.items():
        if n >= SEUIL_RECURRENCE_PONT and cle not in deja_lies and cle not in vus:
            vus.add(cle)
            eligibles.append(nom_par_cle.get(cle, cle))
    return eligibles
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/studio && python -m pytest test_continuite.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_continuite.py
git commit -m "feat(studio): _personnages_eligibles_pont — éligibilité au pont world-engine"
```

---

## Task 3: `stockage_pont.py` — persistance du lien personnage↔habitant

**Files:**
- Create: `briques/studio/stockage_pont.py`
- Create: `briques/studio/test_stockage_pont.py`

**Interfaces:**
- Consumes: nothing (reads `STUDIO_DIR` env var directly — deliberately NOT imported from `studio.py`, to avoid a circular import since `studio.py` will import this module in Task 4).
- Produces (used by Tasks 4-6): `lire_pont(serie_id: str) -> dict` → `{"serie_id", "monde_id": str | None, "habitants": {nom_cle: {"eid", "nom_affiche", "lie_le"}}}` (never raises — a série with no pont file yet gets a fresh empty shape); `fixer_monde(serie_id: str, monde_id: str) -> dict`; `lier_habitant(serie_id: str, nom_cle: str, eid: str, nom_affiche: str, lie_le: str) -> dict`; `detacher_habitant(serie_id: str, nom_cle: str) -> dict`.

- [ ] **Step 1: Write the failing tests**

Create `briques/studio/test_stockage_pont.py`:

```python
"""Tests — stockage_pont.py : le lien personnage Studio ↔ habitant world-engine, un
fichier JSON par série (même idiome que _profil_path/_journal_path de studio.py), séparé
de la fiche série ET de la fiche world-engine (voir design du pont)."""
import stockage_pont as P


def test_lire_pont_absent_renvoie_forme_vide():
    assert P.lire_pont("serie-inconnue") == {
        "serie_id": "serie-inconnue", "monde_id": None, "habitants": {}}


def test_fixer_monde_puis_lire():
    P.fixer_monde("s1", "monde-abc")
    assert P.lire_pont("s1")["monde_id"] == "monde-abc"


def test_lier_habitant_puis_lire():
    P.lier_habitant("s2", "ELARA", "eid-1", "Elara", "2026-08-26T00:00:00+00:00")
    pont = P.lire_pont("s2")
    assert pont["habitants"] == {
        "ELARA": {"eid": "eid-1", "nom_affiche": "Elara", "lie_le": "2026-08-26T00:00:00+00:00"}}


def test_detacher_habitant():
    P.lier_habitant("s3", "KAEL", "eid-2", "Kaël", "2026-08-26T00:00:00+00:00")
    P.detacher_habitant("s3", "KAEL")
    assert P.lire_pont("s3")["habitants"] == {}


def test_detacher_habitant_absent_noop():
    P.detacher_habitant("s4", "INCONNU")   # ne lève pas
    assert P.lire_pont("s4")["habitants"] == {}


def test_isolation_par_serie():
    P.lier_habitant("s5", "A", "eid-a", "A", "t")
    P.lier_habitant("s6", "B", "eid-b", "B", "t")
    assert "B" not in P.lire_pont("s5")["habitants"]
    assert "A" not in P.lire_pont("s6")["habitants"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/studio && python -m pytest test_stockage_pont.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockage_pont'`

- [ ] **Step 3: Implement `stockage_pont.py`**

Create `briques/studio/stockage_pont.py`:

```python
"""Persistance du lien personnage Studio ↔ habitant world-engine (pont, voir
docs/superpowers/specs/2026-08-26-pont-studio-world-engine-design.md) : un fichier JSON
par série, séparé de la fiche série (`serie.personnages`) ET de la fiche world-engine —
décision utilisateur explicite (isole la responsabilité du lien des deux modèles de
données existants). Même idiome que `_profil_path`/`_journal_path` de `studio.py`
(fichier JSON par concept), volontairement PAS importé de `studio.py` (lirait
`STUDIO_DIR` deux fois plutôt qu'un import circulaire — `studio.py` importera ce module
en Task 4)."""
import json
import os

ATELIERS_DIR = os.getenv("STUDIO_DIR", "/data/ateliers")
PONT_DIR = os.path.join(ATELIERS_DIR, "pont")
os.makedirs(PONT_DIR, exist_ok=True)


def _pont_path(serie_id: str) -> str:
    return os.path.join(PONT_DIR, f"{serie_id}.json")


def lire_pont(serie_id: str) -> dict:
    p = _pont_path(serie_id)
    if not os.path.exists(p):
        return {"serie_id": serie_id, "monde_id": None, "habitants": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _sauver(pont: dict) -> None:
    with open(_pont_path(pont["serie_id"]), "w", encoding="utf-8") as f:
        json.dump(pont, f, ensure_ascii=False, indent=2)


def fixer_monde(serie_id: str, monde_id: str) -> dict:
    pont = lire_pont(serie_id)
    pont["monde_id"] = monde_id
    _sauver(pont)
    return pont


def lier_habitant(serie_id: str, nom_cle: str, eid: str, nom_affiche: str, lie_le: str) -> dict:
    pont = lire_pont(serie_id)
    pont["habitants"][nom_cle] = {"eid": eid, "nom_affiche": nom_affiche, "lie_le": lie_le}
    _sauver(pont)
    return pont


def detacher_habitant(serie_id: str, nom_cle: str) -> dict:
    pont = lire_pont(serie_id)
    pont["habitants"].pop(nom_cle, None)
    _sauver(pont)
    return pont
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/studio && python -m pytest test_stockage_pont.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/stockage_pont.py briques/studio/test_stockage_pont.py
git commit -m "feat(studio): stockage_pont.py — lien personnage/habitant, un JSON par série"
```

---

## Task 4: `_appeler_world_engine` + wrappers dans `studio.py`

**Files:**
- Modify: `briques/studio/studio.py`
- Test: `briques/studio/test_world_engine.py`

**Interfaces:**
- Consumes: `httpx` (already imported in `studio.py`).
- Produces (used by Tasks 5-6): `WORLD_ENGINE_URL` (module constant), `_appeler_world_engine(methode: str, route: str, payload: dict | None = None) -> dict | None`, `_pont_creer_monde() -> dict | None`, `_pont_fonder(monde_id: str, description: str, prenoms: str) -> dict | None`, `_pont_tick(monde_id: str) -> None`, `_pont_lire_enfant(eid: str) -> dict | None`.

- [ ] **Step 1: Write the failing tests**

Create `briques/studio/test_world_engine.py`:

```python
"""Tests — pont vers world-engine : _appeler_world_engine + wrappers. Même motif que
test_images.py (monkeypatch de httpx.AsyncClient, pas respx — absent des dépendances de
cette brique)."""
import asyncio

import studio as A


class _FauxRep:
    def __init__(self, data): self._data = data
    def raise_for_status(self): pass
    def json(self): return self._data


class _FauxClient:
    def __init__(self, reponse=None, leve=None):
        self._reponse, self._leve = reponse, leve
    def __call__(self, *a, **k): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def request(self, methode, url, json=None):
        if self._leve:
            raise self._leve
        return _FauxRep(self._reponse)


def test_appeler_world_engine_succes(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(reponse={"id": "m1"}))
    res = asyncio.run(A._appeler_world_engine("POST", "/spatial/mondes", {"nb_cellules": 10}))
    assert res == {"id": "m1"}


def test_appeler_world_engine_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    assert asyncio.run(A._appeler_world_engine("GET", "/sante")) is None


def test_pont_creer_monde_appelle_spatial_mondes(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(reponse={"id": "m2", "nb_cellules": 10}))
    assert asyncio.run(A._pont_creer_monde()) == {"id": "m2", "nb_cellules": 10}


def test_pont_fonder_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    assert asyncio.run(A._pont_fonder("m1", "une description", "Elara")) is None


def test_pont_tick_ne_leve_jamais(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    asyncio.run(A._pont_tick("m1"))   # ne lève pas, pas de valeur de retour à vérifier


def test_pont_lire_enfant_succes(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(reponse={"id": "e1", "simulation": None}))
    assert asyncio.run(A._pont_lire_enfant("e1")) == {"id": "e1", "simulation": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/studio && python -m pytest test_world_engine.py -v`
Expected: FAIL with `AttributeError: module 'studio' has no attribute '_appeler_world_engine'`

- [ ] **Step 3: Implement**

In `briques/studio/studio.py`, add near the other sibling-brique URL constants (after line 56, right after the `VIDEO_PUBLIC` line):

```python
# Brique « world-engine » (6230) : registre de personnages persistant (pont, S26x).
WORLD_ENGINE_URL = os.getenv("WORLD_ENGINE_URL", "http://host.docker.internal:6230")
```

Add right after `_appeler_video` (after line 825, before the `# ── Construction des tâches (prompts) ──` comment):

```python
# ── Pont vers la brique world-engine (6230) ──────────────────────

async def _appeler_world_engine(methode: str, route: str, payload: dict | None = None) -> Optional[dict]:
    """Appelle world-engine ; renvoie son résultat ou None (repli honnête, même motif que
    `_appeler_images`/`_appeler_video`) — jamais d'exception, jamais de donnée inventée si
    world-engine est injoignable. C'est l'APPELANT qui décide si `None` doit devenir un 502
    (geste explicite de l'utilisateur) ou rester silencieux (tick de fond, suggestions)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(methode, f"{WORLD_ENGINE_URL}{route}", json=payload)
            r.raise_for_status()
            return r.json()
    except Exception:  # noqa: BLE001
        return None


async def _pont_creer_monde() -> Optional[dict]:
    """Crée le monde world-engine d'une série (maillage minimal — détail technique, pas
    un choix narratif : 10 est le minimum accepté par `CreerMonde.nb_cellules`)."""
    return await _appeler_world_engine("POST", "/spatial/mondes", {"nb_cellules": 10})


async def _pont_fonder(monde_id: str, description: str, prenoms: str) -> Optional[dict]:
    """Fonde un habitant world-engine à partir de la description d'un personnage Studio —
    lieu/heure de naissance fixes (choix technique sans signification narrative, comme
    `annee_enfant` côté world-engine) : un personnage de fiction n'a pas de vraies
    coordonnées de naissance à fournir."""
    return await _appeler_world_engine("POST", "/genome/fonder", {
        "monde_id": monde_id, "description": description, "prenoms": prenoms, "nom": "",
        "latitude": 48.8566, "longitude": 2.3522, "heure_naissance": "12:00", "utc_offset": 1.0})


async def _pont_tick(monde_id: str) -> None:
    """Avance d'un tick le monde d'une série — un par chapitre écrit, best-effort."""
    await _appeler_world_engine("POST", f"/horloge/{monde_id}/tick")


async def _pont_lire_enfant(eid: str) -> Optional[dict]:
    """Lit la fiche + l'état simulé courant d'un habitant world-engine (champ
    `simulation`, voir docs/superpowers/plans/2026-08-26-world-engine-fondateur-solo.md)."""
    return await _appeler_world_engine("GET", f"/genome/enfants/{eid}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/studio && python -m pytest test_world_engine.py -v`
Expected: PASS (6 tests)

Then run the full suite to check nothing broke: `cd briques/studio && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_world_engine.py
git commit -m "feat(studio): _appeler_world_engine + wrappers pont (fonder/tick/lire)"
```

---

## Task 5: entrée dans le pont — `POST /series/{serie_id}/pont/fonder` + `pont_eligibles` sur les 2 routes de chapitre

**Files:**
- Modify: `briques/studio/studio.py`
- Modify: `briques/studio/main.py`
- Test: `briques/studio/test_pont_entree.py`

**Interfaces:**
- Consumes: `stockage_pont.lire_pont/fixer_monde/lier_habitant`, `studio._personnages_eligibles_pont`, `studio._pont_creer_monde/_pont_fonder/_pont_tick`, `studio._cle_perso`, `studio.SEUIL_RECURRENCE_PONT`, `charger` (already in `main.py`).
- Produces: `studio._pont_apres_chapitre(serie_id: str, serie: dict) -> list` (tick + éligibles), route `POST /series/{serie_id}/pont/fonder`, and `faire_episode`/`episode_express` responses gain a `pont_eligibles` key on the returned `episode`.

- [ ] **Step 1: Write the failing tests**

Create `briques/studio/test_pont_entree.py`:

```python
"""Tests — routes du pont Studio↔world-engine : entrée (fonder) + éligibles après
chapitre. Monkeypatch de httpx.AsyncClient (même motif que test_world_engine.py)."""
from fastapi.testclient import TestClient

import main
import stockage_pont as P
import studio as S

client = TestClient(main.app)


class _FauxRep:
    def __init__(self, data): self._data = data
    def raise_for_status(self): pass
    def json(self): return self._data


class _FauxClient:
    def __init__(self, reponses=None, leve=None):
        self._reponses = list(reponses or []); self._leve = leve
    def __call__(self, *a, **k): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def request(self, methode, url, json=None):
        if self._leve:
            raise self._leve
        return _FauxRep(self._reponses.pop(0))


def _serie_avec_personnage_caste(nom="Elara", description="Une aventurière rusée."):
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["personnages"] = [{"nom": nom, "role": "héroïne", "description": description}]
    S._save(serie)
    return sid


def test_fonder_personnage_non_eligible_422():
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Inconnu"})
    assert r.status_code == 422


def test_fonder_cree_le_monde_puis_lie_habitant(monkeypatch):
    sid = _serie_avec_personnage_caste()
    monkeypatch.setattr(S.httpx, "AsyncClient",
                         _FauxClient(reponses=[{"id": "monde-1", "nb_cellules": 10},
                                                {"eid": "eid-1", "cellule_id": 3, "theme": {}}]))
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Elara"})
    assert r.status_code == 200
    pont = r.json()
    assert pont["monde_id"] == "monde-1"
    assert pont["habitants"]["ELARA"]["eid"] == "eid-1"
    assert P.lire_pont(sid)["monde_id"] == "monde-1"


def test_fonder_reutilise_le_monde_deja_cree(monkeypatch):
    sid = _serie_avec_personnage_caste("Elara")
    P.fixer_monde(sid, "monde-existant")
    monkeypatch.setattr(S.httpx, "AsyncClient",
                         _FauxClient(reponses=[{"eid": "eid-2", "cellule_id": 1, "theme": {}}]))
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Elara"})
    assert r.status_code == 200
    assert r.json()["monde_id"] == "monde-existant"


def test_fonder_world_engine_injoignable_502(monkeypatch):
    sid = _serie_avec_personnage_caste()
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Elara"})
    assert r.status_code == 502


def test_pont_apres_chapitre_liste_les_eligibles_sans_tick_si_pas_de_monde():
    sid = _serie_avec_personnage_caste()
    serie = S._load(sid)
    import asyncio
    eligibles = asyncio.run(S._pont_apres_chapitre(sid, serie))
    assert eligibles == ["Elara"]


def test_pont_apres_chapitre_tick_si_monde_existant(monkeypatch):
    sid = _serie_avec_personnage_caste()
    P.fixer_monde(sid, "monde-1")
    appels = []

    class _ClientTraceur(_FauxClient):
        async def request(self, methode, url, json=None):
            appels.append((methode, url))
            return _FauxRep({})
    monkeypatch.setattr(S.httpx, "AsyncClient", _ClientTraceur())
    import asyncio
    serie = S._load(sid)
    asyncio.run(S._pont_apres_chapitre(sid, serie))
    assert ("POST", f"{S.WORLD_ENGINE_URL}/horloge/monde-1/tick") in appels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/studio && python -m pytest test_pont_entree.py -v`
Expected: FAIL — `404 Not Found` on the route tests, `AttributeError` on `S._pont_apres_chapitre` for the last two.

- [ ] **Step 3: Implement `_pont_apres_chapitre` in `studio.py`**

Add to `briques/studio/studio.py`, right after `_pont_lire_enfant` (end of the block added in Task 4):

```python
async def _pont_apres_chapitre(serie_id: str, serie: dict) -> list:
    """Après un chapitre écrit (canon déjà mis à jour par `_recolter_canon`) : avance
    d'un tick le monde de la série s'il existe déjà (best-effort, jamais bloquant), et
    renvoie les personnages nouvellement éligibles à une entrée dans world-engine."""
    import stockage_pont
    pont = stockage_pont.lire_pont(serie_id)
    if pont["monde_id"] is not None:
        await _pont_tick(pont["monde_id"])
    return _personnages_eligibles_pont(serie, pont)
```

- [ ] **Step 4: Wire `pont_eligibles` into the 2 chapter-generation routes in `main.py`**

Add `import stockage_pont` to the imports at the top of `briques/studio/main.py` (after `import studio as S`, line 29):

```python
import stockage_pont
```

In `faire_episode` (`main.py:1067-1103`), change:

```python
    serie["episodes"].append(episode)
    await S._recolter_canon(serie, script)
    S._save(serie)
    return episode
```

to:

```python
    serie["episodes"].append(episode)
    await S._recolter_canon(serie, script)
    episode["pont_eligibles"] = await S._pont_apres_chapitre(serie_id, serie)
    S._save(serie)
    return episode
```

In `episode_express` (`main.py:1260-1300`), change:

```python
    serie["episodes"].append(episode)
    await S._recolter_canon(serie, script)
    S._save(serie)
    return {"bible": serie["bible"], "episode": episode}
```

to:

```python
    serie["episodes"].append(episode)
    await S._recolter_canon(serie, script)
    episode["pont_eligibles"] = await S._pont_apres_chapitre(serie_id, serie)
    S._save(serie)
    return {"bible": serie["bible"], "episode": episode}
```

- [ ] **Step 5: Add the `POST /series/{serie_id}/pont/fonder` route in `main.py`**

Add right after `episode_express` (after line 1300, before the `# ── Arbre des choix ──` comment):

```python
# ── Pont vers world-engine (registre de personnages persistant) ──
class PontFonder(BaseModel):
    nom: str


@app.post("/series/{serie_id}/pont/fonder", tags=["pont"])
async def pont_fonder(serie_id: str, body: PontFonder, cle: str = Depends(cle_api)):
    """Fait entrer un personnage éligible dans world-engine — geste explicite de
    l'utilisateur, jamais automatique (voir design du pont Studio↔world-engine)."""
    serie = charger(serie_id, cle)
    pont = stockage_pont.lire_pont(serie_id)
    cle_nom = S._cle_perso(body.nom)
    eligibles = {S._cle_perso(n): n for n in S._personnages_eligibles_pont(serie, pont)}
    if cle_nom not in eligibles:
        raise HTTPException(422, f"'{body.nom}' n'est pas éligible pour l'instant (pas "
                                  f"casté formellement et moins de {S.SEUIL_RECURRENCE_PONT} "
                                  "apparitions).")
    if pont["monde_id"] is None:
        monde = await S._pont_creer_monde()
        if monde is None:
            raise HTTPException(502, f"Brique world-engine injoignable ({S.WORLD_ENGINE_URL}).")
        pont = stockage_pont.fixer_monde(serie_id, monde["id"])
    perso = next((p for p in serie.get("personnages") or []
                  if S._cle_perso(p.get("nom")) == cle_nom), None)
    description = ((perso or {}).get("description") or "").strip() or eligibles[cle_nom]
    fondation = await S._pont_fonder(pont["monde_id"], description, eligibles[cle_nom])
    if fondation is None:
        raise HTTPException(502, f"Brique world-engine injoignable ({S.WORLD_ENGINE_URL}).")
    return stockage_pont.lier_habitant(serie_id, cle_nom, fondation["eid"], eligibles[cle_nom],
                                        datetime.now(timezone.utc).isoformat())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd briques/studio && python -m pytest test_pont_entree.py -v`
Expected: PASS (6 tests)

Then run the full suite: `cd briques/studio && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add briques/studio/studio.py briques/studio/main.py briques/studio/test_pont_entree.py
git commit -m "feat(studio): POST /series/{id}/pont/fonder + pont_eligibles après chapitre"
```

---

## Task 6: retour dans le pont — `GET /series/{serie_id}/pont/suggestions` + `POST /series/{serie_id}/pont/accepter`

**Files:**
- Modify: `briques/studio/main.py`
- Test: `briques/studio/test_pont_retour.py`

**Interfaces:**
- Consumes: `stockage_pont.lire_pont/detacher_habitant`, `S._pont_lire_enfant`, `S._cle_perso`.
- Produces: routes `GET /series/{serie_id}/pont/suggestions` → `{"suggestions": [{nom_cle, nom_affiche, monde_id, cellule_id, ne_au_tick, age_actuel_ticks, vivant, mort_au_tick}]}`, `POST /series/{serie_id}/pont/accepter` → `{"acquis": [...]}`.

- [ ] **Step 1: Write the failing tests**

Create `briques/studio/test_pont_retour.py`:

```python
"""Tests — routes du pont Studio↔world-engine : retour (suggestions + acceptation)."""
from fastapi.testclient import TestClient

import main
import stockage_pont as P
import studio as S

client = TestClient(main.app)


class _FauxRep:
    def __init__(self, data): self._data = data
    def raise_for_status(self): pass
    def json(self): return self._data


class _FauxClient:
    def __init__(self, reponse=None, leve=None):
        self._reponse, self._leve = reponse, leve
    def __call__(self, *a, **k): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def request(self, methode, url, json=None):
        if self._leve:
            raise self._leve
        return _FauxRep(self._reponse)


def _serie_avec_habitant_lie(nom="Elara", eid="eid-1"):
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["personnages"] = [{"nom": nom, "role": "héroïne", "description": "x"}]
    S._save(serie)
    P.lier_habitant(sid, S._cle_perso(nom), eid, nom, "2026-08-26T00:00:00+00:00")
    return sid


def test_suggestions_vide_sans_personnage_lie():
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.get(f"/series/{sid}/pont/suggestions")
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_suggestions_vivant(monkeypatch):
    sid = _serie_avec_habitant_lie()
    sim = {"monde_id": "m1", "cellule_id": 2, "ne_au_tick": 0, "age_actuel_ticks": 4,
           "vivant": True, "mort_au_tick": None}
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(reponse={"id": "eid-1", "simulation": sim}))
    r = client.get(f"/series/{sid}/pont/suggestions")
    assert r.status_code == 200
    (sug,) = r.json()["suggestions"]
    assert sug["nom_affiche"] == "Elara"
    assert sug["age_actuel_ticks"] == 4
    assert sug["vivant"] is True


def test_suggestions_silencieuses_si_world_engine_injoignable(monkeypatch):
    sid = _serie_avec_habitant_lie()
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    r = client.get(f"/series/{sid}/pont/suggestions")
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_accepter_ajoute_un_fait_acquis(monkeypatch):
    sid = _serie_avec_habitant_lie()
    sim = {"monde_id": "m1", "cellule_id": 2, "ne_au_tick": 0, "age_actuel_ticks": 4,
           "vivant": True, "mort_au_tick": None}
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(reponse={"id": "eid-1", "simulation": sim}))
    r = client.post(f"/series/{sid}/pont/accepter", json={"nom_cles": ["ELARA"]})
    assert r.status_code == 200
    assert any("Elara" in f and "4" in f for f in r.json()["acquis"])
    assert any("Elara" in f for f in S._load(sid)["canon"]["acquis"])


def test_accepter_mort_detache_l_habitant(monkeypatch):
    sid = _serie_avec_habitant_lie()
    sim = {"monde_id": "m1", "cellule_id": 2, "ne_au_tick": 0, "age_actuel_ticks": 9,
           "vivant": False, "mort_au_tick": 9}
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(reponse={"id": "eid-1", "simulation": sim}))
    r = client.post(f"/series/{sid}/pont/accepter", json={"nom_cles": ["ELARA"]})
    assert r.status_code == 200
    assert "ELARA" not in P.lire_pont(sid)["habitants"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/studio && python -m pytest test_pont_retour.py -v`
Expected: FAIL with `404 Not Found` (routes don't exist yet).

- [ ] **Step 3: Implement the 2 routes**

Add to `briques/studio/main.py`, right after `pont_fonder` (end of the block added in Task 5):

```python
@app.get("/series/{serie_id}/pont/suggestions", tags=["pont"])
async def pont_suggestions(serie_id: str, cle: str = Depends(cle_api)):
    """État simulé world-engine des personnages castés déjà liés — à valider avant
    d'écrire le prochain chapitre, jamais injecté seul."""
    serie = charger(serie_id, cle)
    pont = stockage_pont.lire_pont(serie_id)
    suggestions = []
    for p in serie.get("personnages") or []:
        cle_nom = S._cle_perso(p.get("nom"))
        habitant = pont["habitants"].get(cle_nom)
        if not habitant:
            continue
        enfant = await S._pont_lire_enfant(habitant["eid"])
        sim = (enfant or {}).get("simulation")
        if sim is None:
            continue
        suggestions.append({"nom_cle": cle_nom, "nom_affiche": habitant["nom_affiche"], **sim})
    return {"suggestions": suggestions}


class PontAccepter(BaseModel):
    nom_cles: list[str]


@app.post("/series/{serie_id}/pont/accepter", tags=["pont"])
async def pont_accepter(serie_id: str, body: PontAccepter, cle: str = Depends(cle_api)):
    """Intègre au canon les faits acceptés par l'utilisateur pour des personnages liés —
    jamais automatique (voir pont_suggestions). Un personnage mort accepté est détaché du
    pont : plus jamais proposé (il redevient une fiche Studio ordinaire)."""
    serie = charger(serie_id, cle)
    pont = stockage_pont.lire_pont(serie_id)
    canon = serie.setdefault("canon", {})
    acquis = canon.setdefault("acquis", [])
    for cle_nom in body.nom_cles:
        habitant = pont["habitants"].get(cle_nom)
        if not habitant:
            continue
        enfant = await S._pont_lire_enfant(habitant["eid"])
        sim = (enfant or {}).get("simulation")
        if sim is None:
            continue
        nom = habitant["nom_affiche"]
        if sim["vivant"]:
            fait = f"{nom} a {sim['age_actuel_ticks']} an(s) et vit à la cellule {sim['cellule_id']} du monde simulé."
        else:
            fait = f"{nom} est mort dans le monde simulé, à {sim['age_actuel_ticks']} an(s)."
            stockage_pont.detacher_habitant(serie_id, cle_nom)
        if fait not in acquis:
            acquis.append(fait)
    S._save(serie)
    return {"acquis": canon["acquis"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/studio && python -m pytest test_pont_retour.py -v`
Expected: PASS (5 tests)

Then run the full suite: `cd briques/studio && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_pont_retour.py
git commit -m "feat(studio): GET pont/suggestions + POST pont/accepter — retour validé"
```

---

## Task 7: `manifest.json`

**Files:**
- Modify: `briques/studio/manifest.json`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n '"nom": "faire_episode"\|"chemin": "/series/{serie_id}/episode"' briques/studio/manifest.json`

Find the capacité entry for the `episode` route (or the closest production-tagged entry) to insert the 3 new capacités right after it, keeping capacités for the same feature area adjacent — follow the manifest's existing ordering convention (grouped by feature, same order as `main.py`'s routes).

- [ ] **Step 2: Add the 3 new capacités**

Insert into the `capacites` array of `briques/studio/manifest.json` (exact position from Step 1):

```json
    {
      "nom": "pont_fonder",
      "description": "Fait entrer un personnage éligible (casté formellement, ou vu dans au moins 3 chapitres distincts) dans world-engine comme habitant persistant du monde dédié à cette série — geste explicite, jamais automatique. Crée le monde de la série au premier personnage fondé.",
      "methode": "POST",
      "chemin": "/series/{serie_id}/pont/fonder",
      "params": {
        "serie_id": {"type": "string", "description": "Id de la série.", "requis": true},
        "nom": {"type": "string", "description": "Nom du personnage à fonder — doit être éligible (422 sinon).", "requis": true}
      },
      "action": true
    },
    {
      "nom": "pont_suggestions",
      "description": "Liste l'état simulé world-engine (âge, position, vivant/mort) des personnages castés déjà liés au pont — à présenter à l'utilisateur avant d'écrire un chapitre, jamais injecté seul. Vide si aucun personnage lié ou si world-engine est injoignable (repli honnête, pas une erreur).",
      "methode": "GET",
      "chemin": "/series/{serie_id}/pont/suggestions",
      "params": {
        "serie_id": {"type": "string", "description": "Id de la série.", "requis": true}
      },
      "action": false
    },
    {
      "nom": "pont_accepter",
      "description": "Intègre au canon de continuité les faits acceptés par l'utilisateur pour des personnages liés au pont (âge/position s'il est vivant, mort s'il est mort — auquel cas il est détaché du pont, plus jamais proposé).",
      "methode": "POST",
      "chemin": "/series/{serie_id}/pont/accepter",
      "params": {
        "serie_id": {"type": "string", "description": "Id de la série.", "requis": true},
        "nom_cles": {"type": "array", "description": "Clés normalisées des personnages dont les faits proposés sont acceptés (voir pont_suggestions pour les obtenir).", "requis": true}
      },
      "action": true
    },
```

- [ ] **Step 3: Verify the manifest test still passes**

Run: `cd briques/studio && python -m pytest test_manifest_capacites.py -v`
Expected: PASS.

Then run the full suite one last time: `cd briques/studio && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add briques/studio/manifest.json
git commit -m "docs(studio): manifest — 3 capacités du pont Studio↔world-engine"
```

---

## Task 8: front — proposer l'entrée et le retour

**Files:**
- Modify: `briques/studio/front.html`

**Interfaces:**
- Consumes: `api()`, `toast()`, `S()`, `refresh()`, `vue()`, `esc()` (all already defined in `front.html`), the delegated click listener (`front.html:188-207`), routes from Tasks 5-6.
- Produces: 2 new UI affordances in the "Chapitres" view — a list of éligibles with a "Fonder" button after writing a chapter, and a "Voir l'historique simulé" check before writing the next one.

There is no automated test for `front.html` in this brique (no JS test runner) — verification is manual per this plan's Step 3.

- [ ] **Step 1: Show `pont_eligibles` after writing a chapter**

In `briques/studio/front.html`, add a case to the delegated click listener (after the `retenirBtn` block, before the closing `});` at line 207):

```javascript
  const fonderBtn = t.closest('[data-fonder-nom]');
  if (fonderBtn) { fonderPersonnage(fonderBtn.dataset.fonderNom); return; }
```

Add a new function near `ecrireChapitre` (after line 703, before `async function produireAudio`):

```javascript
let PONT_ELIGIBLES = [];
async function fonderPersonnage(nom){
  toast('🌍 Entrée dans world-engine…');
  try{
    await api(`/series/${S().id}/pont/fonder`,'POST',{nom});
    PONT_ELIGIBLES = PONT_ELIGIBLES.filter(n=>n!==nom);
    vue('Chapitres');
    toast(`${nom} est maintenant suivi dans world-engine 🌍`);
  }catch(e){ toast('⚠ '+e.message); }
}
function renderPontEligibles(){
  if(!PONT_ELIGIBLES.length) return '';
  return `<div class="hint" style="margin-top:10px">Personnages récurrents détectés :
    ${PONT_ELIGIBLES.map(n=>`<button class="sm ghost" data-fonder-nom="${esc(n)}">🌍 Fonder ${esc(n)}</button>`).join(' ')}
  </div>`;
}
```

Modify `ecrireChapitre` (line 698-703) from:

```javascript
async function ecrireChapitre(){
  const b=$('btn-ep'); b.disabled=true; b.textContent='✍️ Le Scénariste écrit…'; $('ch-err').textContent='';
  try{ await api(`/series/${S().id}/episode`,'POST',{branche:$('ch-dir').value.trim()||null}); await refresh(); vue('Chapitres'); toast('Chapitre écrit ✍️'); }
  catch(e){ $('ch-err').textContent='⚠ '+e.message; }
  finally{ b.disabled=false; }
}
```

to:

```javascript
async function ecrireChapitre(){
  const b=$('btn-ep'); b.disabled=true; b.textContent='✍️ Le Scénariste écrit…'; $('ch-err').textContent='';
  try{
    const ep = await api(`/series/${S().id}/episode`,'POST',{branche:$('ch-dir').value.trim()||null});
    PONT_ELIGIBLES = ep.pont_eligibles || [];
    await refresh(); vue('Chapitres'); toast('Chapitre écrit ✍️');
  }
  catch(e){ $('ch-err').textContent='⚠ '+e.message; }
  finally{ b.disabled=false; }
}
```

Modify `vueChapitres` (line 594-603) to render `renderPontEligibles()` right after the direction input, from:

```javascript
    <input id="ch-dir" placeholder="On suit l'antagoniste cette fois…">
    <button style="margin-top:10px" id="btn-ep" onclick="ecrireChapitre()">✍️ Écrire le chapitre ${eps.length+1}</button>
    <div class="err" id="ch-err"></div>
```

to:

```javascript
    <input id="ch-dir" placeholder="On suit l'antagoniste cette fois…">
    <button style="margin-top:10px" id="btn-ep" onclick="ecrireChapitre()">✍️ Écrire le chapitre ${eps.length+1}</button>
    <div class="err" id="ch-err"></div>
    ${renderPontEligibles()}
```

- [ ] **Step 2: Show retour suggestions before writing the next chapter**

Modify `ecrireChapitre` again to check suggestions first and let the user confirm — from the version written in Step 1, to:

```javascript
async function ecrireChapitre(){
  try{
    const { suggestions } = await api(`/series/${S().id}/pont/suggestions`);
    if(suggestions.length){
      const texte = suggestions.map(s => s.vivant
        ? `${s.nom_affiche} : ${s.age_actuel_ticks} an(s), toujours vivant(e).`
        : `${s.nom_affiche} : mort(e) à ${s.age_actuel_ticks} an(s).`).join('\n');
      const accepter = confirm(`world-engine signale :\n\n${texte}\n\nIntégrer ces faits au canon avant d'écrire ?`);
      if(accepter){
        await api(`/series/${S().id}/pont/accepter`,'POST',{nom_cles: suggestions.map(s=>s.nom_cle)});
      }
    }
  }catch(e){ /* repli honnête : pas de suggestion, on écrit quand même */ }
  const b=$('btn-ep'); b.disabled=true; b.textContent='✍️ Le Scénariste écrit…'; $('ch-err').textContent='';
  try{
    const ep = await api(`/series/${S().id}/episode`,'POST',{branche:$('ch-dir').value.trim()||null});
    PONT_ELIGIBLES = ep.pont_eligibles || [];
    await refresh(); vue('Chapitres'); toast('Chapitre écrit ✍️');
  }
  catch(e){ $('ch-err').textContent='⚠ '+e.message; }
  finally{ b.disabled=false; }
}
```

- [ ] **Step 3: Manual verification**

Start the brique locally (`cd briques/studio && uvicorn main:app --reload --port 5920` or via its own `docker-compose.yml`) and world-engine locally too (`cd briques/world-engine && uvicorn main:app --reload --port 6230`, both plans in this pair implemented). In the front:
1. Create a série, cast a personnage in "Personnages" with a role/description.
2. Write a chapter — a "🌍 Fonder <nom>" button should appear under the chapter form.
3. Click it — a toast confirms, the button disappears.
4. Write a second chapter — a browser `confirm()` dialog should appear showing that personnage's simulated age (0, since only 1 tick has passed) before the chapter is generated.

- [ ] **Step 4: Commit**

```bash
git add briques/studio/front.html
git commit -m "feat(studio): front — proposer l'entrée et le retour du pont world-engine"
```
