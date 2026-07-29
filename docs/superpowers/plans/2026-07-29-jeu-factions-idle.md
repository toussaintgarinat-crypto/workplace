# Jeu-factions — progression idle (S216) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give personnages engaged on a voie d'archétype a passive progression bonus while their account has been idle, without adding any new server loop or touching the real-time combat engine.

**Architecture:** A single fixed 30s heartbeat (`POST /presence`) from the front updates a per-account `derniere_presence` timestamp. A pure function (`archetypes.bonus_idle`) converts elapsed time since that timestamp into points, capped at one tick cycle. The existing daily tick (`groupes.resoudre_groupes_actifs()`, called by `tick.boucle_tick()`, cadence unchanged) adds this bonus — only for the member whose own next step matches the group's target — to the stat total it already compares against the step's difficulty. `GET /personnages` exposes the same computation read-only so the front can show it before the next tick runs.

**Tech Stack:** Python 3, FastAPI, SQLite (stdlib `sqlite3`), pytest, vanilla JS front (no build step).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-29-jeu-factions-idle-design.md` — read it before starting if anything below is ambiguous.
- No new table, no new persisted "balance" — the bonus is always recomputed from `derniere_presence` at read time (spec, "Modèle de données").
- Never touch `combat_moteur.py` / `combat.py` (spec, Non-objectifs).
- The bonus only ever applies to voie d'archétype progression, never to zones de signe (spec, Non-objectifs).
- `tick.py::TICK_INTERVAL_HOURS` cadence stays unchanged — no new `asyncio.sleep` loop is introduced anywhere in this plan.
- All DB access follows the existing short-connection discipline already documented in `groupes.py`'s docstring: each read/write opens its own `with S._conn() as c:`, never nested across a call to a function that opens its own connection.
- Run tests from `briques/jeu-factions/` with `python -m pytest <file> -v` (repo convention, see `README.md`).

---

### Task 1: Présence par compte (`stockage.py`)

**Files:**
- Modify: `briques/jeu-factions/stockage.py:17-33` (migration helper + `joueurs` table)
- Modify: `briques/jeu-factions/stockage.py:68-75` (call site pattern to mirror)
- Test: `briques/jeu-factions/test_stockage.py`

**Interfaces:**
- Produces: `stockage.enregistrer_presence(cle_api: str) -> None`, `stockage.lire_derniere_presence(cle_api: str) -> str | None`, `stockage.lire_derniere_presence_personnage(personnage_id: str) -> str | None` — all three used by Task 4 (`groupes.py`) and Task 5 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Add to `briques/jeu-factions/test_stockage.py` (append at end of file):

```python
def test_enregistrer_presence_puis_lire():
    S.assurer_joueur("cleF", "Finn")
    assert S.lire_derniere_presence("cleF") is None
    S.enregistrer_presence("cleF")
    assert S.lire_derniere_presence("cleF") is not None


def test_enregistrer_presence_cree_le_joueur_si_absent():
    assert S.lire_derniere_presence("cleG") is None
    S.enregistrer_presence("cleG")
    assert S.lire_derniere_presence("cleG") is not None


def test_lire_derniere_presence_personnage_suit_le_compte_proprietaire():
    S.assurer_joueur("cleH", "Hugo")
    p = S.creer_personnage("cleH", "Perso", {"date_naissance": "1990-01-01"}, {"portrait": {}})
    assert S.lire_derniere_presence_personnage(p["id"]) is None
    S.enregistrer_presence("cleH")
    assert S.lire_derniere_presence_personnage(p["id"]) is not None


def test_lire_derniere_presence_personnage_inconnu_est_none():
    assert S.lire_derniere_presence_personnage("perso-inconnu") is None


def test_migration_derniere_presence_est_presente_et_idempotente():
    with S._conn() as c:
        colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    assert "derniere_presence" in colonnes
    S._conn()  # rejouer la migration ne doit pas lever d'erreur
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py -v`
Expected: FAIL — `AttributeError: module 'stockage' has no attribute 'enregistrer_presence'`

- [ ] **Step 3: Add the migration helper and call it**

In `stockage.py`, add a new function right after `_migrer_colonnes_effet_competences` (after line 25, before `def _conn()`):

```python
def _migrer_colonne_presence(c: sqlite3.Connection) -> None:
    """Ajoute `derniere_presence` à `joueurs` si absente (même motif que
    `_migrer_colonnes_effet_competences` ci-dessus)."""
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    if "derniere_presence" not in colonnes:
        c.execute("ALTER TABLE joueurs ADD COLUMN derniere_presence TEXT")
```

Then, in `_conn()`, right after the `joueurs` table creation (the line `c.execute("""CREATE TABLE IF NOT EXISTS joueurs (...)""")` currently at line 32-33), add the call:

```python
    c.execute("""CREATE TABLE IF NOT EXISTS joueurs (
        cle_api TEXT PRIMARY KEY, pseudo TEXT NOT NULL)""")
    _migrer_colonne_presence(c)
```

- [ ] **Step 4: Add the three functions**

Add at the end of `stockage.py` (after `log_resolution`):

```python
def enregistrer_presence(cle_api: str) -> None:
    with _conn() as c:
        c.execute("""INSERT INTO joueurs (cle_api, pseudo, derniere_presence) VALUES (?,?,?)
                     ON CONFLICT(cle_api) DO UPDATE SET derniere_presence=excluded.derniere_presence""",
                  (cle_api, cle_api, _maintenant()))


def lire_derniere_presence(cle_api: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT derniere_presence FROM joueurs WHERE cle_api=?",
                        (cle_api,)).fetchone()
    return row["derniere_presence"] if row else None


def lire_derniere_presence_personnage(personnage_id: str) -> str | None:
    with _conn() as c:
        row = c.execute("""SELECT j.derniere_presence FROM personnages_jeu p
                            JOIN joueurs j ON j.cle_api = p.cle_api
                            WHERE p.id=?""", (personnage_id,)).fetchone()
    return row["derniere_presence"] if row else None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py -v`
Expected: PASS (all tests including the 5 new ones)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions/stockage.py briques/jeu-factions/test_stockage.py
git commit -m "feat(jeu-factions): présence par compte (derniere_presence, S216 idle)"
```

---

### Task 2: Fonction pure `bonus_idle` (`archetypes.py`)

**Files:**
- Modify: `briques/jeu-factions/archetypes.py:1-8` (imports + constants)
- Test: `briques/jeu-factions/test_archetypes.py`

**Interfaces:**
- Consumes: nothing new (pure function, only stdlib `datetime`).
- Produces: `archetypes.TAUX_IDLE_PAR_HEURE: float`, `archetypes.PLAFOND_IDLE_HEURES: float`, `archetypes.bonus_idle(derniere_presence: str | None, maintenant: datetime, taux_par_heure: float, plafond_heures: float) -> int` — used by Task 4 (`groupes.py`) and Task 5 (`main.py`). No default arguments (deliberate — see note in Step 3) so tests and call sites always pass explicit values, and `monkeypatch.setattr(archetypes, "TAUX_IDLE_PAR_HEURE", ...)` reliably affects any call site that reads the module attribute at call time.

- [ ] **Step 1: Write the failing tests**

Add to `briques/jeu-factions/test_archetypes.py` (append at end of file). First add the import at the top of the file (currently just `import archetypes as A`):

```python
from datetime import datetime, timezone

import archetypes as A
```

Then append:

```python
def test_bonus_idle_sans_presence_est_nul():
    assert A.bonus_idle(None, datetime.now(timezone.utc), taux_par_heure=2.0, plafond_heures=24) == 0


def test_bonus_idle_arrondit_a_lentier_inferieur():
    maintenant = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    derniere = datetime(2026, 7, 30, 11, 20, 0, tzinfo=timezone.utc)  # 40 min plus tôt
    bonus = A.bonus_idle(derniere.isoformat(), maintenant, taux_par_heure=1.0, plafond_heures=24)
    assert bonus == 0  # 0.667h x 1 pt/h = 0.667 → arrondi à 0


def test_bonus_idle_proportionnel_au_temps_ecoule():
    maintenant = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    derniere = datetime(2026, 7, 30, 7, 0, 0, tzinfo=timezone.utc)  # 5h plus tôt
    bonus = A.bonus_idle(derniere.isoformat(), maintenant, taux_par_heure=2.0, plafond_heures=24)
    assert bonus == 10  # 5h x 2 pts/h


def test_bonus_idle_plafonne_au_dela_du_plafond():
    maintenant = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
    derniere = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)  # 48h plus tôt
    bonus = A.bonus_idle(derniere.isoformat(), maintenant, taux_par_heure=2.0, plafond_heures=24)
    assert bonus == 48  # plafonné à 24h x 2 pts/h, pas 48h x 2


def test_bonus_idle_futur_ou_maintenant_est_nul():
    maintenant = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert A.bonus_idle(maintenant.isoformat(), maintenant, taux_par_heure=2.0, plafond_heures=24) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: FAIL — `AttributeError: module 'archetypes' has no attribute 'bonus_idle'`

- [ ] **Step 3: Implement `bonus_idle` and the two constants**

At the top of `archetypes.py`, change:

```python
from __future__ import annotations

import uuid

import stockage as S
```

to:

```python
from __future__ import annotations

import os
import uuid
from datetime import datetime

import stockage as S
```

Then, right after the `ARCHETYPES_SIGNATURE` dict (after line 21, before the `# 3 étapes par voie` comment), add:

```python
# S216 — progression idle : bonus de points de voie d'archétype pendant l'absence.
# Plafonné à un cycle de tick (même variable d'env que `tick.TICK_INTERVAL_HOURS`, lue ici
# indépendamment pour éviter un import circulaire archetypes -> tick -> groupes -> archetypes).
TAUX_IDLE_PAR_HEURE = 2.0
PLAFOND_IDLE_HEURES = float(os.getenv("TICK_INTERVAL_HOURS", "24"))


def bonus_idle(derniere_presence: str | None, maintenant: datetime,
               taux_par_heure: float, plafond_heures: float) -> int:
    """Fonction PURE : points de progression accumulés depuis `derniere_presence`, plafonnés
    à `plafond_heures` d'absence. `derniere_presence=None` (jamais de heartbeat) -> 0."""
    if not derniere_presence:
        return 0
    depuis = datetime.fromisoformat(derniere_presence)
    heures_ecoulees = (maintenant - depuis).total_seconds() / 3600
    if heures_ecoulees <= 0:
        return 0
    return int(taux_par_heure * min(heures_ecoulees, plafond_heures))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: PASS (all tests including the 5 new ones)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/archetypes.py briques/jeu-factions/test_archetypes.py
git commit -m "feat(jeu-factions): fonction pure bonus_idle (S216 idle)"
```

---

### Task 3: `calculer_resolution` gagne un bonus par membre (`archetypes.py`)

**Files:**
- Modify: `briques/jeu-factions/archetypes.py` (function `calculer_resolution`, currently lines 126-130)
- Test: `briques/jeu-factions/test_archetypes.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `archetypes.calculer_resolution(membres_stats: list[dict], stats_cles: tuple[str, str, str], difficulte: int, bonus_par_membre: dict[str, int] | None = None) -> dict` — same return shape as before (`{"total": int, "vaincue": bool}`). `bonus_par_membre` defaults to `None` (treated as empty) so every existing call site keeps working unchanged. Used by Task 4 (`groupes.py`).

- [ ] **Step 1: Write the failing tests**

Add to `briques/jeu-factions/test_archetypes.py` (append at end of file):

```python
def test_calculer_resolution_sans_bonus_est_inchangee():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100)
    assert res["total"] == 90
    assert res["vaincue"] is False


def test_calculer_resolution_bonus_sur_membre_absent_est_ignore():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100,
                                bonus_par_membre={"pX": 999})
    assert res["total"] == 90


def test_calculer_resolution_bonus_ajoute_au_membre_concerne():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100,
                                bonus_par_membre={"p1": 15})
    assert res["total"] == 105
    assert res["vaincue"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: FAIL — `TypeError: calculer_resolution() got an unexpected keyword argument 'bonus_par_membre'`

- [ ] **Step 3: Implement**

Replace the existing `calculer_resolution` function:

```python
def calculer_resolution(membres_stats: list[dict], stats_cles: tuple[str, str, str],
                        difficulte: int) -> dict:
    """Fonction PURE : `membres_stats` = [{"personnage_id", "stats": {...}}]."""
    total = sum(sum(int(m["stats"].get(s, 0)) for s in stats_cles) for m in membres_stats)
    return {"total": total, "vaincue": total >= difficulte}
```

with:

```python
def calculer_resolution(membres_stats: list[dict], stats_cles: tuple[str, str, str],
                        difficulte: int, bonus_par_membre: dict[str, int] | None = None) -> dict:
    """Fonction PURE : `membres_stats` = [{"personnage_id", "stats": {...}}].
    `bonus_par_membre` (S216 idle) ajoute des points à la contribution d'un membre précis
    avant sommation — absent de `membres_stats` -> ignoré silencieusement."""
    bonus_par_membre = bonus_par_membre or {}
    total = sum(sum(int(m["stats"].get(s, 0)) for s in stats_cles) +
               bonus_par_membre.get(m["personnage_id"], 0)
               for m in membres_stats)
    return {"total": total, "vaincue": total >= difficulte}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: PASS (all tests including the 3 new ones)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/archetypes.py briques/jeu-factions/test_archetypes.py
git commit -m "feat(jeu-factions): calculer_resolution accepte un bonus par membre (S216 idle)"
```

---

### Task 4: Intégration dans le tick de résolution (`groupes.py`)

**Files:**
- Modify: `briques/jeu-factions/groupes.py:58-98` (function `resoudre_groupes_actifs`)
- Test: `briques/jeu-factions/test_groupes.py`

**Interfaces:**
- Consumes: `stockage.lire_derniere_presence_personnage` (Task 1), `archetypes.bonus_idle`, `archetypes.TAUX_IDLE_PAR_HEURE`, `archetypes.PLAFOND_IDLE_HEURES` (Task 2), `archetypes.calculer_resolution(..., bonus_par_membre=...)` (Task 3).
- Produces: no new public function — `groupes.resoudre_groupes_actifs()` keeps its existing signature and return shape (`list[dict]` with `groupe_id`/`etat_resultant`/`total`/`vaincue`), now idle-bonus-aware.

- [ ] **Step 1: Write the failing tests**

Add to `briques/jeu-factions/test_groupes.py`. First add the import at the top of the file (currently `import archetypes as A`, `import stockage as S`, `import groupes as G`):

```python
from datetime import datetime, timedelta, timezone

import archetypes as A
import stockage as S
import groupes as G
```

Then append at the end of the file:

```python
def test_resoudre_groupes_actifs_bonus_idle_comble_lecart(monkeypatch):
    A.seed_zones_archetype()
    monkeypatch.setattr(A, "TAUX_IDLE_PAR_HEURE", 1000.0)
    p = _personnage("cleG8", "Fatigue", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    with S._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cleG8"))
    etapes = A.lister_etapes("Le Meneur Charismatique")
    G.creer_groupe(p["id"], etapes[0]["id"])
    resultats = G.resoudre_groupes_actifs()
    # stats brutes = 30, bien sous la difficulté 80 de l'étape 1 — seul le bonus idle
    # (1h x 1000 pts/h, monkeypatché) permet de la franchir.
    assert any(r["etat_resultant"] == "vaincue" for r in resultats)
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]


def test_resoudre_groupes_actifs_bonus_idle_du_carry_ne_beneficie_pas_a_la_cible(monkeypatch):
    A.seed_zones_archetype()
    monkeypatch.setattr(A, "TAUX_IDLE_PAR_HEURE", 1000.0)
    p = _personnage("cleG10", "Cible7", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    aide = _personnage("cleG10b", "Portefaix", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    # p franchit l'étape 1 seul grâce à SON propre bonus idle (stats brutes 30, insuffisantes
    # seules face à la difficulté 80).
    with S._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cleG10"))
    G.creer_groupe(p["id"], etapes[0]["id"])
    G.resoudre_groupes_actifs()
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
    assert A.prochaine_etape(aide["id"], "Le Meneur Charismatique") == etapes[0]["id"]
    # p "revient" (présence remise à maintenant -> bonus nul pour la suite) ; aide reste idle
    # depuis 1h (bonus énorme avec le taux monkeypatché) mais rejoint en CARRY sur l'étape 2
    # de p — pas structurellement SA prochaine étape (la sienne reste l'étape 1).
    S.enregistrer_presence("cleG10")
    with S._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cleG10b"))
    g2 = G.creer_groupe(p["id"], etapes[1]["id"])
    G.rejoindre_groupe(g2["id"], aide["id"])
    resultats = G.resoudre_groupes_actifs()
    # total brut = 30 (p) + 30 (aide) = 60, bien sous la difficulté 140 — si le bonus de aide
    # fuitait dans le total du groupe (1000+ pts), l'étape 2 serait vaincue à tort.
    assert all(r["etat_resultant"] == "en_cours" for r in resultats if r["groupe_id"] == g2["id"])
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_groupes.py -v`
Expected: FAIL — both new tests fail their `assert` (bonus not yet wired in, so the étape never resolves)

- [ ] **Step 3: Implement**

In `groupes.py`, add the datetime import at the top (currently `from datetime import datetime, timezone` is already there for `_maintenant()` — no change needed there). Replace the body of `resoudre_groupes_actifs()`:

```python
def resoudre_groupes_actifs() -> list[dict]:
    """Orchestration DB — même discipline de connexions courtes que `zones.ajouter_score`/
    `marquer_vaincue_si_premiere_fois` (voir stockage.py) : chaque lecture/écriture utilise sa
    PROPRE connexion courte, refermée avant d'appeler une fonction qui ouvre la sienne
    (`archetypes.py`, `stockage.log_resolution`). Tenir une connexion ouverte pendant ces
    appels imbriqués se verrouille elle-même (`database is locked`) — NE PAS envelopper toute
    la fonction dans un seul `with S._conn() as c:`."""
    resultats = []
    with S._conn() as c:
        groupes_actifs = c.execute("SELECT * FROM groupes WHERE etat='actif'").fetchall()
    for gr in groupes_actifs:
        etape = A.lire_etape(gr["zone_archetype_id"])
        if not etape:
            continue
        stats_cles = A.ARCHETYPES_SIGNATURE[etape["archetype"]]
        with S._conn() as c:
            membres_ids = [r["personnage_id"] for r in c.execute(
                "SELECT personnage_id FROM membres_groupe WHERE groupe_id=?", (gr["id"],)).fetchall()]
            membres_stats = []
            for mid in membres_ids:
                row = c.execute("SELECT snapshot_holistique FROM personnages_jeu WHERE id=?",
                                (mid,)).fetchone()
                if not row:
                    continue
                snap = json.loads(row["snapshot_holistique"])
                stats = (snap.get("portrait") or {}).get("stats") or {}
                membres_stats.append({"personnage_id": mid, "stats": stats})
        res = A.calculer_resolution(membres_stats, stats_cles, etape["difficulte_pve"])
        etat_resultant = "vaincue" if res["vaincue"] else "en_cours"
        if res["vaincue"]:
            for mid in membres_ids:
                if A.prochaine_etape(mid, etape["archetype"]) == gr["zone_archetype_id"]:
                    A.marquer_etape_vaincue(mid, gr["zone_archetype_id"])
                    A.debloquer_competence_si_existe(mid, gr["zone_archetype_id"])
            with S._conn() as c:
                c.execute("UPDATE groupes SET etat='dissous' WHERE id=?", (gr["id"],))
        contributions = {m["personnage_id"]: sum(int(m["stats"].get(s, 0)) for s in stats_cles)
                         for m in membres_stats}
        S.log_resolution(None, gr["zone_archetype_id"], contributions, etat_resultant)
        resultats.append({"groupe_id": gr["id"], "etat_resultant": etat_resultant, **res})
    return resultats
```

with (change is: a `maintenant` timestamp shared across the whole tick pass, a `bonus_par_membre` dict built per group — only for members whose own next step matches this group's target — and it's passed into `calculer_resolution`):

```python
def resoudre_groupes_actifs() -> list[dict]:
    """Orchestration DB — même discipline de connexions courtes que `zones.ajouter_score`/
    `marquer_vaincue_si_premiere_fois` (voir stockage.py) : chaque lecture/écriture utilise sa
    PROPRE connexion courte, refermée avant d'appeler une fonction qui ouvre la sienne
    (`archetypes.py`, `stockage.log_resolution`). Tenir une connexion ouverte pendant ces
    appels imbriqués se verrouille elle-même (`database is locked`) — NE PAS envelopper toute
    la fonction dans un seul `with S._conn() as c:`."""
    resultats = []
    maintenant = datetime.now(timezone.utc)
    with S._conn() as c:
        groupes_actifs = c.execute("SELECT * FROM groupes WHERE etat='actif'").fetchall()
    for gr in groupes_actifs:
        etape = A.lire_etape(gr["zone_archetype_id"])
        if not etape:
            continue
        stats_cles = A.ARCHETYPES_SIGNATURE[etape["archetype"]]
        with S._conn() as c:
            membres_ids = [r["personnage_id"] for r in c.execute(
                "SELECT personnage_id FROM membres_groupe WHERE groupe_id=?", (gr["id"],)).fetchall()]
            membres_stats = []
            for mid in membres_ids:
                row = c.execute("SELECT snapshot_holistique FROM personnages_jeu WHERE id=?",
                                (mid,)).fetchone()
                if not row:
                    continue
                snap = json.loads(row["snapshot_holistique"])
                stats = (snap.get("portrait") or {}).get("stats") or {}
                membres_stats.append({"personnage_id": mid, "stats": stats})
        # S216 — bonus idle : uniquement pour le(s) membre(s) dont c'est réellement leur
        # propre prochaine étape (jamais un carry), jamais persisté (recalculé à chaque tick).
        bonus_par_membre = {}
        for mid in membres_ids:
            if A.prochaine_etape(mid, etape["archetype"]) == gr["zone_archetype_id"]:
                derniere_presence = S.lire_derniere_presence_personnage(mid)
                bonus = A.bonus_idle(derniere_presence, maintenant,
                                     A.TAUX_IDLE_PAR_HEURE, A.PLAFOND_IDLE_HEURES)
                if bonus:
                    bonus_par_membre[mid] = bonus
        res = A.calculer_resolution(membres_stats, stats_cles, etape["difficulte_pve"], bonus_par_membre)
        etat_resultant = "vaincue" if res["vaincue"] else "en_cours"
        if res["vaincue"]:
            for mid in membres_ids:
                if A.prochaine_etape(mid, etape["archetype"]) == gr["zone_archetype_id"]:
                    A.marquer_etape_vaincue(mid, gr["zone_archetype_id"])
                    A.debloquer_competence_si_existe(mid, gr["zone_archetype_id"])
            with S._conn() as c:
                c.execute("UPDATE groupes SET etat='dissous' WHERE id=?", (gr["id"],))
        contributions = {m["personnage_id"]: sum(int(m["stats"].get(s, 0)) for s in stats_cles)
                         for m in membres_stats}
        S.log_resolution(None, gr["zone_archetype_id"], contributions, etat_resultant)
        resultats.append({"groupe_id": gr["id"], "etat_resultant": etat_resultant, **res})
    return resultats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_groupes.py -v`
Expected: PASS (all tests including the 2 new ones)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/groupes.py briques/jeu-factions/test_groupes.py
git commit -m "feat(jeu-factions): le tick de résolution des groupes applique le bonus idle (S216)"
```

---

### Task 5: API — `POST /presence` + `GET /personnages` enrichi (`main.py`)

**Files:**
- Modify: `briques/jeu-factions/main.py:1-10` (imports)
- Modify: `briques/jeu-factions/main.py:111-113` (`lister_personnages_route`)
- Test: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Consumes: `stockage.enregistrer_presence`, `stockage.lire_derniere_presence` (Task 1), `archetypes.bonus_idle`, `archetypes.TAUX_IDLE_PAR_HEURE`, `archetypes.PLAFOND_IDLE_HEURES` (Task 2), `archetypes.prochaine_etape` (existing).
- Produces: `POST /presence` (returns `{"ok": true}`), `GET /personnages` items gain a `bonus_idle_actuel: int` field — consumed by Task 6 (`front.html`).

- [ ] **Step 1: Write the failing tests**

Add to `briques/jeu-factions/test_api.py`. First add the datetime import at the top (currently just `from fastapi.testclient import TestClient` / `from main import app`):

```python
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from main import app
```

Then append at the end of the file:

```python
def test_presence_route_ok():
    r = client.post("/presence", headers={"X-API-Key": "cle-presence"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_presence_route_rejette_une_cle_invalide():
    import main
    main.API_KEYS = {"bonnecle"}
    try:
        r = client.post("/presence", headers={"X-API-Key": "mauvaise"})
        assert r.status_code == 401
    finally:
        main.API_KEYS = set()


def test_personnages_expose_bonus_idle_actuel(monkeypatch):
    _patch_moteur(monkeypatch)
    import main
    monkeypatch.setattr(main.archetypes, "TAUX_IDLE_PAR_HEURE", 1000.0)
    r = client.post("/personnages", json={"nom": "Idle1", "date_naissance": "1990-01-01"},
                    headers={"X-API-Key": "cle-idle-api"})
    pid = r.json()["id"]
    with main.stockage._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cle-idle-api"))
    items = client.get("/personnages", headers={"X-API-Key": "cle-idle-api"}).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["bonus_idle_actuel"] > 0


def test_personnages_sans_presence_a_bonus_idle_nul(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Idle2", "date_naissance": "1990-01-01"},
                    headers={"X-API-Key": "cle-idle-api2"})
    pid = r.json()["id"]
    items = client.get("/personnages", headers={"X-API-Key": "cle-idle-api2"}).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["bonus_idle_actuel"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: FAIL — `test_presence_route_ok` gets a 404 (route doesn't exist yet), the two `bonus_idle_actuel` tests get a `KeyError`

- [ ] **Step 3: Implement**

At the top of `main.py`, change:

```python
import asyncio
import os
import time
from pathlib import Path
from typing import Optional
```

to:

```python
import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
```

Replace the existing `lister_personnages_route`:

```python
@app.get("/personnages", tags=["personnages"])
def lister_personnages_route(cle: str = Depends(cle_api)):
    return stockage.lister_personnages(cle)
```

with:

```python
@app.post("/presence", tags=["personnages"])
def enregistrer_presence_route(cle: str = Depends(cle_api)):
    stockage.enregistrer_presence(cle)
    return {"ok": True}


@app.get("/personnages", tags=["personnages"])
def lister_personnages_route(cle: str = Depends(cle_api)):
    personnages = stockage.lister_personnages(cle)
    derniere_presence = stockage.lire_derniere_presence(cle)
    maintenant = datetime.now(timezone.utc)
    for p in personnages:
        archetype = (p["snapshot_holistique"].get("portrait") or {}).get("archetype")
        prochaine = archetypes.prochaine_etape(p["id"], archetype) if archetype else None
        p["bonus_idle_actuel"] = (
            archetypes.bonus_idle(derniere_presence, maintenant,
                                  archetypes.TAUX_IDLE_PAR_HEURE, archetypes.PLAFOND_IDLE_HEURES)
            if prochaine else 0)
    return personnages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS (all tests including the 4 new ones)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/test_api.py
git commit -m "feat(jeu-factions): route POST /presence + GET /personnages expose bonus_idle_actuel (S216)"
```

---

### Task 6: Front — heartbeat + affichage (`front.html`)

**Files:**
- Modify: `briques/jeu-factions/front.html` (script section)
- Test: `briques/jeu-factions/test_front.py`

**Interfaces:**
- Consumes: `POST /presence`, `GET /personnages` field `bonus_idle_actuel` (Task 5).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Write the failing test**

Add to `briques/jeu-factions/test_front.py` (append at end of file):

```python
def test_front_contient_le_heartbeat_de_presence():
    r = client.get("/")
    assert "/presence" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/jeu-factions && python -m pytest test_front.py -v`
Expected: FAIL — `assert "/presence" in r.text` is `False`

- [ ] **Step 3: Implement**

In `front.html`, replace the `chargerPersonnages` function:

```javascript
async function chargerPersonnages() {
  const r = await fetch("/personnages", {headers: entetes()});
  const items = await r.json();
  document.getElementById("listePersonnages").innerHTML = items.map(p =>
    `<li>${p.nom} — ${(p.snapshot_holistique.portrait || {}).archetype || "?"} (zone: ${p.zone_actuelle || "aucune"})</li>`
  ).join("");
}
```

with:

```javascript
async function chargerPersonnages() {
  const r = await fetch("/personnages", {headers: entetes()});
  const items = await r.json();
  document.getElementById("listePersonnages").innerHTML = items.map(p => {
    const bonus = p.bonus_idle_actuel > 0
      ? ` — +${p.bonus_idle_actuel} vers la prochaine étape (voie d'archétype)` : "";
    return `<li>${p.nom} — ${(p.snapshot_holistique.portrait || {}).archetype || "?"} (zone: ${p.zone_actuelle || "aucune"})${bonus}</li>`;
  }).join("");
}
```

Then, right after the `chargerPersonnages();` / `chargerZones();` calls at the very end of the `<script>` block, add:

```javascript
if (cleApi) {
  setInterval(() => fetch("/presence", {method: "POST", headers: entetes()}), 30_000);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/jeu-factions && python -m pytest test_front.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures — this is the final task, so also confirm the total test count grew by 1 (front) + 4 (api) + 2 (groupes) + 3 (calculer_resolution) + 5 (bonus_idle) + 5 (stockage) = 20 new tests versus the pre-plan baseline.

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/front.html briques/jeu-factions/test_front.py
git commit -m "feat(jeu-factions): front — heartbeat de présence + affichage du bonus idle (S216)"
```
