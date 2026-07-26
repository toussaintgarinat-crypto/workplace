# Famille « Veille » (parent) + retag geo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Créer le regroupement dashboard « 🔭 Veille » et y rattacher la brique `geo`, sans toucher au code fonctionnel de `geo`.

**Architecture:** `core/familles.py` porte déjà une taxonomie générique (liste `FAMILLES` + fonction `grouper()`) consommée par `core/routers/systeme.py` (`GET /briques?grouper=famille`) et rendue par le dashboard. Ajouter une entrée `veille` à cette liste, puis changer la valeur du champ `famille` dans `briques/geo/manifest.json` suffit à faire apparaître le nouveau groupe — aucune autre partie du code ne lit ce champ.

**Tech Stack:** Python 3.11/3.14, pytest (`make test-core` = `pytest core` avec `VAULT_SECRET`/`GATEWAY_KEY` factices).

## Global Constraints

- Ne modifier AUCUNE capacité, route, port ou fichier de `briques/geo/` autre que `manifest.json` — la brique est déployée LIVE sur le HP, zéro risque de régression fonctionnelle toléré.
- Le champ `famille` du manifest ne doit contenir qu'un seul slug (pas de liste) — c'est la convention existante dans toutes les autres briques.
- Suivre le style d'import déjà en place dans `core/test_*.py` : import direct du module (`import familles`), pas de `from core import familles`.

---

### Task 1: Ajouter la famille « veille » à la taxonomie

**Files:**
- Modify: `core/familles.py:7-15`
- Test: `core/test_familles.py` (nouveau fichier)

**Interfaces:**
- Consumes: rien (module autonome, pas de dépendance externe)
- Produces: `familles.FAMILLES` contient désormais un dict `{"slug": "veille", "label": "Veille", "icone": "🔭", "ordre": 6}` ; `familles.meta("veille")` retourne ce dict ; `familles.grouper(briques)` regroupe toute brique dont `famille == "veille"` sous la clé `"veille"` avec `label="Veille"` et `icone="🔭"`.

- [ ] **Step 1: Write the failing test**

Créer `core/test_familles.py` :

```python
"""Tests de la taxonomie des familles de briques (S142 + ajout famille veille)."""
import familles


def test_veille_est_dans_la_taxonomie():
    slugs = [f["slug"] for f in familles.FAMILLES]
    assert "veille" in slugs


def test_meta_veille_a_le_bon_label_et_icone():
    m = familles.meta("veille")
    assert m["label"] == "Veille"
    assert m["icone"] == "🔭"


def test_grouper_range_une_brique_veille_dans_le_bon_groupe():
    briques = [{"nom": "geo-demo", "famille": "veille"}]
    groupes = familles.grouper(briques)
    assert "veille" in groupes
    assert groupes["veille"]["label"] == "Veille"
    assert groupes["veille"]["icone"] == "🔭"
    assert groupes["veille"]["briques"] == briques


def test_toutes_les_familles_ont_un_slug_unique():
    slugs = [f["slug"] for f in familles.FAMILLES]
    assert len(slugs) == len(set(slugs))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_familles.py -v`
Expected: FAIL sur `test_veille_est_dans_la_taxonomie` et `test_meta_veille_a_le_bon_label_et_icone` (slug absent), les deux autres tests passent déjà (comportement générique existant).

- [ ] **Step 3: Write minimal implementation**

Dans `core/familles.py`, remplacer la liste `FAMILLES` (lignes 7-15) par :

```python
FAMILLES: list[dict] = [
    {"slug": "ia",            "label": "Socle IA",                    "icone": "🧠", "ordre": 1},
    {"slug": "ingestion",     "label": "Ingestion & Analyse",          "icone": "📄", "ordre": 2},
    {"slug": "generation",    "label": "Génération & Livraison",       "icone": "🏗️", "ordre": 3},
    {"slug": "collaboration", "label": "Collaboration & Communication", "icone": "💬", "ordre": 4},
    {"slug": "media",         "label": "Média & Contenu",              "icone": "🎬", "ordre": 5},
    {"slug": "veille",        "label": "Veille",                      "icone": "🔭", "ordre": 6},
    {"slug": "metier",        "label": "Applications Métier",          "icone": "🏢", "ordre": 7},
    {"slug": "dev",           "label": "Persistance & Dev",            "icone": "🛠️", "ordre": 8},
]
```

(`metier` passe de l'ordre 6 à 7, `dev` de 7 à 8 ; `veille` s'insère à l'ordre 6, juste avant les applications métier.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_familles.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add core/familles.py core/test_familles.py
git commit -m "feat(core): ajoute la famille de briques \"veille\" (🔭)"
```

---

### Task 2: Retagger `geo` dans la famille « veille »

**Files:**
- Modify: `briques/geo/manifest.json:3`
- Test: `core/test_familles.py` (ajout d'un test, même fichier que Task 1)

**Interfaces:**
- Consumes: `familles.grouper` (Task 1) — signature `grouper(briques: list[dict]) -> dict`.
- Produces: `briques/geo/manifest.json["famille"] == "veille"`, vérifiable par n'importe quel outil qui scanne les manifests (dashboard, `/briques?grouper=famille`).

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `core/test_familles.py` :

```python
import json
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent


def test_manifest_geo_est_dans_la_famille_veille():
    manifest = json.loads((_RACINE / "briques" / "geo" / "manifest.json").read_text())
    assert manifest["famille"] == "veille"


def test_grouper_avec_le_vrai_manifest_geo_atterrit_dans_veille():
    manifest = json.loads((_RACINE / "briques" / "geo" / "manifest.json").read_text())
    groupes = familles.grouper([manifest])
    assert manifest in groupes["veille"]["briques"]
    assert "metier" not in groupes or manifest not in groupes["metier"]["briques"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_familles.py -v`
Expected: FAIL sur `test_manifest_geo_est_dans_la_famille_veille` (`assert "metier" == "veille"`) et sur `test_grouper_avec_le_vrai_manifest_geo_atterrit_dans_veille`.

- [ ] **Step 3: Write minimal implementation**

Dans `briques/geo/manifest.json`, ligne 3, remplacer :

```json
  "famille": "metier",
```

par :

```json
  "famille": "veille",
```

(Aucune autre ligne du fichier ne change.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_familles.py -v`
Expected: `6 passed`

Puis lancer la suite complète du Cœur pour confirmer l'absence de régression :

Run: `make test-core`
Expected: tous les tests passent (aucun test existant ne dépend de `geo.famille == "metier"`, vérifié par recherche préalable sur tout le repo).

- [ ] **Step 5: Commit**

```bash
git add briques/geo/manifest.json core/test_familles.py
git commit -m "feat(geo): rattache la brique à la famille \"veille\""
```

---

### Task 3: Vérification manuelle end-to-end (dashboard)

**Files:** aucun fichier modifié — vérification uniquement.

**Interfaces:** aucune (consomme le résultat des Tasks 1+2 via l'endpoint HTTP existant).

- [ ] **Step 1: Démarrer le Cœur en local (si pas déjà lancé)**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m uvicorn main:app --port 5100 &`
Expected: le serveur démarre sans erreur, log `Uvicorn running on http://0.0.0.0:5100`.

- [ ] **Step 2: Vérifier le groupement par l'API**

Run: `curl -s http://localhost:5100/briques?grouper=famille | python3 -m json.tool | grep -A3 '"veille"'`
Expected: un bloc JSON avec `"label": "Veille"`, `"icone": "🔭"`, et `"briques"` contenant l'objet dont `"nom": "geo"`.

- [ ] **Step 3: Vérifier que `geo` n'apparaît plus dans `metier`**

Run: `curl -s http://localhost:5100/briques?grouper=famille | python3 -c "import json,sys; d=json.load(sys.stdin); print([b['nom'] for b in d.get('metier',{}).get('briques',[])])"`
Expected: la liste imprimée ne contient pas `"geo"`.

- [ ] **Step 4: Coup d'œil dashboard**

Ouvrir `http://localhost:5100/dashboard` dans un navigateur, confirmer qu'une section « 🔭 Veille » est visible avec la tuile `geo` dedans, cliquable comme avant.

- [ ] **Step 5: Arrêter le serveur de test**

Run: `kill %1` (ou `pkill -f "uvicorn main:app --port 5100"`)

Pas de commit pour cette tâche (vérification pure, aucun fichier modifié).
