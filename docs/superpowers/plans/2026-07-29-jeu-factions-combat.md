# Brique `jeu-factions` — moteur de combat temps réel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la résolution automatique des zones de signe de `jeu-factions` (port 6210, brique déjà livrée) par du combat 2D temps réel joué — déplacement, sorts, cooldowns, mobs/boss — exactement per `docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md`.

**Architecture:** Nouveaux modules dans la brique existante (pas de nouvelle brique) : `combat_moteur.py` (cœur de simulation PUR, zéro I/O, testable sans WebSocket), `combat.py` (orchestration asyncio : sharding d'instances, cycle de vie, persistance des événements), `mobs.py` (seed des mobs/boss par zone), une route `@app.websocket` dans `main.py`, et un nouveau front `front_combat.html` (Phaser 3 via CDN, sans build).

**Tech Stack:** Python 3.12, FastAPI (WebSocket natif), SQLite (stdlib `sqlite3`), pytest + `TestClient` (websocket_connect) + `pytest-asyncio`, Phaser 3 (CDN), Docker.

## Global Constraints

- Ne touche à rien d'autre que `briques/jeu-factions/` — brique déjà en prod, aucune nouvelle dépendance serveur (Phaser est un CDN front pur, `requirements.txt` ne change pas).
- `combat_moteur.py` ne fait AUCUN I/O (pas de DB, pas de réseau, pas d'horloge système lue en interne) — `dt`/`horodatage` sont toujours des paramètres, jamais `time.monotonic()` appelé à l'intérieur.
- 100 % PvE, pas de PvP (cf. spec, Non-objectifs).
- Sharding : `JEU_FACTIONS_INSTANCE_CAPACITE` (défaut 30) joueurs max par instance de zone.
- Tick de simulation : `COMBAT_TICK_HZ` (défaut 10 Hz). Instance vide fermée après `COMBAT_INSTANCE_GRACE_S` (défaut 30s). Boss respawn après `COMBAT_BOSS_RESPAWN_S` (défaut 60s). Arène : `COMBAT_ARENE_TAILLE` unités (défaut 800), carrée.
- Auth WebSocket : clé en **query param** `api_key` (jamais en en-tête — le `WebSocket` natif du navigateur ne permet pas d'en-têtes personnalisés), même validation que la dépendance `cle_api` existante (Header) pour les routes HTTP.
- `zones.resoudre_toutes_zones()` disparaît : les zones de signe ne sont plus résolues passivement au tick. `tick.py` continue de résoudre les **groupes/archétypes** (hors scope de ce plan).
- Discipline de connexion SQLite déjà en place dans le repo (voir `zones.py`/`groupes.py`) : chaque fonction ouvre sa **propre** connexion courte (`with S._conn() as c:`), jamais de connexion tenue ouverte en travers d'un appel à une autre fonction qui ouvre la sienne (sinon `database is locked`). Respecter ce motif dans tout nouveau code touchant la DB.
- Comme pour `tick.boucle_tick()` (déjà dans le repo, jamais unit-testé — seul `executer_tick()` l'est), la boucle réelle `combat._boucle_instance()` (vrai `asyncio.sleep` en temps réel) n'est **pas** unit-testée directement ; ses briques constitutives (`rejoindre`, `quitter`, `un_tick`, `instance_expiree`) le sont individuellement. Un nouveau flag test-only `JEU_FACTIONS_COMBAT_AUTOSTART=0` (mirroir de `JEU_FACTIONS_TICK_AUTOSTART` déjà dans le repo, posé dans `conftest.py`) empêche la vraie boucle de démarrer pendant les tests API/WebSocket — sans lui, une tâche `asyncio` réelle fuirait entre tests et écrirait sur une DB SQLite que `conftest.py` supprime avant le test suivant.

---

## File Structure

```
briques/jeu-factions/
  stockage.py          — MODIFIÉ : + table mobs_zone, migration colonnes effet de competences
  mobs.py               — NOUVEAU : seed mobs/boss par zone
  archetypes.py         — MODIFIÉ : seed_competences() pose désormais un effet réel
  combat_moteur.py       — NOUVEAU : cœur de simulation PUR (avancer_tick)
  combat.py              — NOUVEAU : orchestration asyncio (instances, sharding, persistance)
  zones.py               — MODIFIÉ : + marquer_vaincue_si_premiere_fois, ajouter_score ;
                            resoudre_toutes_zones/calculer_resolution RETIRÉS (Task 6) ;
                            _signe_personnage renommé signe_personnage (public)
  tick.py                 — MODIFIÉ : ne résout plus les zones (Task 6)
  main.py                  — MODIFIÉ : startup seed mobs, route WebSocket, route front_combat.html
  front_combat.html         — NOUVEAU : client Phaser 3 (CDN, sans build)
  front.html                 — MODIFIÉ : lien « Rejoindre le combat » par zone
  docker-compose.yml          — MODIFIÉ : nouvelles variables d'env, retrait STATS_ZONE_SIGNE
  manifest.json                — MODIFIÉ : description + offre
  conftest.py                   — MODIFIÉ : JEU_FACTIONS_COMBAT_AUTOSTART=0, fixture vide-instances
  test_mobs.py                   — NOUVEAU
  test_stockage.py                — MODIFIÉ : test de migration
  test_archetypes.py               — MODIFIÉ : test des effets seedés
  test_combat_moteur.py             — NOUVEAU
  test_combat.py                     — NOUVEAU
  test_zones.py                       — MODIFIÉ : tests de l'ancienne résolution retirés/remplacés
  test_tick.py                         — MODIFIÉ : le tick ne résout plus les zones
  test_api.py                           — MODIFIÉ : tests WebSocket
  test_front_combat.py                   — NOUVEAU
```

---

### Task 1: Table `mobs_zone` + seed (`mobs.py`)

**Files:**
- Modify: `briques/jeu-factions/stockage.py`
- Modify: `briques/jeu-factions/main.py`
- Create: `briques/jeu-factions/mobs.py`
- Test: `briques/jeu-factions/test_mobs.py`

**Interfaces:**
- Consumes: `stockage._conn` (existant).
- Produces: `mobs.seed_mobs() -> None`, `mobs.lister_mobs_zone(zone_id: str) -> list[dict]` (chaque dict : `id, zone_id, nom, role, pv_max, degats_attaque, cooldown_attaque_s, portee_aggro, portee_attaque`) — consommé par Task 3 (`combat_moteur.nouvel_etat_instance`) et Task 5 (route WebSocket).

- [ ] **Step 1: Write the failing test**

```python
# test_mobs.py
import mobs
import zones


def test_seed_mobs_cree_un_boss_et_deux_mobs_par_zone():
    zones.seed_zones()
    mobs.seed_mobs()
    une_zone = zones.lister_zones()[0]
    gabarits = mobs.lister_mobs_zone(une_zone["id"])
    assert len(gabarits) == 3
    assert sum(1 for g in gabarits if g["role"] == "boss") == 1
    assert sum(1 for g in gabarits if g["role"] == "mob") == 2


def test_seed_mobs_est_idempotent():
    zones.seed_zones()
    mobs.seed_mobs()
    mobs.seed_mobs()
    une_zone = zones.lister_zones()[0]
    assert len(mobs.lister_mobs_zone(une_zone["id"])) == 3


def test_lister_mobs_zone_inconnue_est_vide():
    assert mobs.lister_mobs_zone("inconnue") == []


def test_gabarits_ont_les_champs_attendus():
    zones.seed_zones()
    mobs.seed_mobs()
    une_zone = zones.lister_zones()[0]
    boss = next(g for g in mobs.lister_mobs_zone(une_zone["id"]) if g["role"] == "boss")
    for champ in ("id", "zone_id", "nom", "pv_max", "degats_attaque",
                 "cooldown_attaque_s", "portee_aggro", "portee_attaque"):
        assert champ in boss
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/jeu-factions && python -m pytest test_mobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobs'`.

- [ ] **Step 3: Add the `mobs_zone` table to `stockage.py`**

In `briques/jeu-factions/stockage.py`, add this `CREATE TABLE` call right after the `zones` table creation (inside `_conn()`, before `scores_zone_guilde`):

```python
    c.execute("""CREATE TABLE IF NOT EXISTS mobs_zone (
        id TEXT PRIMARY KEY, zone_id TEXT NOT NULL, nom TEXT NOT NULL, role TEXT NOT NULL,
        pv_max INTEGER NOT NULL, degats_attaque INTEGER NOT NULL,
        cooldown_attaque_s REAL NOT NULL, portee_aggro INTEGER NOT NULL,
        portee_attaque INTEGER NOT NULL)""")
```

- [ ] **Step 4: Write `mobs.py`**

```python
"""Mobs/boss de combat par zone de signe — données de seed (même motif que
`zones.ZONES_SEED`) : un boss + deux mobs de « trash » par zone. Voir
docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md."""
from __future__ import annotations

import uuid

import stockage as S

# (role, nom, pv_max, degats_attaque, cooldown_attaque_s, portee_aggro, portee_attaque)
GABARIT_BOSS = ("boss", "Gardien de la zone", 400, 12, 1.5, 250, 30)
GABARITS_MOBS = [
    ("mob", "Sentinelle", 60, 6, 1.0, 150, 25),
    ("mob", "Sentinelle", 60, 6, 1.0, 150, 25),
]


def seed_mobs() -> None:
    with S._conn() as c:
        zones_existantes = c.execute("SELECT id, nom FROM zones").fetchall()
        for zone in zones_existantes:
            existe = c.execute("SELECT 1 FROM mobs_zone WHERE zone_id=?", (zone["id"],)).fetchone()
            if existe:
                continue
            for role, nom, pv_max, degats, cooldown, aggro, portee in [GABARIT_BOSS, *GABARITS_MOBS]:
                nom_final = f"{nom} — {zone['nom']}" if role == "boss" else nom
                c.execute("""INSERT INTO mobs_zone (id, zone_id, nom, role, pv_max,
                             degats_attaque, cooldown_attaque_s, portee_aggro, portee_attaque)
                             VALUES (?,?,?,?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, zone["id"], nom_final, role, pv_max, degats,
                           cooldown, aggro, portee))


def _ligne_mob(r) -> dict:
    return {"id": r["id"], "zone_id": r["zone_id"], "nom": r["nom"], "role": r["role"],
            "pv_max": r["pv_max"], "degats_attaque": r["degats_attaque"],
            "cooldown_attaque_s": r["cooldown_attaque_s"], "portee_aggro": r["portee_aggro"],
            "portee_attaque": r["portee_attaque"]}


def lister_mobs_zone(zone_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute("SELECT * FROM mobs_zone WHERE zone_id=? ORDER BY role DESC",
                         (zone_id,)).fetchall()
    return [_ligne_mob(r) for r in rows]
```

- [ ] **Step 5: Wire the seed into `main.py` startup**

In `briques/jeu-factions/main.py`, add `import mobs` to the imports, and add `mobs.seed_mobs()` to `_seed_donnees_globales()`:

```python
import mobs
```

```python
@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
    mobs.seed_mobs()
    if os.getenv("JEU_FACTIONS_TICK_AUTOSTART", "1") != "0":
        asyncio.create_task(tick.boucle_tick())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_mobs.py -v`
Expected: PASS (4 tests). Also run `python -m pytest -v` (full suite) to confirm nothing else broke.

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions/mobs.py briques/jeu-factions/test_mobs.py \
       briques/jeu-factions/stockage.py briques/jeu-factions/main.py
git commit -m "feat(jeu-factions): mobs/boss de combat par zone (table + seed)"
```

---

### Task 2: Effets de compétences (migration + seed) sur `competences`

**Files:**
- Modify: `briques/jeu-factions/stockage.py`
- Modify: `briques/jeu-factions/archetypes.py`
- Test: `briques/jeu-factions/test_stockage.py`
- Test: `briques/jeu-factions/test_archetypes.py`

**Interfaces:**
- Consumes: `stockage._conn` (existant).
- Produces: colonnes `effet_type, magnitude, portee, cooldown_s` sur `competences` (nullable — une compétence seedée avant ce plan reste lisible avec `effet_type=None`), `archetypes.lister_toutes_competences_avec_effet() -> dict[str, dict]` (`{competence_id: {"effet_type", "magnitude", "portee", "cooldown_s"}}`, uniquement celles où `effet_type IS NOT NULL`) — consommé par Task 5 (chargé une fois par instance de combat, passé à `combat_moteur.avancer_tick`).

- [ ] **Step 1: Write the failing tests**

```python
# append to test_stockage.py
def test_migration_colonnes_effet_est_presente_et_idempotente():
    with S._conn() as c:
        colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    assert {"effet_type", "magnitude", "portee", "cooldown_s"} <= colonnes
    S._conn()  # rejouer la migration ne doit pas lever d'erreur (ALTER TABLE idempotent)
```

```python
# append to test_archetypes.py
def test_seed_competences_definit_un_effet_pour_chaque_etape():
    A.seed_zones_archetype()
    A.seed_competences()
    effets = A.lister_toutes_competences_avec_effet()
    assert len(effets) == 30  # 10 archétypes x 3 étapes
    assert all(e["effet_type"] in ("degats", "soin", "bouclier") for e in effets.values())
    assert all(isinstance(e["magnitude"], int) and e["magnitude"] > 0 for e in effets.values())


def test_seed_competences_est_idempotent_et_backfill_les_lignes_existantes():
    A.seed_zones_archetype()
    A.seed_competences()
    avant = A.lister_toutes_competences_avec_effet()
    A.seed_competences()
    apres = A.lister_toutes_competences_avec_effet()
    assert avant == apres


def test_seed_competences_backfill_une_ligne_deja_existante_sans_effet():
    A.seed_zones_archetype()
    # simule une compétence seedée AVANT ce plan (pas d'effet), motif déjà utilisé en
    # production sur le HP — le seed doit la compléter, pas la dupliquer.
    import stockage as S
    import uuid
    etape = A.lister_etapes("Le Sage Contemplatif")[0]
    with S._conn() as c:
        c.execute("""INSERT INTO competences (id, nom, texte, archetype, ordre_etape)
                     VALUES (?,?,?,?,?)""",
                  (uuid.uuid4().hex, "Compétence — ancienne", "texte", "Le Sage Contemplatif",
                   etape["ordre"]))
    A.seed_competences()
    effets = A.lister_toutes_competences_avec_effet()
    trouvee = [e for cid, e in effets.items()]
    assert any(e["effet_type"] == "degats" for e in trouvee)  # ordre 1 → degats
    # une seule ligne pour cette étape (pas de doublon inséré par-dessus l'ancienne)
    with S._conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM competences WHERE archetype=? AND ordre_etape=?",
                      ("Le Sage Contemplatif", etape["ordre"])).fetchone()["n"]
    assert n == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py test_archetypes.py -v -k "effet or migration"`
Expected: FAIL — `sqlite3.OperationalError: no such column: effet_type` (colonnes absentes) puis `AttributeError` sur `lister_toutes_competences_avec_effet`.

- [ ] **Step 3: Add the migration to `stockage.py`**

In `briques/jeu-factions/stockage.py`, add this function and call it right after the `competences` table creation inside `_conn()`:

```python
def _migrer_colonnes_effet_competences(c: sqlite3.Connection) -> None:
    """Ajoute les colonnes d'effet de compétence si absentes (brique déployée avant ce
    plan) — `ALTER TABLE` idempotent, vérifié via `PRAGMA table_info` (SQLite n'a pas
    d'`ADD COLUMN IF NOT EXISTS`)."""
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    for nom, type_sql in (("effet_type", "TEXT"), ("magnitude", "INTEGER"),
                          ("portee", "INTEGER"), ("cooldown_s", "REAL")):
        if nom not in colonnes:
            c.execute(f"ALTER TABLE competences ADD COLUMN {nom} {type_sql}")
```

```python
    c.execute("""CREATE TABLE IF NOT EXISTS competences (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, texte TEXT NOT NULL,
        archetype TEXT NOT NULL, ordre_etape INTEGER NOT NULL)""")
    _migrer_colonnes_effet_competences(c)
```

- [ ] **Step 4: Update `seed_competences()` in `archetypes.py`**

Replace the existing `seed_competences()` function with:

```python
EFFETS_PAR_ETAPE: dict[int, dict] = {
    1: {"effet_type": "degats", "magnitude": 20, "portee": 120, "cooldown_s": 3.0},
    2: {"effet_type": "soin", "magnitude": 15, "portee": 100, "cooldown_s": 6.0},
    3: {"effet_type": "bouclier", "magnitude": 30, "portee": 80, "cooldown_s": 10.0},
}


def seed_competences() -> None:
    with S._conn() as c:
        etapes = c.execute("SELECT * FROM zones_archetype").fetchall()
        for e in etapes:
            effet = EFFETS_PAR_ETAPE[e["ordre"]]
            existe = c.execute(
                "SELECT id, effet_type FROM competences WHERE archetype=? AND ordre_etape=?",
                (e["archetype"], e["ordre"])).fetchone()
            if existe:
                if existe["effet_type"] is None:
                    c.execute("""UPDATE competences
                                 SET effet_type=?, magnitude=?, portee=?, cooldown_s=?
                                 WHERE id=?""",
                              (effet["effet_type"], effet["magnitude"], effet["portee"],
                               effet["cooldown_s"], existe["id"]))
                continue
            c.execute("""INSERT INTO competences
                         (id, nom, texte, archetype, ordre_etape, effet_type, magnitude,
                          portee, cooldown_s)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (uuid.uuid4().hex, f"Compétence — {e['nom']}",
                       f"Débloquée en achevant « {e['nom']} ». "
                       f"Effet : {effet['effet_type']} ({effet['magnitude']}).",
                       e["archetype"], e["ordre"], effet["effet_type"], effet["magnitude"],
                       effet["portee"], effet["cooldown_s"]))


def lister_toutes_competences_avec_effet() -> dict[str, dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT id, effet_type, magnitude, portee, cooldown_s FROM competences "
            "WHERE effet_type IS NOT NULL").fetchall()
    return {r["id"]: {"effet_type": r["effet_type"], "magnitude": r["magnitude"],
                      "portee": r["portee"], "cooldown_s": r["cooldown_s"]} for r in rows}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py test_archetypes.py -v`
Expected: PASS (all tests in both files, including pre-existing ones).

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/stockage.py briques/jeu-factions/archetypes.py \
       briques/jeu-factions/test_stockage.py briques/jeu-factions/test_archetypes.py
git commit -m "feat(jeu-factions): effets réels des compétences (migration + seed)"
```

---

### Task 3: Cœur de simulation pur (`combat_moteur.py`)

**Files:**
- Create: `briques/jeu-factions/combat_moteur.py`
- Test: `briques/jeu-factions/test_combat_moteur.py`

**Interfaces:**
- Consumes: nothing (pure module — takes plain dicts shaped like `mobs.lister_mobs_zone()` output and `archetypes.lister_toutes_competences_avec_effet()` output as parameters).
- Produces: `combat_moteur.nouvel_etat_instance(zone_id, arene_taille, mobs_zone) -> dict`, `combat_moteur.ajouter_joueur(etat, personnage_id, element, signe) -> dict`, `combat_moteur.retirer_joueur(etat, personnage_id) -> dict`, `combat_moteur.avancer_tick(etat, actions, dt, competences, horodatage, respawn_delai_s) -> tuple[dict, list[dict]]` — all consumed by Task 4 (`combat.py`).

- [ ] **Step 1: Write the failing tests**

```python
# test_combat_moteur.py
import combat_moteur as CM

MOB_ZONE = [{"id": "boss-1", "nom": "Boss", "role": "boss", "pv_max": 50,
            "degats_attaque": 5, "cooldown_attaque_s": 1.0, "portee_aggro": 200,
            "portee_attaque": 20}]

COMPETENCE_DEGATS = {"sort-degats": {"effet_type": "degats", "magnitude": 30,
                                     "portee": 100, "cooldown_s": 2.0}}
COMPETENCE_SOIN = {"sort-soin": {"effet_type": "soin", "magnitude": 15,
                                 "portee": 100, "cooldown_s": 5.0}}
COMPETENCE_BOUCLIER = {"sort-bouclier": {"effet_type": "bouclier", "magnitude": 20,
                                         "portee": 100, "cooldown_s": 5.0}}
COMPETENCE_ETOURDI = {"sort-etourdi": {"effet_type": "etourdissement", "magnitude": 3.0,
                                       "portee": 100, "cooldown_s": 8.0}}
COMPETENCE_DOT = {"sort-dot": {"effet_type": "dot", "magnitude": 10,
                               "portee": 100, "cooldown_s": 8.0}}


def _etat_avec_joueur():
    etat = CM.nouvel_etat_instance("zone-1", 800, MOB_ZONE)
    return CM.ajouter_joueur(etat, "p1", "Feu", "Bélier")


def _joueur_colle_au_mob(etat, mob_id, pid="p1"):
    etat["joueurs"][pid]["x"] = etat["mobs"][mob_id]["x"]
    etat["joueurs"][pid]["y"] = etat["mobs"][mob_id]["y"]
    return etat


def test_nouvel_etat_instance_place_le_boss_au_centre():
    etat = CM.nouvel_etat_instance("zone-1", 800, MOB_ZONE)
    mob_id = next(iter(etat["mobs"]))
    assert etat["mobs"][mob_id]["x"] == 400
    assert etat["mobs"][mob_id]["y"] == 400
    assert etat["mobs"][mob_id]["role"] == "boss"


def test_ajouter_puis_retirer_joueur():
    etat = _etat_avec_joueur()
    assert "p1" in etat["joueurs"]
    etat = CM.retirer_joueur(etat, "p1")
    assert "p1" not in etat["joueurs"]


def test_deplacement_borne_par_larene():
    etat = _etat_avec_joueur()
    actions = [{"type": "deplacement", "personnage_id": "p1", "direction": {"x": -1, "y": -1}}]
    etat, _ = CM.avancer_tick(etat, actions, dt=10.0, competences={}, horodatage=0.0,
                              respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["x"] == 0
    assert etat["joueurs"]["p1"]["y"] == 0


def test_sort_hors_de_portee_est_un_noop():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat["joueurs"]["p1"]["x"], etat["joueurs"]["p1"]["y"] = 0, 0
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, evenements = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                                       horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 50
    assert evenements == []


def test_degats_appliques_et_mob_tue():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 20
    # cooldown décrémenté par `dt`, pas par l'écart de `horodatage` — dt=3.0 simule les 3s
    # écoulées (un vrai appelant à fréquence fixe a toujours dt == l'écart entre horodatages)
    etat, ev2 = CM.avancer_tick(etat, actions, dt=3.0, competences=COMPETENCE_DEGATS,
                                horodatage=3.0, respawn_delai_s=60.0)
    assert mob_id not in etat["mobs"]
    mort = next(e for e in ev2 if e["type"] == "boss_tue")
    assert mort["contributions"] == {"Bélier": 50}


def test_cooldown_bloque_la_reutilisation_immediate():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 20
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.5, respawn_delai_s=60.0)  # cooldown 2s pas écoulé
    assert etat["mobs"][mob_id]["pv"] == 20


def test_plusieurs_sorts_au_meme_tick_dans_lordre():
    # pv_max relevé à 200 (au lieu des 50 de MOB_ZONE) : deux sorts à 30 dégâts dans le même
    # tick totalisent 60 — avec pv_max=50 le mob mourrait et disparaîtrait de `etat["mobs"]`
    # avant qu'on puisse lire `degats_recus_par_guilde` dessus.
    mob_zone_resistant = [{**MOB_ZONE[0], "pv_max": 200}]
    etat = CM.nouvel_etat_instance("zone-1", 800, mob_zone_resistant)
    etat = CM.ajouter_joueur(etat, "p1", "Feu", "Bélier")
    etat = CM.ajouter_joueur(etat, "p2", "Eau", "Cancer")
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id, "p1")
    etat = _joueur_colle_au_mob(etat, mob_id, "p2")
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats", "cible_id": mob_id},
              {"type": "sort", "personnage_id": "p2", "competence_id": "sort-degats", "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {"Bélier": 30, "Cancer": 20}


def test_mob_nattaque_que_dans_sa_portee_daggro():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat["mobs"][mob_id]["portee_aggro"] = 10
    etat["joueurs"]["p1"]["x"], etat["joueurs"]["p1"]["y"] = 0, 0  # loin du boss (400,400)
    etat, _ = CM.avancer_tick(etat, [], dt=1.0, competences={}, horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["cible_id"] is None
    assert etat["joueurs"]["p1"]["pv"] == 100


def test_effet_soin_augmente_les_pv():
    etat = _etat_avec_joueur()
    etat["joueurs"]["p1"]["pv"] = 50
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-soin", "cible_id": "p1"}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_SOIN,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["pv"] == 65


def test_effet_bouclier_absorbe_les_degats_suivants():
    # NE PAS coller le joueur au mob avant ce premier tick : phase 3 (sorts) et phase 5 (IA
    # des mobs) tournent dans le MÊME appel — un mob déjà à portée attaquerait sur ce tick-là
    # aussi, avant même l'assertion sur le bouclier fraîchement posé.
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-bouclier", "cible_id": "p1"}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_BOUCLIER,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["bouclier"] == 20
    etat = _joueur_colle_au_mob(etat, mob_id)
    # le boss (degats_attaque=5, cooldown_restant=0, joueur maintenant dans sa portee_attaque) attaque :
    etat, _ = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=1.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["pv"] == 100  # entièrement absorbé
    assert etat["joueurs"]["p1"]["bouclier"] == 15


def test_effet_etourdissement_empeche_le_mob_dattaquer():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-etourdi",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_ETOURDI,
                              horodatage=0.0, respawn_delai_s=60.0)
    etat, _ = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=1.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["pv"] == 100  # le mob était étourdi, n'a pas pu attaquer


def test_effet_dot_inflige_des_degats_dans_la_duree():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-dot",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DOT,
                              horodatage=0.0, respawn_delai_s=60.0)
    etat, _ = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=1.0, respawn_delai_s=60.0)
    # le DOT s'applique dès le tick où il est posé (phase 4 tourne juste après la phase 3
    # sorts, dans le même appel) — 50 - 1 (tick de lancer) - 1 (tick suivant) = 48
    assert etat["mobs"][mob_id]["pv"] == 48


def test_boss_respawn_apres_le_delai():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat["mobs"][mob_id]["pv"] = 0
    etat, ev1 = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=0.0, respawn_delai_s=5.0)
    assert any(e["type"] == "boss_tue" for e in ev1)
    assert not any(m["role"] == "boss" for m in etat["mobs"].values())
    etat, ev2 = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=2.0, respawn_delai_s=5.0)
    assert not any(m["role"] == "boss" for m in etat["mobs"].values())  # trop tôt
    etat, ev3 = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=6.0, respawn_delai_s=5.0)
    assert any(m["role"] == "boss" for m in etat["mobs"].values())
    assert any(e["type"] == "boss_reapparu" for e in ev3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_combat_moteur.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'combat_moteur'`.

- [ ] **Step 3: Write `combat_moteur.py`**

```python
"""Cœur de simulation du combat temps réel — fonction PURE, zéro I/O (pas de DB, pas de
réseau, pas d'horloge système lue directement : `dt`/`horodatage` sont des paramètres,
jamais `time.monotonic()` appelé ici). Testable en pytest sans WebSocket ni asyncio réel.
Voir docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md."""
from __future__ import annotations

import math

VITESSE_JOUEUR = 120.0   # unités d'arène / seconde
VITESSE_MOB = 60.0
PV_MAX_JOUEUR = 100       # V1 : fixe, pas dérivé des stats holistiques (hors scope du spec)
DUREE_DOT_S = 5.0         # le spec ne définit pas de colonne « durée » pour les DOT (V1 fixe)

_CIBLE_MOB = {"degats", "etourdissement", "dot"}
_CIBLE_JOUEUR = {"soin", "bouclier"}


def _instancier_mob(gabarit: dict, x: float, y: float) -> dict:
    return {"template_id": gabarit["id"], "nom": gabarit["nom"], "role": gabarit["role"],
            "x": x, "y": y, "pv": gabarit["pv_max"], "pv_max": gabarit["pv_max"],
            "degats_attaque": gabarit["degats_attaque"],
            "cooldown_attaque_s": gabarit["cooldown_attaque_s"], "cooldown_restant": 0.0,
            "portee_aggro": gabarit["portee_aggro"], "portee_attaque": gabarit["portee_attaque"],
            "cible_id": None, "bouclier": 0, "etourdi_jusqua": 0.0, "dots": [],
            "degats_recus_par_guilde": {}}


def nouvel_etat_instance(zone_id: str, arene_taille: int, mobs_zone: list[dict]) -> dict:
    """`mobs_zone` = `mobs.lister_mobs_zone(zone_id)` (Task 1). Place le boss au centre, les
    autres mobs éparpillés en cercle autour."""
    centre = arene_taille / 2
    gabarit_boss = next((m for m in mobs_zone if m["role"] == "boss"), None)
    autres = [m for m in mobs_zone if m["role"] != "boss"]
    mobs: dict[str, dict] = {}
    for i, m in enumerate(autres):
        angle = (2 * math.pi * i) / max(len(autres), 1)
        rayon = arene_taille * 0.3
        mobs[f"{m['id']}-{i}"] = _instancier_mob(m, centre + rayon * math.cos(angle),
                                                  centre + rayon * math.sin(angle))
    if gabarit_boss:
        mobs[f"{gabarit_boss['id']}-boss"] = _instancier_mob(gabarit_boss, centre, centre)
    return {"zone_id": zone_id, "arene_taille": arene_taille, "joueurs": {}, "mobs": mobs,
            "_gabarit_boss": gabarit_boss, "boss_mort_horodatage": None}


def ajouter_joueur(etat: dict, personnage_id: str, element: str, signe: str) -> dict:
    bord = etat["arene_taille"] * 0.05
    etat["joueurs"][personnage_id] = {
        "x": bord, "y": bord, "pv": PV_MAX_JOUEUR, "pv_max": PV_MAX_JOUEUR,
        "element": element, "signe": signe, "etat": "actif",
        "cooldowns": {}, "bouclier": 0, "dots": [],
    }
    return etat


def retirer_joueur(etat: dict, personnage_id: str) -> dict:
    etat["joueurs"].pop(personnage_id, None)
    for m in etat["mobs"].values():
        if m["cible_id"] == personnage_id:
            m["cible_id"] = None
    return etat


def _distance(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _trouver_entite(etat: dict, entite_id: str) -> tuple[dict | None, str]:
    if entite_id in etat["joueurs"]:
        return etat["joueurs"][entite_id], "joueur"
    if entite_id in etat["mobs"]:
        return etat["mobs"][entite_id], "mob"
    return None, ""


def _infliger_degats(cible: dict, degats: float) -> float:
    """Absorbe d'abord via `bouclier`, puis réduit `pv` (jamais sous 0). Renvoie les PV
    réellement perdus (hors bouclier) — sert au calcul des contributions par guilde."""
    absorbe = min(cible.get("bouclier", 0), degats)
    cible["bouclier"] = cible.get("bouclier", 0) - absorbe
    reste = degats - absorbe
    avant = cible["pv"]
    cible["pv"] = max(0, cible["pv"] - reste)
    return avant - cible["pv"]


def avancer_tick(etat: dict, actions: list[dict], dt: float, competences: dict[str, dict],
                 horodatage: float, respawn_delai_s: float) -> tuple[dict, list[dict]]:
    """`competences` = {competence_id: {"effet_type", "magnitude", "portee", "cooldown_s"}}
    (chargé une fois par l'appelant — Task 5 — jamais lu depuis la DB ici). `actions` =
    [{"type": "deplacement"|"sort", "personnage_id", ...}]."""
    evenements: list[dict] = []

    # 1. Déplacement
    for a in actions:
        if a["type"] != "deplacement":
            continue
        j = etat["joueurs"].get(a["personnage_id"])
        if not j or j["etat"] != "actif":
            continue
        dx, dy = a["direction"].get("x", 0), a["direction"].get("y", 0)
        norme = math.hypot(dx, dy)
        if norme == 0:
            continue
        j["x"] = min(max(j["x"] + (dx / norme) * VITESSE_JOUEUR * dt, 0), etat["arene_taille"])
        j["y"] = min(max(j["y"] + (dy / norme) * VITESSE_JOUEUR * dt, 0), etat["arene_taille"])

    # 2. Cooldowns
    for j in etat["joueurs"].values():
        for cid in list(j["cooldowns"]):
            j["cooldowns"][cid] = max(0.0, j["cooldowns"][cid] - dt)
    for m in etat["mobs"].values():
        m["cooldown_restant"] = max(0.0, m["cooldown_restant"] - dt)

    # 3. Sorts
    for a in actions:
        if a["type"] != "sort":
            continue
        j = etat["joueurs"].get(a["personnage_id"])
        comp = competences.get(a.get("competence_id", ""))
        if not j or j["etat"] != "actif" or not comp or not comp.get("effet_type"):
            continue
        if j["cooldowns"].get(a["competence_id"], 0) > 0:
            continue
        cible, genre = _trouver_entite(etat, a.get("cible_id", ""))
        if cible is None:
            continue
        effet = comp["effet_type"]
        if effet in _CIBLE_MOB and genre != "mob":
            continue
        if effet in _CIBLE_JOUEUR and genre != "joueur":
            continue
        if _distance(j, cible) > comp["portee"]:
            continue
        j["cooldowns"][a["competence_id"]] = comp["cooldown_s"]
        if effet == "degats":
            reels = _infliger_degats(cible, comp["magnitude"])
            cible["degats_recus_par_guilde"][j["signe"]] = \
                cible["degats_recus_par_guilde"].get(j["signe"], 0) + reels
            evenements.append({"type": "mob_touche", "mob_id": a["cible_id"], "degats": reels})
        elif effet == "soin":
            cible["pv"] = min(cible["pv_max"], cible["pv"] + comp["magnitude"])
        elif effet == "bouclier":
            cible["bouclier"] = cible.get("bouclier", 0) + comp["magnitude"]
        elif effet == "etourdissement":
            cible["etourdi_jusqua"] = horodatage + comp["magnitude"]
        elif effet == "dot":
            cible.setdefault("dots", []).append(
                {"degats_par_seconde": comp["magnitude"], "expire_a": horodatage + DUREE_DOT_S,
                 "guilde": j["signe"]})

    # 4. DOT (joueurs et mobs)
    for entites in (etat["joueurs"], etat["mobs"]):
        for e in entites.values():
            actifs = []
            for d in e.get("dots", []):
                if horodatage >= d["expire_a"]:
                    continue
                reels = _infliger_degats(e, d["degats_par_seconde"] * dt)
                if "degats_recus_par_guilde" in e:
                    e["degats_recus_par_guilde"][d["guilde"]] = \
                        e["degats_recus_par_guilde"].get(d["guilde"], 0) + reels
                actifs.append(d)
            e["dots"] = actifs

    # 5. IA des mobs (aggro le plus proche dans sa portée, pas de pathfinding)
    joueurs_actifs = [(pid, j) for pid, j in etat["joueurs"].items() if j["etat"] == "actif"]
    for m in etat["mobs"].values():
        if horodatage < m.get("etourdi_jusqua", 0):
            continue
        cible_id, cible, meilleure_distance = None, None, None
        for pid, j in joueurs_actifs:
            d = _distance(m, j)
            if d <= m["portee_aggro"] and (meilleure_distance is None or d < meilleure_distance):
                cible_id, cible, meilleure_distance = pid, j, d
        m["cible_id"] = cible_id
        if cible is None:
            continue
        distance = _distance(m, cible)
        if distance > m["portee_attaque"]:
            dx, dy = cible["x"] - m["x"], cible["y"] - m["y"]
            norme = math.hypot(dx, dy) or 1
            m["x"] += (dx / norme) * VITESSE_MOB * dt
            m["y"] += (dy / norme) * VITESSE_MOB * dt
        elif m["cooldown_restant"] <= 0:
            m["cooldown_restant"] = m["cooldown_attaque_s"]
            reels = _infliger_degats(cible, m["degats_attaque"])
            evenements.append({"type": "joueur_touche", "personnage_id": cible_id, "degats": reels})
            if cible["pv"] <= 0 and cible["etat"] == "actif":
                cible["etat"] = "ko"
                evenements.append({"type": "joueur_ko", "personnage_id": cible_id})

    # 6. Morts de mobs (retrait + événement) + respawn du boss
    for mid in [mid for mid, m in etat["mobs"].items() if m["pv"] <= 0]:
        m = etat["mobs"].pop(mid)
        type_evenement = "boss_tue" if m["role"] == "boss" else "mob_tue"
        evenements.append({"type": type_evenement, "mob_id": mid,
                           "contributions": dict(m["degats_recus_par_guilde"])})
        if m["role"] == "boss":
            etat["boss_mort_horodatage"] = horodatage

    boss_present = any(m["role"] == "boss" for m in etat["mobs"].values())
    if (etat["boss_mort_horodatage"] is not None and not boss_present and etat["_gabarit_boss"]
            and horodatage - etat["boss_mort_horodatage"] >= respawn_delai_s):
        centre = etat["arene_taille"] / 2
        gabarit = etat["_gabarit_boss"]
        etat["mobs"][f"{gabarit['id']}-boss-{int(horodatage)}"] = \
            _instancier_mob(gabarit, centre, centre)
        etat["boss_mort_horodatage"] = None
        evenements.append({"type": "boss_reapparu"})

    return etat, evenements
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_combat_moteur.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/combat_moteur.py briques/jeu-factions/test_combat_moteur.py
git commit -m "feat(jeu-factions): cœur pur de simulation de combat (avancer_tick)"
```

---

### Task 4: Orchestration asyncio — sharding, cycle de vie, persistance (`combat.py`)

**Files:**
- Create: `briques/jeu-factions/combat.py`
- Modify: `briques/jeu-factions/zones.py`
- Modify: `briques/jeu-factions/conftest.py`
- Test: `briques/jeu-factions/test_combat.py`
- Test: `briques/jeu-factions/test_zones.py`

**Interfaces:**
- Consumes: `combat_moteur.*` (Task 3), `mobs.lister_mobs_zone` (Task 1), `stockage.log_resolution` (existant), `zones.marquer_vaincue_si_premiere_fois`, `zones.ajouter_score`, `zones.signe_personnage` (nouveaux/renommés dans ce Task).
- Produces: `combat.InstanceCombat` (classe), `combat.rejoindre(zone_id, personnage_id, element, signe, mobs_zone) -> InstanceCombat`, `combat.enregistrer_connexion(inst, personnage_id, websocket) -> None`, `combat.empiler_action(inst, personnage_id, message) -> None`, `combat.vider_actions(inst) -> list[dict]`, `combat.quitter(inst, personnage_id, horodatage) -> None`, `combat.instance_expiree(inst, horodatage) -> bool`, `combat.fermer_instance(inst) -> None`, `combat.un_tick(inst, actions, dt, competences, horodatage) -> list[dict]`, `combat.etat_public(inst) -> dict`, `combat.diffuser_etat(inst) -> None` (async), `combat.demarrer_boucle_si_necessaire(inst, competences) -> None`, `combat._INSTANCES: dict[str, list[InstanceCombat]]` — consommé par Task 5 (route WebSocket dans `main.py`).

- [ ] **Step 1: Add `marquer_vaincue_si_premiere_fois` / `ajouter_score` / rename `signe_personnage` in `zones.py`, write their failing tests**

```python
# append to test_zones.py
def test_marquer_vaincue_si_premiere_fois():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    assert Z.marquer_vaincue_si_premiere_fois(zid) is True
    assert Z.lire_zone(zid)["etat"] == "vaincue"
    assert Z.marquer_vaincue_si_premiere_fois(zid) is False  # déjà vaincue, pas de re-déclenchement


def test_ajouter_score_cumule_par_guilde():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    Z.ajouter_score(zid, "Bélier", 30)
    Z.ajouter_score(zid, "Bélier", 20)
    Z.ajouter_score(zid, "Lion", 5)
    scores = {s["guilde"]: s["points_cumules"] for s in Z.lire_zone(zid)["scores"]}
    assert scores == {"Bélier": 50, "Lion": 5}


def test_ajouter_score_ignore_les_points_a_zero():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    Z.ajouter_score(zid, "Bélier", 0)
    assert Z.lire_zone(zid)["scores"] == []


def test_signe_personnage_lit_le_snapshot():
    assert Z.signe_personnage({"traditions": {"signe_solaire": {"nom": "Lion"}}}) == "Lion"
    assert Z.signe_personnage({}) is None
```

Also replace the now-outdated `test_lire_zone_scores_reflete_la_resolution` (which calls
`resoudre_toutes_zones`, still present at this point but about to be removed in Task 6) with:

```python
def test_lire_zone_scores_reflete_ajouter_score():
    Z.seed_zones()
    belier = next(z for z in Z.lister_zones() if z["signe_natif"] == "Bélier")
    Z.ajouter_score(belier["id"], "Bélier", 400)
    z = Z.lire_zone(belier["id"])
    assert z["scores"] == [{"guilde": "Bélier", "points_cumules": 400}]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd briques/jeu-factions && python -m pytest test_zones.py -v -k "vaincue_si_premiere or ajouter_score or signe_personnage"`
Expected: FAIL — `AttributeError` on the three new names.

- [ ] **Step 3: Add the functions to `zones.py`**

Rename `_signe_personnage` to `signe_personnage` (drop the underscore — it becomes a
shared utility used by `combat.py`, not just `resoudre_toutes_zones`'s internals):

```python
# was: def _signe_personnage(snapshot: dict) -> str | None:
def signe_personnage(snapshot: dict) -> str | None:
    return ((snapshot.get("traditions") or {}).get("signe_solaire") or {}).get("nom")
```

Update its one call site, inside `resoudre_toutes_zones`:

```python
# was: signe = _signe_personnage(snap)
signe = signe_personnage(snap)
```

Then append:

```python
def marquer_vaincue_si_premiere_fois(zone_id: str) -> bool:
    with S._conn() as c:
        cur = c.execute("UPDATE zones SET etat='vaincue' WHERE id=? AND etat='en_cours'", (zone_id,))
        return cur.rowcount > 0


def ajouter_score(zone_id: str, guilde: str, points: float) -> None:
    if points <= 0:
        return
    with S._conn() as c:
        c.execute("""INSERT INTO scores_zone_guilde (zone_id, guilde, points_cumules)
                     VALUES (?,?,?)
                     ON CONFLICT(zone_id, guilde) DO UPDATE SET
                     points_cumules = points_cumules + excluded.points_cumules""",
                  (zone_id, guilde, int(points)))
```

- [ ] **Step 4: Run to verify the `zones.py` tests pass**

Run: `cd briques/jeu-factions && python -m pytest test_zones.py -v`
Expected: PASS (all tests, including the replaced one — `resoudre_toutes_zones` itself is untouched at this point, still present, still tested until Task 6).

- [ ] **Step 5: Write the failing `combat.py` tests**

```python
# test_combat.py
import combat
import mobs
import zones


def _mobs_zone_fixture():
    zones.seed_zones()
    mobs.seed_mobs()
    zone = zones.lister_zones()[0]
    return zone["id"], mobs.lister_mobs_zone(zone["id"])


async def test_rejoindre_cree_une_instance_et_y_ajoute_le_joueur():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    assert "p1" in inst.etat["joueurs"]
    assert inst.zone_id == zone_id


async def test_rejoindre_reutilise_linstance_ouverte():
    zone_id, gabarits = _mobs_zone_fixture()
    inst1 = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    inst2 = await combat.rejoindre(zone_id, "p2", "Eau", "Cancer", gabarits)
    assert inst1.id == inst2.id


async def test_rejoindre_cree_une_nouvelle_instance_une_fois_pleine(monkeypatch):
    monkeypatch.setenv("JEU_FACTIONS_INSTANCE_CAPACITE", "1")
    zone_id, gabarits = _mobs_zone_fixture()
    inst1 = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    combat.enregistrer_connexion(inst1, "p1", object())
    inst2 = await combat.rejoindre(zone_id, "p2", "Eau", "Cancer", gabarits)
    assert inst1.id != inst2.id


async def test_quitter_retire_le_joueur_et_marque_linstance_vide():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    combat.enregistrer_connexion(inst, "p1", object())
    combat.quitter(inst, "p1", horodatage=100.0)
    assert "p1" not in inst.etat["joueurs"]
    assert inst.derniere_activite == 100.0


async def test_instance_expiree_apres_le_delai_de_grace(monkeypatch):
    monkeypatch.setenv("COMBAT_INSTANCE_GRACE_S", "30")
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    combat.enregistrer_connexion(inst, "p1", object())
    combat.quitter(inst, "p1", horodatage=100.0)
    assert not combat.instance_expiree(inst, horodatage=110.0)
    assert combat.instance_expiree(inst, horodatage=131.0)


async def test_fermer_instance_la_retire_du_registre():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    assert inst in combat._INSTANCES[zone_id]
    combat.fermer_instance(inst)
    assert inst not in combat._INSTANCES[zone_id]


async def test_un_tick_applique_la_simulation_pure():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    x_avant = inst.etat["joueurs"]["p1"]["x"]
    actions = [{"type": "deplacement", "personnage_id": "p1", "direction": {"x": 1, "y": 0}}]
    await combat.un_tick(inst, actions, dt=1.0, competences={}, horodatage=0.0)
    assert inst.etat["joueurs"]["p1"]["x"] > x_avant


async def test_un_tick_persiste_la_victoire_de_zone_a_la_mort_du_boss():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    inst.etat["mobs"][boss_id]["pv"] = 0
    inst.etat["mobs"][boss_id]["degats_recus_par_guilde"] = {"Bélier": 400}
    evenements = await combat.un_tick(inst, [], dt=0.1, competences={}, horodatage=0.0)
    assert any(e["type"] == "boss_tue" for e in evenements)
    assert zones.lire_zone(zone_id)["etat"] == "vaincue"
    scores = {s["guilde"]: s["points_cumules"] for s in zones.lire_zone(zone_id)["scores"]}
    assert scores["Bélier"] == 400
```

- [ ] **Step 6: Add the autouse fixture and the test-only autostart flag to `conftest.py`**

```python
# add to conftest.py, alongside the existing os.environ["JEU_FACTIONS_TICK_AUTOSTART"] line
os.environ["JEU_FACTIONS_COMBAT_AUTOSTART"] = "0"    # jamais de vraie boucle temps réel en test
```

```python
@pytest.fixture(autouse=True)
def _vider_instances_combat():
    import combat
    combat._INSTANCES.clear()
    yield
    combat._INSTANCES.clear()
```

- [ ] **Step 7: Run to verify failure**

Run: `cd briques/jeu-factions && python -m pytest test_combat.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'combat'`.

- [ ] **Step 8: Write `combat.py`**

```python
"""Orchestration asyncio du combat temps réel : sharding des instances par zone, cycle de
vie (jointure/départ/fermeture après grâce), et persistance des événements de simulation
(le seul point de contact entre `combat_moteur.py` — pur — et la DB). Voir
docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import combat_moteur as CM
import stockage
import zones


def capacite() -> int:
    return int(os.getenv("JEU_FACTIONS_INSTANCE_CAPACITE", "30"))


def arene_taille() -> int:
    return int(os.getenv("COMBAT_ARENE_TAILLE", "800"))


def tick_hz() -> float:
    return float(os.getenv("COMBAT_TICK_HZ", "10"))


def grace_s() -> float:
    return float(os.getenv("COMBAT_INSTANCE_GRACE_S", "30"))


def respawn_delai_s() -> float:
    return float(os.getenv("COMBAT_BOSS_RESPAWN_S", "60"))


@dataclass
class InstanceCombat:
    id: str
    zone_id: str
    etat: dict
    connexions: dict = field(default_factory=dict)     # personnage_id -> WebSocket
    file_actions: list = field(default_factory=list)   # actions en attente du prochain tick
    derniere_activite: float | None = None              # horodatage depuis lequel vide
    tache: asyncio.Task | None = None


_INSTANCES: dict[str, list[InstanceCombat]] = {}


def _instance_disponible(zone_id: str) -> InstanceCombat | None:
    for inst in _INSTANCES.get(zone_id, []):
        if len(inst.connexions) < capacite():
            return inst
    return None


def _creer_instance(zone_id: str, mobs_zone: list[dict]) -> InstanceCombat:
    import uuid
    etat = CM.nouvel_etat_instance(zone_id, arene_taille(), mobs_zone)
    inst = InstanceCombat(id=uuid.uuid4().hex, zone_id=zone_id, etat=etat)
    _INSTANCES.setdefault(zone_id, []).append(inst)
    return inst


async def rejoindre(zone_id: str, personnage_id: str, element: str, signe: str,
                    mobs_zone: list[dict]) -> InstanceCombat:
    inst = _instance_disponible(zone_id) or _creer_instance(zone_id, mobs_zone)
    inst.etat = CM.ajouter_joueur(inst.etat, personnage_id, element, signe)
    inst.derniere_activite = None
    return inst


def enregistrer_connexion(inst: InstanceCombat, personnage_id: str, websocket) -> None:
    inst.connexions[personnage_id] = websocket


def empiler_action(inst: InstanceCombat, personnage_id: str, message: dict) -> None:
    action = dict(message)
    action["personnage_id"] = personnage_id
    inst.file_actions.append(action)


def vider_actions(inst: InstanceCombat) -> list[dict]:
    actions, inst.file_actions = inst.file_actions, []
    return actions


def quitter(inst: InstanceCombat, personnage_id: str, horodatage: float) -> None:
    inst.etat = CM.retirer_joueur(inst.etat, personnage_id)
    inst.connexions.pop(personnage_id, None)
    if not inst.connexions:
        inst.derniere_activite = horodatage


def instance_expiree(inst: InstanceCombat, horodatage: float) -> bool:
    return (not inst.connexions and inst.derniere_activite is not None
            and horodatage - inst.derniere_activite >= grace_s())


def fermer_instance(inst: InstanceCombat) -> None:
    if inst.tache:
        inst.tache.cancel()
    liste = _INSTANCES.get(inst.zone_id, [])
    if inst in liste:
        liste.remove(inst)


def persister_evenements(zone_id: str, evenements: list[dict]) -> None:
    for ev in evenements:
        if ev["type"] in ("mob_tue", "boss_tue"):
            for guilde, points in ev.get("contributions", {}).items():
                zones.ajouter_score(zone_id, guilde, points)
            stockage.log_resolution(zone_id, None, ev.get("contributions", {}), ev["type"])
        if ev["type"] == "boss_tue":
            zones.marquer_vaincue_si_premiere_fois(zone_id)


async def un_tick(inst: InstanceCombat, actions: list[dict], dt: float,
                  competences: dict[str, dict], horodatage: float) -> list[dict]:
    inst.etat, evenements = CM.avancer_tick(inst.etat, actions, dt, competences, horodatage,
                                            respawn_delai_s())
    persister_evenements(inst.zone_id, evenements)
    return evenements


def etat_public(inst: InstanceCombat) -> dict:
    return {"instance_id": inst.id, "zone_id": inst.zone_id,
            "joueurs": inst.etat["joueurs"], "mobs": inst.etat["mobs"]}


async def diffuser_etat(inst: InstanceCombat) -> None:
    message = {"type": "etat", **etat_public(inst)}
    deconnectes = []
    for personnage_id, ws in inst.connexions.items():
        try:
            await ws.send_json(message)
        except Exception:
            deconnectes.append(personnage_id)
    for personnage_id in deconnectes:
        inst.connexions.pop(personnage_id, None)


def demarrer_boucle_si_necessaire(inst: InstanceCombat, competences: dict[str, dict]) -> None:
    if inst.tache is not None:
        return
    if os.getenv("JEU_FACTIONS_COMBAT_AUTOSTART", "1") == "0":
        return
    inst.tache = asyncio.create_task(_boucle_instance(inst, competences))


async def _boucle_instance(inst: InstanceCombat, competences: dict[str, dict]) -> None:
    dt = 1.0 / tick_hz()
    while True:
        await asyncio.sleep(dt)
        actions = vider_actions(inst)
        await un_tick(inst, actions, dt, competences, time.monotonic())
        await diffuser_etat(inst)
        if instance_expiree(inst, time.monotonic()):
            fermer_instance(inst)
            return
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_combat.py test_zones.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add briques/jeu-factions/combat.py briques/jeu-factions/zones.py \
       briques/jeu-factions/conftest.py briques/jeu-factions/test_combat.py \
       briques/jeu-factions/test_zones.py
git commit -m "feat(jeu-factions): orchestration asyncio du combat (sharding + persistance)"
```

---

### Task 5: Route WebSocket (`main.py`)

**Files:**
- Modify: `briques/jeu-factions/main.py`
- Test: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Consumes: `combat.rejoindre`, `combat.enregistrer_connexion`, `combat.empiler_action`, `combat.etat_public`, `combat.demarrer_boucle_si_necessaire`, `combat.quitter`, `combat._INSTANCES` (Task 4) ; `archetypes.lister_toutes_competences_avec_effet` (Task 2) ; `mobs.lister_mobs_zone` (Task 1) ; `zones.signe_personnage`, `zones.ZONES_SEED` (Task 4/existant).
- Produces: `WS /zones/{zone_id}/combat?personnage_id=<id>&api_key=<clé>`.

- [ ] **Step 1: Write the failing tests**

```python
# append to test_api.py
import combat
import mobs


def test_combat_ws_rejette_une_cle_invalide(monkeypatch):
    import main
    main.API_KEYS = {"bonnecle"}
    try:
        with client.websocket_connect(
                "/zones/inconnue/combat?personnage_id=x&api_key=mauvaise") as ws:
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message["code"] == 4401
    finally:
        main.API_KEYS = set()


def test_combat_ws_zone_ou_personnage_inconnu_est_rejete():
    with client.websocket_connect(
            "/zones/inconnue/combat?personnage_id=inconnu&api_key=") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_ws_connexion_valide_recoit_un_etat_initial(monkeypatch):
    _patch_moteur(monkeypatch)
    zones.seed_zones()
    mobs.seed_mobs()
    r = client.post("/personnages", json={"nom": "Combattant", "date_naissance": "1990-01-01"})
    pid = r.json()["id"]
    zone_id = zones.lister_zones()[0]["id"]
    with client.websocket_connect(f"/zones/{zone_id}/combat?personnage_id={pid}") as ws:
        premier = ws.receive_json()
        assert premier["type"] == "etat"
        assert pid in premier["joueurs"]
    instance = combat._INSTANCES[zone_id][0]
    assert pid not in instance.etat["joueurs"]  # retiré à la déconnexion (finally du handler)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v -k combat_ws`
Expected: FAIL — `404`/routing error (route doesn't exist yet).

- [ ] **Step 3: Extend `main.py`**

```python
# add to imports
import time

from fastapi import Query, WebSocket, WebSocketDisconnect

import combat
import mobs
```

```python
def _cle_depuis_query(api_key: str) -> str | None:
    """Même validation que `cle_api` (Header) mais pour le WebSocket : le navigateur ne
    peut pas poser d'en-tête personnalisé à la connexion — la clé passe en query param."""
    if not API_KEYS:
        return api_key or "public"
    return api_key if api_key in API_KEYS else None


@app.websocket("/zones/{zone_id}/combat")
async def combat_ws(websocket: WebSocket, zone_id: str,
                    personnage_id: str = Query(...), api_key: str = Query("")):
    await websocket.accept()
    cle = _cle_depuis_query(api_key)
    if cle is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(cle, personnage_id)
    zone = zones.lire_zone(zone_id)
    if not perso or not zone:
        await websocket.close(code=4404)
        return
    signe = zones.signe_personnage(perso["snapshot_holistique"]) or "Bélier"
    element = dict(zones.ZONES_SEED).get(signe, "Feu")
    gabarits = mobs.lister_mobs_zone(zone_id)
    inst = await combat.rejoindre(zone_id, personnage_id, element, signe, gabarits)
    combat.enregistrer_connexion(inst, personnage_id, websocket)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    await websocket.send_json({"type": "etat", **combat.etat_public(inst)})
    try:
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: PASS (all tests, including pre-existing ones). Also run the full suite:
`python -m pytest -v`.

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/test_api.py
git commit -m "feat(jeu-factions): route WebSocket de combat (auth par query param)"
```

---

### Task 6: Retirer la résolution passive des zones de signe

**Files:**
- Modify: `briques/jeu-factions/zones.py`
- Modify: `briques/jeu-factions/tick.py`
- Modify: `briques/jeu-factions/test_zones.py`
- Modify: `briques/jeu-factions/test_tick.py`
- Modify: `briques/jeu-factions/docker-compose.yml`
- Modify: `briques/jeu-factions/manifest.json`

**Interfaces:**
- Consumes: nothing new.
- Produces: `tick.executer_tick()` ne renvoie plus que `{"groupes": [...]}` — les voies d'archétype/groupes restent résolues au tick asyncio (hors scope de ce plan), les zones de signe ne le sont plus.

- [ ] **Step 1: Remove the now-dead functions from `zones.py`**

Delete `resoudre_toutes_zones()` and `calculer_resolution()` entirely (the real-time combat
engine — Task 3/4 — replaces both). `signe_personnage()` (renamed in Task 4) stays — it's
now used by `main.py`'s WebSocket route.

- [ ] **Step 2: Remove the matching tests from `test_zones.py`**

Delete: `test_calculer_resolution_pure_vaincue`, `test_calculer_resolution_pure_pas_vaincue`,
`test_resoudre_toutes_zones_marque_vaincue_et_note_le_score`,
`test_resoudre_toutes_zones_ignore_les_zones_deja_vaincues`. (`test_lire_zone_scores_reflete_la_resolution`
was already replaced by `test_lire_zone_scores_reflete_ajouter_score` in Task 4.)

- [ ] **Step 3: Simplify `tick.py`**

```python
"""Résolution planifiée des groupes actifs (voies d'archétype). Les zones de signe ne sont
plus résolues ici — elles se jouent en temps réel (cf. combat.py, combat_moteur.py).
`executer_tick()` est une passe unique, appelée par les tests SANS sleep, et par
`boucle_tick()` en production."""
import asyncio
import os

import groupes

TICK_INTERVAL_HOURS = float(os.getenv("TICK_INTERVAL_HOURS", "24"))


def executer_tick() -> dict:
    return {"groupes": groupes.resoudre_groupes_actifs()}


async def boucle_tick() -> None:
    while True:
        executer_tick()
        await asyncio.sleep(TICK_INTERVAL_HOURS * 3600)
```

- [ ] **Step 4: Update `test_tick.py`**

```python
import archetypes as A
import zones as Z
import tick as T


def test_executer_tick_ne_resout_plus_que_les_groupes():
    Z.seed_zones()
    A.seed_zones_archetype()
    resultat = T.executer_tick()
    assert list(resultat.keys()) == ["groupes"]


def test_executer_tick_sans_rien_a_resoudre_ne_plante_pas():
    Z.seed_zones()
    A.seed_zones_archetype()
    resultat = T.executer_tick()
    assert resultat["groupes"] == []
```

(This replaces the old `test_executer_tick_resout_zones_et_groupes` and
`test_executer_tick_sans_rien_a_resoudre_ne_plante_pas` — remove both, add the two above.)

- [ ] **Step 5: Document the new meaning of `PATCH /personnages/{pid}/zone` in `main.py`**

The route's code doesn't change (it already only writes `zone_actuelle`, it never
triggered resolution itself) — but its *meaning* changes now that nothing reads
`zone_actuelle` to resolve anything. Add a comment so a future reader doesn't assume it
still drives PvE resolution:

```python
# Ne pilote plus aucune résolution passive (celle-ci a disparu avec
# `zones.resoudre_toutes_zones`, cf. spec combat) — purement cosmétique : « dernière zone
# visitée », affichée par défaut dans le front. Entrer en combat = ouvrir le WebSocket
# `/zones/{zone_id}/combat`, indépendamment de cette valeur.
@app.patch("/personnages/{pid}/zone", tags=["personnages"])
def assigner_zone_route(pid: str, body: AssignerZone, cle: str = Depends(cle_api)):
```

- [ ] **Step 6: Run the full suite to verify nothing broke**

Run: `cd briques/jeu-factions && python -m pytest -v`
Expected: PASS (every test in the brick).

- [ ] **Step 7: Update `docker-compose.yml`**

Replace the `environment:` block:

```yaml
    environment:
      - PORT=6210
      - PERSONNAGES_URL=http://host.docker.internal:5900
      - JEU_FACTIONS_DB=/data/jeu_factions.db
      - TICK_INTERVAL_HOURS=24
      - COMBAT_TICK_HZ=10
      - JEU_FACTIONS_INSTANCE_CAPACITE=30
      - COMBAT_INSTANCE_GRACE_S=30
      - COMBAT_BOSS_RESPAWN_S=60
      - COMBAT_ARENE_TAILLE=800
```

(`STATS_ZONE_SIGNE` removed — dead config, nothing reads it anymore.)

- [ ] **Step 8: Update `manifest.json`**

```json
  "description": "Création de personnage (via la brique personnages) + factions à deux niveaux (nation=élément, guilde=signe, classe=archétype) + combat 2D temps réel joué en zones de signe (PvE partagé, shardé par instance) + voies d'archétype personnelles avec groupes ouverts. Sous-projets 1 et 2 du jeu holistique.",
```

```json
  "offre": [
    "creation_personnage_holistique",
    "combat_temps_reel_pve",
    "zones_signe_pve_partage",
    "voies_archetype_personnelles",
    "groupes_ouverts"
  ],
```

- [ ] **Step 9: Commit**

```bash
git add briques/jeu-factions/zones.py briques/jeu-factions/tick.py \
       briques/jeu-factions/test_zones.py briques/jeu-factions/test_tick.py \
       briques/jeu-factions/docker-compose.yml briques/jeu-factions/manifest.json
git commit -m "refactor(jeu-factions): retire la résolution passive des zones (remplacée par le combat joué)"
```

---

### Task 7: Client de combat (`front_combat.html`)

**Files:**
- Create: `briques/jeu-factions/front_combat.html`
- Modify: `briques/jeu-factions/front.html`
- Modify: `briques/jeu-factions/main.py`
- Test: `briques/jeu-factions/test_front_combat.py`

**Interfaces:**
- Consumes: `GET /personnages`, `GET /personnages/{id}/competences`, `WS /zones/{zone_id}/combat` (existants).
- Produces: page servie à `GET /front_combat.html`.

- [ ] **Step 1: Write the failing test**

```python
# test_front_combat.py
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_front_combat_sert_le_html():
    r = client.get("/front_combat.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "phaser" in r.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/jeu-factions && python -m pytest test_front_combat.py -v`
Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Add the route in `main.py`**

```python
@app.get("/front_combat.html", response_class=FileResponse, include_in_schema=False)
def combat_front():
    return FileResponse(Path(__file__).parent / "front_combat.html")
```

- [ ] **Step 4: Write `front_combat.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Jeu-factions — Combat</title>
<link rel="stylesheet" href="/workplace.css">
<script src="https://cdn.jsdelivr.net/npm/phaser@3.80.1/dist/phaser.min.js"></script>
<style>
  #hud { display: flex; gap: 16px; align-items: center; padding: 8px; }
  .barre { width: 200px; height: 14px; background: #333; border-radius: 4px; overflow: hidden; }
  .barre-remplissage { height: 100%; background: #4ade80; }
  #sorts button { margin-right: 4px; }
  #jeu { width: 800px; max-width: 100%; }
</style>
</head>
<body>
<h1>Jeu-factions — Combat</h1>
<div id="hud">
  <div>PV : <div class="barre"><div id="pv-joueur" class="barre-remplissage" style="width:100%"></div></div></div>
  <div>Boss : <div class="barre"><div id="pv-boss" class="barre-remplissage" style="width:100%"></div></div></div>
</div>
<div id="sorts"></div>
<div id="jeu"></div>

<script>
const params = new URLSearchParams(location.search);
const zoneId = params.get("zone");
const cleApi = localStorage.getItem("jeu_factions_cle") || "";

let personnageId = null;
let dernierEtat = {joueurs: {}, mobs: {}};
let cibleActive = null;
let ws;

async function initPersonnage() {
  const r = await fetch("/personnages", {headers: cleApi ? {"X-API-Key": cleApi} : {}});
  const mine = await r.json();
  if (!mine.length) {
    document.getElementById("jeu").textContent = "Crée d'abord un personnage sur la page principale.";
    throw new Error("aucun personnage");
  }
  personnageId = mine[0].id;
  const rc = await fetch(`/personnages/${personnageId}/competences`,
    {headers: cleApi ? {"X-API-Key": cleApi} : {}});
  const sorts = (await rc.json()).filter(c => c.effet_type);
  document.getElementById("sorts").innerHTML = sorts.map(s =>
    `<button data-id="${s.id}">${s.nom}</button>`).join("");
  document.querySelectorAll("#sorts button").forEach(b => b.addEventListener("click", () => {
    if (cibleActive && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: "sort", competence_id: b.dataset.id, cible_id: cibleActive}));
    }
  }));
}

function connecter() {
  const protocole = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocole}//${location.host}/zones/${zoneId}/combat` +
    `?personnage_id=${personnageId}&api_key=${encodeURIComponent(cleApi)}`);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type !== "etat") return;
    dernierEtat = msg;
    const moi = msg.joueurs[personnageId];
    if (moi) document.getElementById("pv-joueur").style.width = `${(moi.pv / moi.pv_max) * 100}%`;
    const boss = Object.values(msg.mobs).find(m => m.role === "boss");
    document.getElementById("pv-boss").style.width = boss ? `${(boss.pv / boss.pv_max) * 100}%` : "0%";
  };
}

class SceneCombat extends Phaser.Scene {
  create() {
    this.formes = new Map();
    this.cursors = this.input.keyboard.createCursorKeys();
  }
  _forme(id, couleur, rayon) {
    let f = this.formes.get(id);
    if (!f) {
      f = this.add.circle(0, 0, rayon, couleur).setInteractive();
      f.on("pointerdown", () => { cibleActive = id; });
      this.formes.set(id, f);
    }
    return f;
  }
  update() {
    let dx = 0, dy = 0;
    if (this.cursors.left.isDown) dx = -1;
    if (this.cursors.right.isDown) dx = 1;
    if (this.cursors.up.isDown) dy = -1;
    if (this.cursors.down.isDown) dy = 1;
    if ((dx || dy) && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: "deplacement", direction: {x: dx, y: dy}}));
    }
    const vus = new Set();
    for (const [id, j] of Object.entries(dernierEtat.joueurs || {})) {
      const f = this._forme(id, id === personnageId ? 0xfacc15 : 0x60a5fa, 10);
      f.setPosition(j.x, j.y);
      vus.add(id);
    }
    for (const [id, m] of Object.entries(dernierEtat.mobs || {})) {
      const f = this._forme(id, m.role === "boss" ? 0xef4444 : 0xf97316, m.role === "boss" ? 20 : 12);
      f.setPosition(m.x, m.y);
      vus.add(id);
    }
    for (const [id, f] of this.formes) {
      if (!vus.has(id)) { f.destroy(); this.formes.delete(id); }
    }
  }
}

(async () => {
  await initPersonnage();
  connecter();
  new Phaser.Game({
    type: Phaser.AUTO, width: 800, height: 800, parent: "jeu",
    backgroundColor: "#1e293b", scene: SceneCombat,
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 5: Add a "join combat" link per zone in `front.html`**

Replace the `chargerZones()` function:

```javascript
async function chargerZones() {
  const r = await fetch("/zones", {headers: entetes()});
  const items = await r.json();
  document.getElementById("listeZones").innerHTML = items.map(z =>
    `<li>${z.nom} (${z.element_natif}) — ${z.etat} ` +
    `<a href="/front_combat.html?zone=${z.id}">Rejoindre le combat</a></li>`
  ).join("");
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_front_combat.py -v`
Expected: PASS. Then run the full suite: `python -m pytest -v` — every test in the brick
should be green.

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions/front_combat.html briques/jeu-factions/front.html \
       briques/jeu-factions/main.py briques/jeu-factions/test_front_combat.py
git commit -m "feat(jeu-factions): client de combat (Phaser 3 via CDN, sans build)"
```

---

## Manual verification (after all tasks)

The plan's automated tests mock `personnages` and never open a real browser WebSocket.
Before considering this done, per the repo's testing philosophy, actually run it:

```bash
cd briques/jeu-factions && python -m uvicorn main:app --port 6210 &
open http://localhost:6210/
```

Create a character, click "Rejoindre le combat" on a zone, confirm: the arena renders, the
player token moves with arrow keys, clicking a mob sets it as target, clicking a spell
button while a target is selected deals damage (boss HP bar drops), and the boss dying
updates `GET /zones/{id}` scores.
