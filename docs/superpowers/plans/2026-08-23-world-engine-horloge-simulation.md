# World Engine — Horloge de simulation (Sprint C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire vivre un monde spatial (Sprint B) au fil de ticks (1 tick = 1 an narratif) : vieillissement/mortalité, migration, formation/dissolution de couples, reproduction — sur un monde non fédéré, à volume modéré, avec un scheduler in-process opt-in par monde.

**Architecture:** Extraction d'abord (`genome_moteur.py` sort de `main.py` pour être réutilisable sans HTTP), puis 2 nouveaux modules de stockage (`stockage_horloge.py` pour les tables neuves, extensions de `stockage_spatial.py` pour les colonnes ajoutées), un module de mécanique pure (`horloge.py`, même esprit que `spatial.py`/`fusion.py` — aucune I/O), un orchestrateur (`horloge_moteur.py`) qui compose le tout, et enfin le routeur `/horloge` + le scheduler in-process dans `main.py`.

**Tech Stack:** FastAPI, SQLite (stdlib `sqlite3`), Pydantic, `httpx`/`respx` (tests), aucune nouvelle dépendance externe (le scheduler est une tâche `asyncio` de fond, pas un service séparé).

## Global Constraints

- Cloisonnement par `cle_api` sur toute nouvelle route — 404 si absent/autre clé, jamais 403 (même motif que `/genome` et `/spatial`).
- Aucune écriture partielle ne doit faire échouer une requête ou un tick entier — erreurs capturées, ajoutées à `avertissements`, jamais un 500 (même motif que Sprint A/B).
- Toute migration de schéma (nouvelle colonne) doit être idempotente : `ALTER TABLE ... ADD COLUMN` échoue si rejoué sur une colonne déjà présente — utiliser le helper `_ajouter_colonne` (vérifie via `PRAGMA table_info` avant d'altérer).
- Déterminisme : toute fonction aléatoire de `horloge.py` reçoit son `Random` en paramètre (jamais de `random` module-global) — même motif que `fusion.fusionner_description`.
- `docs/superpowers/specs/2026-08-23-world-engine-horloge-simulation-design.md` est la source de vérité pour TOUTE valeur de comportement (ordre des étapes, quelles données par placement/cellule) ; ce plan choisit les constantes numériques exactes (âges, probabilités, plafonds) que le design a explicitement laissées à l'implémentation.

---

## Contexte pour l'implémenteur (lire avant de commencer)

`briques/world-engine` (port 6220) a déjà, avant ce sprint :
- `stockage.py` : table `enfants` (id, cle_api, prenoms, nom, parent_a_id, parent_b_id, donnees JSON, cree_le).
- `stockage_spatial.py` : tables `mondes`, `cellules` (x, y, biome, ressources JSON liste, voisins JSON liste), `placements` (enfant_id, monde_id, cellule_id, place_le) — PLUS une copie dupliquée de la DDL `enfants` (fix latent documenté, pincé par un test de parité).
- `spatial.py` : génération procédurale pure (Voronoï + bruit cohérent), aucune I/O.
- `fusion.py` : logique pure de fusion cosmique (aucune I/O).
- `personnages_client.py` : seul point de contact HTTP avec la brique `personnages`.
- `main.py` : routes `/genome/*` et `/spatial/*`, contient AUSSI toute la logique de croisement (modèles Pydantic + fonctions `_theme_parent`/`_cellule_naissance`/etc.) — ce sprint l'extrait dans `genome_moteur.py` pour la rendre appelable sans HTTP (l'horloge doit pouvoir déclencher une naissance automatique sans passer par une requête HTTP interne).

Un enfant peut déjà être placé sur un monde à sa naissance (`monde_id` sur `POST /genome/croiser`), et un monde peut être forké (copie indépendante de cellules+placements). Ce sprint AJOUTE : persistance du sexe d'un enfant (absente jusqu'ici — `sexe` n'était qu'un rôle transitoire de croisement, jamais stocké), l'âge/statut vivant PAR PLACEMENT (pas par enfant — un enfant peut être vivant dans un monde et mort dans un fork de ce monde), des couples, un stock de ressources numérique par cellule, un niveau de technologie par cellule, et le routeur `/horloge`.

---

### Task 1: Extraire `genome_moteur.py` depuis `main.py` (refactor pur)

**Files:**
- Create: `briques/world-engine/genome_moteur.py`
- Modify: `briques/world-engine/main.py:1-30` (imports), `main.py:52-278` (modèles + fonctions + route `genome_croiser`)
- Test: aucun nouveau test — la suite existante (`test_api.py`, `test_manifest_capacites.py`) doit passer SANS AUCUNE MODIFICATION après ce refactor.

**Interfaces:**
- Consumes : rien (pur déplacement de code déjà existant dans `main.py`).
- Produces : `genome_moteur.FicheParent`, `genome_moteur.ReferenceParent`, `genome_moteur.ParentInput`, `genome_moteur.Croisement`, `genome_moteur.executer_croisement(body: Croisement, cle_api_val: str) -> dict` (async) — consommés par `main.py` (Task 1) et par `horloge_moteur.py` (Task 6).

- [ ] **Step 1 : créer `genome_moteur.py` avec le contenu déplacé**

Déplace TEL QUEL (aucun changement de comportement) les éléments suivants de `main.py` : `FicheParent` (lignes 52-71), `ReferenceParent` (74-83), `ParentInput` (86), `Croisement` (89-102), `_detail` (112-119), `_propager_ou_502` (122-129), `_exiger_theme_complet` (132-143), `_theme_parent` (146-166), `_parent_reference_naissance` (169-176), `_cellule_naissance` (179-198). La route `genome_croiser` (201-278) devient la fonction `executer_croisement` ci-dessous (signature changée : prend `body`/`cle_api_val` au lieu de `body`/`Depends(cle_api)`, ne dépend plus de FastAPI).

```python
"""Logique de croisement cosmique (Sprint A/B), extraite de `main.py` (Sprint C) pour
être appelable SANS HTTP — l'horloge (`horloge_moteur.py`) déclenche des naissances
automatiques par appel de fonction direct, pas par requête HTTP interne."""
from __future__ import annotations

from datetime import date
from random import Random
from typing import Literal, Optional, Union

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

import fusion
import personnages_client
import stockage
import stockage_horloge
import stockage_spatial


class FicheParent(BaseModel):
    """Même forme que FicheHolistique côté personnages — sous-ensemble minimal
    pour ce prototype (pas de systeme_numerologie/langue_sortie ici, YAGNI).

    heure_naissance/latitude/longitude restent optionnels ICI (comme côté
    personnages, repli honnête), mais sont EFFECTIVEMENT nécessaires : sans eux,
    personnages renvoie un theme_complet dégradé (sans dominantes/dix_corps) et
    _exiger_theme_complet() refuse la fiche avec un 422 explicite plutôt que de
    laisser le calcul planter plus loin."""
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


class ReferenceParent(BaseModel):
    """Référence à un enfant déjà stocké (Sprint A), utilisable comme parent d'un
    nouveau croisement — évite de recopier date/heure/lieu de naissance d'un
    enfant déjà généré. `extra="forbid"` sur les deux modèles rend le choix entre
    fiche brute et référence déterministe pour Pydantic (aucun input valide ne
    peut matcher les deux à la fois)."""
    model_config = ConfigDict(extra="forbid")

    id: str
    sexe: Optional[Literal["F", "M"]] = None


ParentInput = Union[ReferenceParent, FicheParent]


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
    sexe_enfant: Optional[Literal["F", "M"]] = None  # Sprint C : persisté sur l'enfant (voir
                                                       # stockage.py) — nécessaire à l'horloge pour
                                                       # apparier des couples F/M. Absent ⇒ enfant
                                                       # non appariable automatiquement (jamais deviné).
    monde_id: Optional[str] = None  # place l'enfant à sa naissance (Sprint B) — absent = non placé


def _detail(resp) -> str:
    """Message d'erreur d'une réponse `personnages` non-200 — repli honnête sur le
    texte brut si le corps n'est pas du JSON valide OU n'est pas un objet (ne lève jamais)."""
    try:
        corps = resp.json()
        return corps.get("detail", resp.text) if isinstance(corps, dict) else resp.text
    except ValueError:
        return resp.text


def _propager_ou_502(resp, qui: str) -> None:
    """Propage un 422 de `personnages` tel quel (fiche invalide, faute de l'appelant).
    Tout autre code (401/403/5xx…) signale un problème CÔTÉ world-engine (mauvaise
    clé d'intégration, panne) et devient un 502 — jamais confondu avec un rejet de
    l'appelant, qui verrait sinon SA requête accusée à tort."""
    if resp.status_code == 422:
        raise HTTPException(422, f"{qui} : {_detail(resp)}")
    raise HTTPException(502, f"{qui} : personnages a répondu {resp.status_code} — {_detail(resp)}")


def _exiger_theme_complet(theme: dict, qui: str) -> dict:
    """`personnages` répond 200 avec un theme_complet DÉGRADÉ (sans dominantes ni
    dix_corps) si l'heure ou le lieu de naissance manque ou est malformé — jamais
    une erreur de son côté (repli honnête documenté dans theme_complet.py). On
    refuse honnêtement ICI plutôt que de planter en KeyError plus loin."""
    tc = theme.get("theme_complet") or {}
    manquant = [k for k in ("dominantes", "dix_corps") if k not in tc]
    if manquant:
        raise HTTPException(422, f"{qui} : thème incomplet ({', '.join(manquant)} absent(s)). "
                                  "Fournis une heure de naissance 'HH:MM' valide ET un lieu "
                                  "(latitude/longitude) — jamais devinés.")
    return tc


async def _theme_parent(parent: ParentInput, cle_api_val: str, qui: str) -> dict:
    """Résout le thème d'un parent : soit en rappelant `personnages` (fiche brute),
    soit en relisant un enfant déjà stocké (référence par id) — sans appel réseau
    dans ce second cas."""
    if isinstance(parent, ReferenceParent):
        enfant = stockage.lire(cle_api_val, parent.id)
        if enfant is None:
            raise HTTPException(404, f"{qui} : enfant stocké '{parent.id}' introuvable.")
        return enfant["theme"]
    try:
        # exclude={"sexe"} : rôle dans CE croisement (placement, Sprint B), pas un
        # trait de la fiche envoyée à `personnages` — ne doit jamais franchir la
        # frontière de la brique (voir doc du champ sur FicheParent).
        r = await personnages_client.portrait(parent.model_dump(exclude={"sexe"}))
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if r.status_code != 200:
        _propager_ou_502(r, qui)
    theme = r.json()
    _exiger_theme_complet(theme, qui)
    return theme


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
    nb = stockage_spatial.nb_cellules_monde(monde_id)
    if nb is None:
        raise RuntimeError(f"Monde '{monde_id}' supprimé pendant le croisement.")
    return rng.randrange(nb)


async def executer_croisement(body: Croisement, cle_api_val: str) -> dict:
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel, avec
    un récit d'hérédité en post-traitement — coïncidence assumée, pas une vraie
    génétique astrale (voir `fusion.comparer_dix_corps`). Si `monde_id` est fourni,
    l'enfant est aussi placé sur ce monde spatial (Sprint B) — voisin de la cellule
    du parent de référence (sexe="F", sinon parent_a) s'il y est déjà, sinon cellule
    aléatoire bornée. Extrait de la route `/genome/croiser` (Sprint C) pour être
    appelable sans HTTP par l'horloge."""
    if (isinstance(body.parent_a, ReferenceParent) and isinstance(body.parent_b, ReferenceParent)
            and body.parent_a.id == body.parent_b.id):
        raise HTTPException(422, "Un enfant ne peut pas être croisé avec lui-même.")
    if body.monde_id is not None and not stockage_spatial.monde_existe(cle_api_val, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    theme_a = await _theme_parent(body.parent_a, cle_api_val, "Parent A")
    theme_b = await _theme_parent(body.parent_b, cle_api_val, "Parent B")

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
        enfant_id = stockage.creer(cle_api_val, body.prenoms_enfant, body.nom_enfant,
                                    parent_a_id, parent_b_id, theme_enfant,
                                    description, heredite, mutation_survenue, body.sexe_enfant)
        avertissement = None
    except Exception as e:
        enfant_id = None
        avertissement = f"Enfant calculé mais non persisté : {e}"

    cellule_id = None
    if body.monde_id is not None and enfant_id is not None:
        try:
            parent_ref = _parent_reference_naissance(body.parent_a, body.parent_b)
            cellule_id = _cellule_naissance(body.monde_id, parent_ref, Random())
            horloge_etat = stockage_horloge.lire_horloge(body.monde_id)
            ne_au_tick = horloge_etat["tick_actuel"] if horloge_etat else 0
            stockage_spatial.placer(body.monde_id, enfant_id, cellule_id, ne_au_tick=ne_au_tick)
        except Exception as e:
            cellule_id = None
            avertissement = f"Enfant persisté mais non placé : {e}"

    return {"parentA": theme_a, "parentB": theme_b, "description_genome": description,
            "enfant": theme_enfant, "heredite": heredite, "mutation_survenue": mutation_survenue,
            "enfant_id": enfant_id, "cellule_id": cellule_id, "avertissement": avertissement}
```

> Note : cette version de `executer_croisement` référence déjà `stockage.creer(..., body.sexe_enfant)` et `stockage_horloge`/`ne_au_tick` qui n'existent pas encore à ce stade — Task 1 est un refactor pur, donc écris D'ABORD la version SANS ces deux ajouts (signature `stockage.creer` inchangée à 8 arguments, pas d'import `stockage_horloge`, `stockage_spatial.placer(body.monde_id, enfant_id, cellule_id)` sans `ne_au_tick`) pour que les tests existants passent tel quel après le seul déplacement de code. Les ajouts `sexe_enfant`/`ne_au_tick` arrivent en Task 2 et Task 4 — le bloc ci-dessus montre l'état FINAL après ces deux tasks, à titre de référence pour ne pas te tromper plus tard.

- [ ] **Step 2 : simplifier `main.py`**

Dans `main.py`, remplace les lignes 52-278 (tout ce qui a été déplacé) par :

```python
import genome_moteur


@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: genome_moteur.Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel — voir
    `genome_moteur.executer_croisement` pour le détail."""
    return await genome_moteur.executer_croisement(body, _cle)
```

Retire de l'en-tête de `main.py` (lignes 1-21) les imports devenus inutiles : `from datetime import date`, `from random import Random` (⚠️ NE PAS retirer `Random` si `spatial_monde_creer` l'utilise encore pour générer un `seed` — vérifie avant de retirer), `from typing import Literal, Optional, Union` (garde `Optional` si utilisé ailleurs dans `main.py`, ex. `cle_api`), `fusion`, `personnages_client`. Garde `stockage`, `stockage_spatial` (encore utilisés par les autres routes `/genome/enfants*`, `/genome/arbre`, `/spatial/*`). Garde `ConfigDict`, `Field` si `CreerMonde` (reste dans `main.py`) les utilise encore.

- [ ] **Step 3 : lancer la suite de tests existante, aucune régression attendue**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: tous les tests déjà présents PASSENT, à l'identique d'avant ce refactor (même nombre de tests, aucun changement de comportement).

- [ ] **Step 4 : commit**

```bash
git add briques/world-engine/genome_moteur.py briques/world-engine/main.py
git commit -m "refactor(world-engine): extrait genome_moteur.py de main.py (réutilisable sans HTTP)"
```

---

### Task 2: Persister `sexe` sur les enfants stockés

**Files:**
- Modify: `briques/world-engine/stockage.py` (DDL + `creer()` + `_ligne_complete()` + `lister()`)
- Modify: `briques/world-engine/stockage_spatial.py:20-40` (DDL dupliquée de `enfants`)
- Modify: `briques/world-engine/genome_moteur.py` (déjà fait en Task 1 — `sexe_enfant` sur `Croisement`, passé à `stockage.creer`)
- Test: `briques/world-engine/test_stockage.py`, `briques/world-engine/test_stockage_spatial.py` (parité DDL), `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes : rien de nouveau.
- Produces : `stockage.creer(cle_api, prenoms, nom, parent_a_id, parent_b_id, theme, description_genome, heredite, mutation_survenue, sexe=None) -> str` (nouveau param optionnel en dernière position) ; `stockage.lire()`/`stockage.lister()` exposent désormais `sexe` — consommé par `stockage_spatial.population_vivante_cellule` (Task 4).

- [ ] **Step 1 : écrire le test qui échoue (persistance du sexe)**

Ajoute à `briques/world-engine/test_stockage.py` :

```python
def test_creer_et_lire_persiste_le_sexe():
    eid = stockage.creer("cle-sexe", "Ana", "Dupont", None, None,
                          {"theme_complet": {}}, "desc", {"resume": {}}, False, sexe="F")
    enfant = stockage.lire("cle-sexe", eid)
    assert enfant["sexe"] == "F"


def test_creer_sans_sexe_reste_none():
    eid = stockage.creer("cle-sexe", "Bo", "Martin", None, None,
                          {"theme_complet": {}}, "desc", {"resume": {}}, False)
    enfant = stockage.lire("cle-sexe", eid)
    assert enfant["sexe"] is None
```

- [ ] **Step 2 : lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python -m pytest test_stockage.py -k sexe -v`
Expected: FAIL — `TypeError: creer() got an unexpected keyword argument 'sexe'`

- [ ] **Step 3 : modifier `stockage.py`**

Dans la DDL de `_conn()` (ligne 25-27), remplace :

```python
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
```

par :

```python
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, sexe TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
```

Ajoute juste avant `_conn()` le helper de migration idempotente (nécessaire pour une base déjà déployée Sprint A/B sans cette colonne — `ALTER TABLE ADD COLUMN` échoue si rejoué) :

```python
def _colonne_absente(c: sqlite3.Connection, table: str, colonne: str) -> bool:
    infos = c.execute(f"PRAGMA table_info({table})").fetchall()
    return colonne not in {row[1] for row in infos}


def _ajouter_colonne(c: sqlite3.Connection, table: str, colonne: str, ddl_type: str) -> None:
    """Migration idempotente : sans le contrôle PRAGMA, `ALTER TABLE ADD COLUMN`
    échouerait sur une base déjà migrée (colonne déjà présente)."""
    if _colonne_absente(c, table, colonne):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {ddl_type}")
```

Dans `_conn()`, juste après la création de la table `enfants` (avant `return c`), ajoute :

```python
    _ajouter_colonne(c, "enfants", "sexe", "TEXT")
```

(Cette ligne est nécessaire même si la `CREATE TABLE` ci-dessus inclut déjà `sexe` : sur une base déjà existante d'un déploiement Sprint A/B, `CREATE TABLE IF NOT EXISTS` ne touche pas une table déjà créée sans cette colonne — seule cette migration l'ajoute.)

Modifie `_ligne_complete()` pour exposer `sexe` :

```python
def _ligne_complete(r: sqlite3.Row) -> dict:
    d = json.loads(r["donnees"])
    return {"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
            "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"], "sexe": r["sexe"],
            "theme": d["theme"], "description_genome": d["description_genome"],
            "heredite": d["heredite"], "mutation_survenue": d["mutation_survenue"],
            "cree_le": r["cree_le"]}
```

Modifie `creer()` :

```python
def creer(cle_api: str, prenoms: str, nom: str, parent_a_id: str | None, parent_b_id: str | None,
          theme: dict, description_genome: str, heredite: dict, mutation_survenue: bool,
          sexe: str | None = None) -> str:
    """Persiste un enfant généré par un croisement. Renvoie son id.

    `sexe` (Sprint C) : trait persistant de l'enfant — nécessaire à l'horloge pour
    apparier des couples F/M au fil des ticks (contrairement au `sexe` transitoire de
    `ParentInput` en Sprint B, qui ne désignait qu'un rôle dans UN croisement, jamais
    stocké). Absent (`None`) ⇒ l'horloge ne pourra jamais apparier cet enfant."""
    eid = uuid.uuid4().hex
    donnees = {"theme": theme, "description_genome": description_genome,
               "heredite": heredite, "mutation_survenue": mutation_survenue}
    with _conn() as c:
        c.execute("""INSERT INTO enfants (id, cle_api, prenoms, nom, parent_a_id, parent_b_id,
                     sexe, donnees, cree_le) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (eid, cle_api, prenoms or "", nom or "", parent_a_id, parent_b_id, sexe,
                   json.dumps(donnees, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return eid
```

Modifie `lister()` pour inclure `sexe` :

```python
def lister(cle_api: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, prenoms, nom, parent_a_id, parent_b_id, sexe, cree_le FROM enfants "
            "WHERE cle_api=? ORDER BY cree_le DESC", (cle_api,)).fetchall()
    return [{"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
             "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"], "sexe": r["sexe"],
             "cree_le": r["cree_le"]} for r in rows]
```

- [ ] **Step 4 : lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python -m pytest test_stockage.py -k sexe -v`
Expected: PASS

- [ ] **Step 5 : dupliquer la même migration dans `stockage_spatial.py`**

Dans `stockage_spatial.py`, ajoute le même helper `_colonne_absente`/`_ajouter_colonne` (dupliqué, même motif que la DDL `enfants` déjà dupliquée entre les deux fichiers — voir le commentaire existant ligne 33-36). Modifie la DDL dupliquée de `enfants` (lignes 37-39) :

```python
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, sexe TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    _ajouter_colonne(c, "enfants", "sexe", "TEXT")
```

Étends le test de parité existant `test_ddl_enfants_identique_a_stockage` (déjà dans `test_stockage_spatial.py`) — il compare le texte des deux blocs DDL, donc il détectera automatiquement toute divergence sur la nouvelle colonne `sexe` sans modification : relance-le pour confirmer qu'il passe toujours.

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -k ddl -v`
Expected: PASS

- [ ] **Step 6 : mettre à jour `genome_moteur.py` (déjà écrit en Task 1, vérifier la cohérence)**

Confirme que `Croisement.sexe_enfant` (ajouté au Step 1 de Task 1) et l'appel `stockage.creer(..., body.sexe_enfant)` dans `executer_croisement` correspondent exactement à la nouvelle signature de `stockage.creer` ci-dessus (9 positionnels + `sexe` nommé). Aucun changement de code supplémentaire nécessaire si Task 1 a été suivi tel quel.

- [ ] **Step 7 : test API — `sexe_enfant` traverse `POST /genome/croiser`**

Ajoute à `test_api.py` (réutilise les fixtures `_FICHE_A`/`_FICHE_B`/`_portrait_factice` déjà présentes) :

```python
@respx.mock
def test_genome_croiser_sexe_enfant_persiste():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice()),
                     httpx.Response(200, json=_portrait_factice()),
                     httpx.Response(200, json=_portrait_factice())])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 48.0, "longitude_enfant": 2.0,
        "heure_naissance_enfant": "10:00", "utc_offset_enfant": 1.0,
        "sexe_enfant": "M"})
    assert r.status_code == 200
    eid = r.json()["enfant_id"]
    enfant = client.get(f"/genome/enfants/{eid}").json()
    assert enfant["sexe"] == "M"
```

- [ ] **Step 8 : lancer et vérifier**

Run: `cd briques/world-engine && python -m pytest test_api.py -k sexe_enfant -v`
Expected: PASS

- [ ] **Step 9 : commit**

```bash
git add briques/world-engine/stockage.py briques/world-engine/stockage_spatial.py briques/world-engine/genome_moteur.py briques/world-engine/test_stockage.py briques/world-engine/test_stockage_spatial.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): persiste le sexe d'un enfant (besoin de l'horloge Sprint C)"
```

---

### Task 3: `stockage_horloge.py` — tables `horloges` et `couples`

**Files:**
- Create: `briques/world-engine/stockage_horloge.py`
- Test: `briques/world-engine/test_stockage_horloge.py`

**Interfaces:**
- Consumes : `stockage_spatial.creer_monde` (dans les tests, pour disposer d'un `monde_id`/`cle_api` réels avant de tester `horloges_actives_a_declencher`, qui JOINT avec `mondes`).
- Produces : `initialiser_horloge(monde_id)`, `lire_horloge(monde_id) -> dict|None`, `demarrer(monde_id, intervalle_secondes)`, `arreter(monde_id)`, `marquer_execution(monde_id, tick_actuel)`, `horloges_actives_a_declencher(maintenant_iso) -> list[dict]`, `copier_pour_fork(monde_source_id, nouveau_monde_id)`, `supprimer_pour_monde(monde_id)`, `former_couple(monde_id, cellule_id, habitant_a_id, habitant_b_id, tick) -> str`, `dissoudre_couple(couple_id, tick)`, `couples_actifs_cellule(monde_id, cellule_id) -> list[dict]` — consommés par `main.py` (Task 7) et `horloge_moteur.py` (Task 6).

- [ ] **Step 1 : écrire le test qui échoue**

Crée `briques/world-engine/test_stockage_horloge.py` :

```python
"""Tests du stockage SQLite de l'horloge (tables horloges/couples) — Sprint C.
Même motif que test_stockage_spatial.py (DB temporaire posée par conftest.py)."""
import stockage_horloge
import stockage_spatial


def _cellules_factices(n=3):
    return [{"cellule_id": i, "x": float(i) * 10, "y": float(i) * 5, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]


def test_initialiser_puis_lire_horloge():
    monde = stockage_spatial.creer_monde("cle-h1", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat == {"monde_id": monde["id"], "tick_actuel": 0, "actif": False,
                     "intervalle_secondes": None, "derniere_execution": None}


def test_lire_horloge_introuvable_renvoie_none():
    assert stockage_horloge.lire_horloge("id-inconnu") is None


def test_demarrer_puis_arreter():
    monde = stockage_spatial.creer_monde("cle-h2", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat["actif"] is True
    assert etat["intervalle_secondes"] == 60
    stockage_horloge.arreter(monde["id"])
    assert stockage_horloge.lire_horloge(monde["id"])["actif"] is False


def test_marquer_execution_avance_tick_et_horodate():
    monde = stockage_spatial.creer_monde("cle-h3", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.marquer_execution(monde["id"], 1)
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat["tick_actuel"] == 1
    assert etat["derniere_execution"] is not None


def test_horloges_actives_a_declencher_jamais_executee_est_due():
    monde = stockage_spatial.creer_monde("cle-h4", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    dues = stockage_horloge.horloges_actives_a_declencher("2026-01-01T00:00:00+00:00")
    assert any(d["monde_id"] == monde["id"] and d["cle_api"] == "cle-h4" for d in dues)


def test_horloges_actives_a_declencher_ignore_inactif():
    monde = stockage_spatial.creer_monde("cle-h5", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])  # actif=0 par défaut
    dues = stockage_horloge.horloges_actives_a_declencher("2026-01-01T00:00:00+00:00")
    assert not any(d["monde_id"] == monde["id"] for d in dues)


def test_horloges_actives_a_declencher_respecte_intervalle():
    from datetime import datetime, timezone
    monde = stockage_spatial.creer_monde("cle-h6", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 3600)
    stockage_horloge.marquer_execution(monde["id"], 1)  # derniere_execution = maintenant réel
    juste_apres = datetime.now(timezone.utc).isoformat()  # quelques ms plus tard, très < 3600s
    dues = stockage_horloge.horloges_actives_a_declencher(juste_apres)
    assert not any(d["monde_id"] == monde["id"] for d in dues)  # écart quasi nul < 3600s


def test_copier_pour_fork_reprend_tick_mais_force_inactif():
    monde = stockage_spatial.creer_monde("cle-h7", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    stockage_horloge.marquer_execution(monde["id"], 5)
    fork = stockage_spatial.forker_monde("cle-h7", monde["id"])
    stockage_horloge.copier_pour_fork(monde["id"], fork["id"])
    etat_fork = stockage_horloge.lire_horloge(fork["id"])
    assert etat_fork["tick_actuel"] == 5
    assert etat_fork["actif"] is False


def test_couples_former_lister_dissoudre():
    monde = stockage_spatial.creer_monde("cle-h8", _cellules_factices(), seed=1)
    cid = stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    actifs = stockage_horloge.couples_actifs_cellule(monde["id"], 0)
    assert len(actifs) == 1 and actifs[0]["id"] == cid
    stockage_horloge.dissoudre_couple(cid, tick=2)
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []


def test_copier_pour_fork_duplique_les_couples_actifs():
    monde = stockage_spatial.creer_monde("cle-h9", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    fork = stockage_spatial.forker_monde("cle-h9", monde["id"])
    stockage_horloge.copier_pour_fork(monde["id"], fork["id"])
    actifs_fork = stockage_horloge.couples_actifs_cellule(fork["id"], 0)
    assert len(actifs_fork) == 1
    assert actifs_fork[0]["habitant_a_id"] == "hab-a"


def test_supprimer_pour_monde_purge_horloge_et_couples():
    monde = stockage_spatial.creer_monde("cle-h10", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    stockage_horloge.supprimer_pour_monde(monde["id"])
    assert stockage_horloge.lire_horloge(monde["id"]) is None
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []
```

- [ ] **Step 2 : lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python -m pytest test_stockage_horloge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stockage_horloge'`

- [ ] **Step 3 : écrire `stockage_horloge.py`**

```python
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
```

- [ ] **Step 4 : lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python -m pytest test_stockage_horloge.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5 : commit**

```bash
git add briques/world-engine/stockage_horloge.py briques/world-engine/test_stockage_horloge.py
git commit -m "feat(world-engine): stockage_horloge.py — tables horloges + couples"
```

---

### Task 4: Extensions de `stockage_spatial.py` (colonnes placements/cellules, accesseurs)

**Files:**
- Modify: `briques/world-engine/stockage_spatial.py` (DDL, `placer()`, `creer_monde()`, `forker_monde()`, `_cellule_dict()`, nouveaux accesseurs)
- Test: `briques/world-engine/test_stockage_spatial.py`

**Interfaces:**
- Consumes : rien de nouveau (tables déjà en place depuis Sprint B).
- Produces : `placer(monde_id, enfant_id, cellule_id, ne_au_tick=0)` (signature étendue), `population_vivante_cellule(monde_id, cellule_id) -> list[dict]`, `deplacer_placement(monde_id, enfant_id, nouvelle_cellule_id)`, `marquer_mort(monde_id, enfant_id, tick)`, `lire_ressources_stock(monde_id, cellule_id) -> dict`, `ecrire_ressources_stock(monde_id, cellule_id, stock)`, `lire_niveau_technologie(monde_id, cellule_id) -> float`, `ecrire_niveau_technologie(monde_id, cellule_id, niveau)` — tous consommés par `horloge_moteur.py` (Task 6).

- [ ] **Step 1 : écrire les tests qui échouent**

Ajoute à `test_stockage_spatial.py` :

```python
def test_placer_avec_ne_au_tick_et_population_vivante():
    monde = stockage_spatial.creer_monde("cle-tick1", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick1", "Ana", "X", None, None, {"theme": {}}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-tick1")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=3)
    pop = stockage_spatial.population_vivante_cellule(monde["id"], 0)
    assert pop == [{"id": eid, "sexe": "F", "ne_au_tick": 3}]


def test_placer_defaut_ne_au_tick_zero():
    monde = stockage_spatial.creer_monde("cle-tick2", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick2", "Bo", "X", None, None, {"theme": {}}, "d", {}, False, sexe="M")
    eid = stockage.lister("cle-tick2")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    pop = stockage_spatial.population_vivante_cellule(monde["id"], 0)
    assert pop[0]["ne_au_tick"] == 0


def test_marquer_mort_exclut_de_la_population_vivante():
    monde = stockage_spatial.creer_monde("cle-tick3", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick3", "Cy", "X", None, None, {"theme": {}}, "d", {}, False, sexe="M")
    eid = stockage.lister("cle-tick3")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    stockage_spatial.marquer_mort(monde["id"], eid, tick=7)
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []


def test_deplacer_placement_change_de_cellule():
    monde = stockage_spatial.creer_monde("cle-tick4", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick4", "Do", "X", None, None, {"theme": {}}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-tick4")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    stockage_spatial.deplacer_placement(monde["id"], eid, 1)
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []
    assert stockage_spatial.population_vivante_cellule(monde["id"], 1)[0]["id"] == eid


def test_ressources_stock_lire_ecrire():
    monde = stockage_spatial.creer_monde("cle-tick5", _cellules_factices(2), seed=1)
    stock = stockage_spatial.lire_ressources_stock(monde["id"], 0)
    assert stock == {"ble": 50.0}  # cellule factice a ["ble"] comme ressources, stock initial demi-plafond
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 12.5})
    assert stockage_spatial.lire_ressources_stock(monde["id"], 0) == {"ble": 12.5}


def test_niveau_technologie_lire_ecrire_defaut_zero():
    monde = stockage_spatial.creer_monde("cle-tick6", _cellules_factices(2), seed=1)
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) == 0.0
    stockage_spatial.ecrire_niveau_technologie(monde["id"], 0, 2.5)
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) == 2.5


def test_forker_monde_copie_ressources_stock_et_technologie():
    monde = stockage_spatial.creer_monde("cle-tick7", _cellules_factices(2), seed=1)
    stockage_spatial.ecrire_niveau_technologie(monde["id"], 0, 3.0)
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 7.0})
    fork = stockage_spatial.forker_monde("cle-tick7", monde["id"])
    assert stockage_spatial.lire_niveau_technologie(fork["id"], 0) == 3.0
    assert stockage_spatial.lire_ressources_stock(fork["id"], 0) == {"ble": 7.0}


def test_forker_monde_copie_placements_avec_ne_au_tick_et_vivant():
    monde = stockage_spatial.creer_monde("cle-tick8", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick8", "Eu", "X", None, None, {"theme": {}}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-tick8")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=4)
    fork = stockage_spatial.forker_monde("cle-tick8", monde["id"])
    pop_fork = stockage_spatial.population_vivante_cellule(fork["id"], 0)
    assert pop_fork == [{"id": eid, "sexe": "F", "ne_au_tick": 4}]
```

Ajoute l'import manquant en tête de `test_stockage_spatial.py` si absent (`stockage` est déjà importé — vérifie).

- [ ] **Step 2 : lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -k tick -v`
Expected: FAIL — `TypeError: placer() got an unexpected keyword argument 'ne_au_tick'` (et suivants, au fur et à mesure)

- [ ] **Step 3 : ajouter les migrations idempotentes des nouvelles colonnes**

⚠️ Le helper `_colonne_absente`/`_ajouter_colonne` a DÉJÀ été ajouté à ce fichier
en Task 2 Step 5 (pour la migration `enfants.sexe`) — NE LE REDÉFINIS PAS ici,
réutilise-le tel quel.

D'abord, remplace les 2 `CREATE TABLE IF NOT EXISTS` existants de `cellules` et
`placements` pour inclure directement les nouvelles colonnes (une base FRAÎCHE les
aura dès la création, sans jamais passer par une migration) :

```python
    c.execute("""CREATE TABLE IF NOT EXISTS cellules (
        monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        x REAL NOT NULL, y REAL NOT NULL, biome TEXT NOT NULL,
        ressources TEXT NOT NULL, voisins TEXT NOT NULL,
        ressources_stock TEXT NOT NULL DEFAULT '{}', niveau_technologie REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (monde_id, cellule_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS placements (
        enfant_id TEXT NOT NULL, monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        place_le TEXT, ne_au_tick INTEGER NOT NULL DEFAULT 0, vivant INTEGER NOT NULL DEFAULT 1,
        mort_au_tick INTEGER, PRIMARY KEY (enfant_id, monde_id))""")
```

Puis, juste après (le helper `_ajouter_colonne` gère le cas d'une base Sprint
A/B DÉJÀ existante, où `CREATE TABLE IF NOT EXISTS` ci-dessus ne touche pas une
table déjà créée sans ces colonnes) :

```python
    _ajouter_colonne(c, "placements", "ne_au_tick", "INTEGER NOT NULL DEFAULT 0")
    _ajouter_colonne(c, "placements", "vivant", "INTEGER NOT NULL DEFAULT 1")
    _ajouter_colonne(c, "placements", "mort_au_tick", "INTEGER")
    _ajouter_colonne(c, "cellules", "ressources_stock", "TEXT NOT NULL DEFAULT '{}'")
    _ajouter_colonne(c, "cellules", "niveau_technologie", "REAL NOT NULL DEFAULT 0.0")
```

- [ ] **Step 4 : modifier `creer_monde()` (seed le stock initial de ressources)**

```python
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
```

- [ ] **Step 5 : modifier `placer()`**

```python
def placer(monde_id: str, enfant_id: str, cellule_id: int, ne_au_tick: int = 0) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : l'appelant DOIT avoir déjà validé
    `monde_existe(cle_api, monde_id)` avant d'appeler cette fonction.

    `ne_au_tick` (Sprint C) : tick de l'horloge de ce monde au moment de cette
    naissance — 0 par défaut (placement sans notion de tick, ou monde jamais
    avancé). `vivant=1` toujours à la création d'un placement (une naissance ne
    peut pas naître déjà morte)."""
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO placements "
                   "(enfant_id, monde_id, cellule_id, place_le, ne_au_tick, vivant) "
                   "VALUES (?,?,?,?,?,1)",
                   (enfant_id, monde_id, cellule_id, datetime.now(timezone.utc).isoformat(), ne_au_tick))
```

- [ ] **Step 6 : ajouter les nouveaux accesseurs (à la fin du fichier, avant `forker_monde`)**

```python
def population_vivante_cellule(monde_id: str, cellule_id: int) -> list[dict]:
    """Habitants vivants placés sur cette cellule, avec leur sexe (Sprint C, voir
    stockage.py) et leur tick de naissance DANS ce monde — snapshot utilisé par
    l'horloge pour décider mortalité/couples/reproduction. ⚠️ Ne vérifie PAS
    `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        rows = c.execute(
            "SELECT e.id AS id, e.sexe AS sexe, p.ne_au_tick AS ne_au_tick "
            "FROM placements p JOIN enfants e ON p.enfant_id = e.id "
            "WHERE p.monde_id=? AND p.cellule_id=? AND p.vivant=1",
            (monde_id, cellule_id)).fetchall()
    return [{"id": r["id"], "sexe": r["sexe"], "ne_au_tick": r["ne_au_tick"]} for r in rows]


def deplacer_placement(monde_id: str, enfant_id: str, nouvelle_cellule_id: int) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        c.execute("UPDATE placements SET cellule_id=? WHERE monde_id=? AND enfant_id=?",
                   (nouvelle_cellule_id, monde_id, enfant_id))


def marquer_mort(monde_id: str, enfant_id: str, tick: int) -> None:
    """⚠️ Ne vérifie PAS `cle_api` : même motif que le reste de ce module."""
    with _conn() as c:
        c.execute("UPDATE placements SET vivant=0, mort_au_tick=? WHERE monde_id=? AND enfant_id=?",
                   (tick, monde_id, enfant_id))


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
```

- [ ] **Step 7 : étendre `forker_monde()` pour copier les nouvelles colonnes**

Remplace le corps de `forker_monde()` :

```python
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
            "ne_au_tick, vivant, mort_au_tick) VALUES (?,?,?,?,?,?,?)",
            [(r["enfant_id"], nid, r["cellule_id"], r["place_le"], r["ne_au_tick"],
              r["vivant"], r["mort_au_tick"]) for r in placements])
    return {"id": nid, "nb_cellules": m["nb_cellules"], "seed": m["seed"],
            "forked_from_id": monde_id, "cree_le": cree_le}
```

- [ ] **Step 8 : exposer les nouveaux champs dans `_cellule_dict()`**

```python
def _cellule_dict(r: sqlite3.Row, enfants: list[dict]) -> dict:
    return {"cellule_id": r["cellule_id"], "x": r["x"], "y": r["y"], "biome": r["biome"],
            "ressources": json.loads(r["ressources"]), "voisins": json.loads(r["voisins"]),
            "ressources_stock": json.loads(r["ressources_stock"]),
            "niveau_technologie": r["niveau_technologie"],
            "enfants": enfants}
```

- [ ] **Step 9 : lancer tous les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_stockage_spatial.py -v`
Expected: PASS (tests existants + nouveaux)

- [ ] **Step 10 : commit**

```bash
git add briques/world-engine/stockage_spatial.py briques/world-engine/test_stockage_spatial.py
git commit -m "feat(world-engine): stockage_spatial.py — âge/mortalité par placement, ressources+technologie par cellule"
```

---

### Task 5: `horloge.py` — mécanique pure du tick

**Files:**
- Create: `briques/world-engine/horloge.py`
- Test: `briques/world-engine/test_horloge.py`

**Interfaces:**
- Consumes : `spatial.TAILLE_MONDE` (import, pour `derive_position_naissance`).
- Produces : `evoluer_ressources_et_technologie`, `meurt`, `cellule_saturee`, `migre`, `est_adulte_fecond`, `former_couples`, `dissout`, `tente_naissance_couple`, `tenter_rencontres_occasionnelles`, `derive_position_naissance`, `derive_heure_et_offset`, `tirer_sexe` — tous consommés par `horloge_moteur.py` (Task 6).

- [ ] **Step 1 : écrire les tests qui échouent**

Crée `briques/world-engine/test_horloge.py` :

```python
"""Tests de la mécanique pure du tick (Sprint C) — aucune I/O, RNG toujours
seedé explicitement en paramètre (même motif que test_fusion.py/test_spatial.py)."""
from random import Random

import horloge


def test_evoluer_ressources_et_technologie_regenere_et_consomme():
    stock, niveau, consomme = horloge.evoluer_ressources_et_technologie(
        {"ble": 40.0}, niveau_technologie=0.0, population_vivante=5)
    assert 0.0 <= stock["ble"] <= horloge.PLAFOND_RESSOURCE
    assert consomme > 0
    assert niveau > 0.0


def test_evoluer_ressources_stock_vide_ne_plante_pas():
    stock, niveau, consomme = horloge.evoluer_ressources_et_technologie(
        {}, niveau_technologie=1.0, population_vivante=10)
    assert stock == {}
    assert consomme == 0.0
    assert niveau == 1.0


def test_evoluer_ressources_borne_au_plafond_technologie():
    _, niveau, _ = horloge.evoluer_ressources_et_technologie(
        {"ble": 100.0}, niveau_technologie=horloge.PLAFOND_TECHNOLOGIE, population_vivante=1000)
    assert niveau == horloge.PLAFOND_TECHNOLOGIE


def test_meurt_jamais_avant_age_adulte_min():
    rng = Random(1)
    assert horloge.meurt(age=horloge.AGE_ADULTE_MIN - 1, niveau_technologie=0.0, rng=rng) is False


def test_meurt_deterministe_avec_seed_fixe():
    a = horloge.meurt(age=80, niveau_technologie=0.0, rng=Random(42))
    b = horloge.meurt(age=80, niveau_technologie=0.0, rng=Random(42))
    assert a == b


def test_meurt_moins_probable_avec_plus_de_technologie():
    rng_sans_tech = Random(7)
    rng_avec_tech = Random(7)
    resultats_sans_tech = [horloge.meurt(90, 0.0, rng_sans_tech) for _ in range(200)]
    resultats_avec_tech = [horloge.meurt(90, 5.0, rng_avec_tech) for _ in range(200)]
    assert sum(resultats_avec_tech) < sum(resultats_sans_tech)


def test_cellule_saturee():
    assert horloge.cellule_saturee(population_vivante=10, stock={"ble": 5.0}) is True
    assert horloge.cellule_saturee(population_vivante=2, stock={"ble": 50.0}) is False


def test_est_adulte_fecond():
    assert horloge.est_adulte_fecond(horloge.AGE_ADULTE_MIN) is True
    assert horloge.est_adulte_fecond(horloge.AGE_ADULTE_MIN - 1) is False
    assert horloge.est_adulte_fecond(horloge.AGE_FECONDITE_MAX + 1) is False


def test_former_couples_appariement_borne_par_le_plus_petit_groupe():
    couples = horloge.former_couples(["f1", "f2", "f3"], ["m1"], Random(1))
    assert len(couples) <= 1


def test_former_couples_deterministe():
    a = horloge.former_couples(["f1", "f2"], ["m1", "m2"], Random(5))
    b = horloge.former_couples(["f1", "f2"], ["m1", "m2"], Random(5))
    assert a == b


def test_tenter_rencontres_occasionnelles_moins_probable_que_couples():
    f, m = [f"f{i}" for i in range(50)], [f"m{i}" for i in range(50)]
    couples = horloge.former_couples(f, m, Random(1))
    rencontres = horloge.tenter_rencontres_occasionnelles(f, m, Random(1))
    assert len(rencontres) < len(couples)


def test_derive_position_naissance_dans_les_bornes_valides():
    lat, lon = horloge.derive_position_naissance(0.0, 0.0)
    assert lat == -90.0 and lon == -180.0
    lat, lon = horloge.derive_position_naissance(horloge.TAILLE_MONDE, horloge.TAILLE_MONDE)
    assert lat == 90.0 and lon == 180.0


def test_derive_heure_et_offset_format_valide():
    heure, offset = horloge.derive_heure_et_offset(Random(1))
    h, m = heure.split(":")
    assert 0 <= int(h) < 24 and 0 <= int(m) < 60
    assert -12 <= offset <= 12


def test_tirer_sexe_deterministe():
    assert horloge.tirer_sexe(Random(1)) == horloge.tirer_sexe(Random(1))
    assert horloge.tirer_sexe(Random(1)) in ("F", "M")
```

- [ ] **Step 2 : lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python -m pytest test_horloge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'horloge'`

- [ ] **Step 3 : écrire `horloge.py`**

```python
"""Mécanique pure du tick de simulation (Sprint C) : ressources/technologie,
mortalité, migration, couples, reproduction — aucune I/O, aucune dépendance à
sqlite/fastapi/httpx (même esprit que spatial.py/fusion.py). Le RNG est TOUJOURS
reçu en paramètre (jamais de module `random` global) pour un déterminisme
reproductible par (seed, tick, cellule) — voir horloge_moteur.py."""
from __future__ import annotations

from random import Random

from spatial import TAILLE_MONDE

# --- Ressources / technologie ---
PLAFOND_RESSOURCE = 100.0
TAUX_REGENERATION = 0.10          # fraction du manque au plafond regagnée par tick
CONSOMMATION_PAR_HABITANT = 1.0   # unités consommées par habitant vivant et par tick,
                                    # réparties également entre les ressources présentes
TAUX_PROGRESSION_TECH = 0.01      # niveau_technologie gagné par unité de ressource consommée
PLAFOND_TECHNOLOGIE = 10.0

# --- Âge / mortalité ---
AGE_ADULTE_MIN = 16
AGE_FECONDITE_MAX = 45
AGE_MORTALITE_MIN = 50
MORTALITE_BASE_ADULTE = 0.005     # risque plancher entre AGE_ADULTE_MIN et AGE_MORTALITE_MIN
MORTALITE_PENTE = 0.02            # + de risque par année au-delà de AGE_MORTALITE_MIN

# --- Migration ---
SEUIL_SATURATION_RATIO = 1.0      # population > stock total des ressources ⇒ saturé
PROBABILITE_MIGRATION_SI_SATURE = 0.20

# --- Couples / reproduction ---
PROBABILITE_FORMATION_COUPLE = 0.30
PROBABILITE_DISSOLUTION_COUPLE = 0.05
PROBABILITE_NAISSANCE_COUPLE = 0.25
PROBABILITE_NAISSANCE_ACCIDENT = 0.03  # « rencontre occasionnelle » hors couple, plus rare


def evoluer_ressources_et_technologie(stock: dict, niveau_technologie: float,
                                        population_vivante: int) -> tuple[dict, float, float]:
    """Régénère chaque ressource d'une fraction du manque au plafond, puis retire une
    consommation proportionnelle à la population vivante (répartie également entre
    les ressources présentes) ; le total consommé alimente la progression
    technologique. Bornes : stock dans [0, PLAFOND_RESSOURCE], technologie dans
    [0, PLAFOND_TECHNOLOGIE]. Renvoie (nouveau_stock, nouveau_niveau, consomme_reel)."""
    if not stock:
        return {}, min(niveau_technologie, PLAFOND_TECHNOLOGIE), 0.0
    consommation_totale = population_vivante * CONSOMMATION_PAR_HABITANT
    part_par_ressource = consommation_totale / len(stock)
    nouveau_stock = {}
    consomme_reel = 0.0
    for nom, quantite in stock.items():
        regenere = quantite + (PLAFOND_RESSOURCE - quantite) * TAUX_REGENERATION
        consomme = min(regenere, part_par_ressource)
        nouveau_stock[nom] = max(0.0, min(PLAFOND_RESSOURCE, regenere - consomme))
        consomme_reel += consomme
    nouveau_niveau = min(PLAFOND_TECHNOLOGIE, niveau_technologie + consomme_reel * TAUX_PROGRESSION_TECH)
    return nouveau_stock, nouveau_niveau, consomme_reel


def meurt(age: int, niveau_technologie: float, rng: Random) -> bool:
    """Probabilité de mort ce tick : nulle avant AGE_ADULTE_MIN (les enfants ne
    meurent pas dans ce modèle simple), risque plancher constant jusqu'à
    AGE_MORTALITE_MIN, puis croissant avec l'âge — réduit par le niveau de
    technologie de la cellule (plus de technologie ⇒ espérance de vie plus longue)."""
    if age < AGE_ADULTE_MIN:
        return False
    if age < AGE_MORTALITE_MIN:
        base = MORTALITE_BASE_ADULTE
    else:
        base = MORTALITE_BASE_ADULTE + MORTALITE_PENTE * (age - AGE_MORTALITE_MIN)
    proba = min(0.95, base / (1.0 + niveau_technologie))
    return rng.random() < proba


def cellule_saturee(population_vivante: int, stock: dict) -> bool:
    """Une cellule est saturée si sa population vivante dépasse son stock total de
    ressources restantes — pousse la migration (étape suivante du tick)."""
    return population_vivante > sum(stock.values()) * SEUIL_SATURATION_RATIO


def migre(rng: Random) -> bool:
    return rng.random() < PROBABILITE_MIGRATION_SI_SATURE


def est_adulte_fecond(age: int) -> bool:
    return AGE_ADULTE_MIN <= age <= AGE_FECONDITE_MAX


def former_couples(celibataires_f: list, celibataires_m: list, rng: Random) -> list[tuple[str, str]]:
    """Apparie au hasard des célibataires F/M (ordre mélangé, un habitant entre au
    plus dans un nouveau couple ce tick — bornée par le plus petit des 2 groupes) ;
    chaque paire candidate a une probabilité indépendante de former un couple — le
    hasard/destin plutôt qu'un appariement systématique."""
    f, m = list(celibataires_f), list(celibataires_m)
    rng.shuffle(f)
    rng.shuffle(m)
    return [(a, b) for a, b in zip(f, m) if rng.random() < PROBABILITE_FORMATION_COUPLE]


def dissout(rng: Random) -> bool:
    return rng.random() < PROBABILITE_DISSOLUTION_COUPLE


def tente_naissance_couple(rng: Random) -> bool:
    return rng.random() < PROBABILITE_NAISSANCE_COUPLE


def tenter_rencontres_occasionnelles(celibataires_f: list, celibataires_m: list,
                                       rng: Random) -> list[tuple[str, str]]:
    """Rencontres hors couple (« accident ») : même règle d'appariement que
    `former_couples`, probabilité bien plus faible, et ne forme jamais de couple
    persistant — seulement une tentative de naissance isolée ce tick."""
    f, m = list(celibataires_f), list(celibataires_m)
    rng.shuffle(f)
    rng.shuffle(m)
    return [(a, b) for a, b in zip(f, m) if rng.random() < PROBABILITE_NAISSANCE_ACCIDENT]


def derive_position_naissance(x: float, y: float) -> tuple[float, float]:
    """Convertit la position (x, y) d'une cellule (espace [0, TAILLE_MONDE]²) en
    latitude/longitude valides — déterministe, sans signification géographique
    réelle : seulement des coordonnées valides à fournir à `personnages` pour une
    naissance automatique, où aucun humain ne peut en fournir (voir design)."""
    latitude = (y / TAILLE_MONDE) * 180.0 - 90.0
    longitude = (x / TAILLE_MONDE) * 360.0 - 180.0
    return latitude, longitude


def derive_heure_et_offset(rng: Random) -> tuple[str, float]:
    """Heure de naissance et décalage UTC tirés du RNG seedé du monde — aucun
    humain ne peut les fournir pour une naissance automatique."""
    heure = rng.randrange(0, 24)
    minute = rng.randrange(0, 60)
    utc_offset = float(rng.randrange(-12, 13))
    return f"{heure:02d}:{minute:02d}", utc_offset


def tirer_sexe(rng: Random) -> str:
    return rng.choice(["F", "M"])
```

- [ ] **Step 4 : lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_horloge.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5 : commit**

```bash
git add briques/world-engine/horloge.py briques/world-engine/test_horloge.py
git commit -m "feat(world-engine): horloge.py — mécanique pure du tick (ressources/mortalité/migration/couples/naissances)"
```

---

### Task 6: `horloge_moteur.py` — orchestrateur `executer_tick`

**Files:**
- Create: `briques/world-engine/horloge_moteur.py`
- Test: `briques/world-engine/test_horloge_moteur.py`

**Interfaces:**
- Consumes : `horloge.*` (Task 5), `stockage_spatial.*` (Task 4), `stockage_horloge.*` (Task 3), `genome_moteur.Croisement`/`ReferenceParent`/`executer_croisement` (Task 1/2).
- Produces : `async def executer_tick(monde_id: str, cle_api_val: str) -> dict` — consommé par `main.py` (Task 7, route manuelle ET scheduler).

- [ ] **Step 1 : écrire le test qui échoue (scénario simple, sans naissance)**

Crée `briques/world-engine/test_horloge_moteur.py` :

```python
"""Tests d'intégration de l'orchestrateur de tick (Sprint C) — DB réelle (même
motif que test_api.py), appels `personnages` mockés via respx quand une
naissance est tentée."""
import httpx
import pytest
import respx

import genome_moteur
import horloge_moteur
import stockage
import stockage_horloge
import stockage_spatial

PERSONNAGES_URL = "http://host.docker.internal:5900"


def _monde_avec_habitants(cle_api: str, n_cellules=2):
    cellules = [{"cellule_id": i, "x": float(i) * 100, "y": 500.0, "biome": "plaine",
                 "ressources": ["ble"], "voisins": [j for j in range(n_cellules) if j != i]}
                for i in range(n_cellules)]
    monde = stockage_spatial.creer_monde(cle_api, cellules, seed=42)
    stockage_horloge.initialiser_horloge(monde["id"])
    return monde


def _ajouter_habitant(cle_api: str, monde_id: str, cellule_id: int, sexe: str,
                       ne_au_tick: int = 0, theme: dict | None = None) -> str:
    """`theme` : dict au format portrait/theme_complet réel (voir PORTRAIT_FACTICE
    plus bas) SI cet habitant sera utilisé comme parent d'un croisement (via
    ReferenceParent) dans le test — sinon un dict vide suffit (jamais lu par la
    mécanique de tick elle-même, qui ne connaît qu'id/sexe/ne_au_tick, voir
    stockage_spatial.population_vivante_cellule)."""
    eid = stockage.creer(cle_api, "H", "X", None, None, theme or {}, "d", {}, False, sexe=sexe)
    stockage_spatial.placer(monde_id, eid, cellule_id, ne_au_tick=ne_au_tick)
    return eid


PORTRAIT_FACTICE = {
    "traditions": {"signe_solaire": {"nom": "Vierge"}},
    "portrait": {"archetype": "A", "forces": ["X", "Y"], "faiblesse": "Z"},
    "theme_complet": {
        "dominantes": {"planete": {"dominante": "Mercure"}, "signe": {"dominant": "Vierge"}},
        "dix_corps": {c: {"signe": "Vierge"} for c in
                      ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                       "Saturne", "Uranus", "Neptune", "Pluton"]},
    },
    "empreinte": [], "glossaire": [],
}


@pytest.mark.asyncio
async def test_tick_sans_habitants_avance_juste_le_compteur():
    monde = _monde_avec_habitants("cle-tk1")
    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk1")
    assert resultat["tick_actuel"] == 1
    assert resultat["naissances"] == 0
    assert resultat["morts"] == 0
    assert stockage_horloge.lire_horloge(monde["id"])["tick_actuel"] == 1


@pytest.mark.asyncio
async def test_tick_monde_introuvable_leve_404():
    with pytest.raises(genome_moteur.HTTPException) as exc:
        await horloge_moteur.executer_tick("id-inconnu", "cle-tk2")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_tick_regenere_ressources_et_progresse_technologie():
    monde = _monde_avec_habitants("cle-tk3")
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 10.0})
    _ajouter_habitant("cle-tk3", monde["id"], 0, "F", ne_au_tick=0)
    await horloge_moteur.executer_tick(monde["id"], "cle-tk3")
    stock_apres = stockage_spatial.lire_ressources_stock(monde["id"], 0)
    assert stock_apres["ble"] != 10.0  # a régénéré/consommé
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) >= 0.0


@pytest.mark.asyncio
async def test_tick_ne_tue_jamais_un_enfant_trop_jeune():
    monde = _monde_avec_habitants("cle-tk4")
    eid = _ajouter_habitant("cle-tk4", monde["id"], 0, "F", ne_au_tick=0)
    # 1 seul tick : âge = 1 << AGE_ADULTE_MIN, ne doit jamais mourir
    resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk4")
    assert resultat["morts"] == 0
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0)[0]["id"] == eid


@respx.mock
@pytest.mark.asyncio
async def test_tick_naissance_couple_appelle_genome_moteur():
    monde = _monde_avec_habitants("cle-tk5")
    from horloge import PLAFOND_RESSOURCE
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": PLAFOND_RESSOURCE})
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    # ne_au_tick=-20 : simule un couple déjà adulte fécondable (âge > AGE_ADULTE_MIN=16)
    # dès le 1er tick, sans avoir à faire tourner des dizaines de ticks de vieillissement.
    # `theme=PORTRAIT_FACTICE` : ces 2 habitants seront réellement croisés via
    # ReferenceParent — leur `theme` stocké doit donc être portrait-shaped (lu par
    # genome_moteur._theme_parent puis fusion.fusionner_description).
    a = _ajouter_habitant("cle-tk5", monde["id"], 0, "F", ne_au_tick=-20, theme=PORTRAIT_FACTICE)
    b = _ajouter_habitant("cle-tk5", monde["id"], 0, "M", ne_au_tick=-20, theme=PORTRAIT_FACTICE)
    # Couple déjà actif AVANT ce tick (créé directement, pas via l'étape 5 du tick) :
    # un couple tout juste formé PAR le tick ne tente jamais une naissance ce même
    # tick (voir design/horloge_moteur.py) — il faut donc préexister à l'appel.
    stockage_horloge.former_couple(monde["id"], 0, a, b, tick=0)

    naissance_observee = False
    for _ in range(30):
        resultat = await horloge_moteur.executer_tick(monde["id"], "cle-tk5")
        if resultat["naissances"] > 0:
            naissance_observee = True
            break
    assert naissance_observee
```

- [ ] **Step 2 : lancer le test, vérifier qu'il échoue**

`pytest-asyncio` est déjà le socle de test async de ce monorepo (fourni par
`scripts/tests_briques.sh`, déjà utilisé dans `briques/world-engine/test_personnages_client.py`
via `@pytest.mark.asyncio`) — aucune nouvelle dépendance à ajouter.

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'horloge_moteur'`

- [ ] **Step 3 : écrire `horloge_moteur.py`**

```python
"""Orchestrateur du tick de simulation (Sprint C) : exécute un tick complet sur
un monde. Lit un instantané figé de l'état en DÉBUT de tick (population, stocks,
technologie, couples), applique la mécanique pure de `horloge.py` cellule par
cellule SUR CET INSTANTANÉ (jamais de re-lecture après une écriture DANS le même
tick — un habitant n'est traité qu'une seule fois par tick, voir design), déclenche
les naissances via `genome_moteur.executer_croisement`, puis applique toutes les
écritures en une dernière phase. Chaque groupe d'écritures est isolé : une erreur
n'interrompt jamais le reste du tick (repli honnête, même motif que Sprint A/B)."""
from __future__ import annotations

from random import Random

from fastapi import HTTPException

import genome_moteur
import horloge
import stockage_horloge
import stockage_spatial

ANNEE_BASE_HORLOGE = 2000  # année narrative de départ pour les naissances automatiques —
                            # sans lien avec l'année réelle, juste une base valide pour
                            # calculer un thème astral (voir genome_moteur.Croisement.annee_enfant)


def _rng(seed: int, tick: int, cellule_id: int, etape: str) -> Random:
    return Random(f"{seed}:{tick}:{cellule_id}:{etape}")


async def executer_tick(monde_id: str, cle_api_val: str) -> dict:
    horloge_etat = stockage_horloge.lire_horloge(monde_id)
    if horloge_etat is None:
        raise HTTPException(404, f"Horloge du monde '{monde_id}' introuvable.")
    tick_suivant = horloge_etat["tick_actuel"] + 1

    monde = stockage_spatial.lire_monde(cle_api_val, monde_id)
    if monde is None:
        raise HTTPException(404, f"Monde '{monde_id}' introuvable.")
    seed = monde["seed"]

    avertissements: list[str] = []
    naissances = morts = migrations = couples_formes = couples_dissous = 0
    niveaux_tech: list[float] = []

    # --- Phase 1 : instantané figé du monde en début de tick ---
    population = {}
    stocks = {}
    niveaux = {}
    couples_par_cellule = {}
    for cel in monde["cellules"]:
        cid = cel["cellule_id"]
        population[cid] = stockage_spatial.population_vivante_cellule(monde_id, cid)
        stocks[cid] = stockage_spatial.lire_ressources_stock(monde_id, cid)
        niveaux[cid] = stockage_spatial.lire_niveau_technologie(monde_id, cid)
        couples_par_cellule[cid] = stockage_horloge.couples_actifs_cellule(monde_id, cid)

    # --- Phase 2 : calcul pur (aucune écriture encore) ---
    nouveaux_stocks, nouveaux_niveaux = {}, {}
    morts_a_appliquer: list[str] = []
    migrations_a_appliquer: list[tuple[str, int]] = []
    couples_a_dissoudre: list[str] = []
    couples_a_former: list[tuple[int, str, str]] = []
    naissances_a_tenter: list[tuple[int, str, str, str, str]] = []  # cid, a, b, sexe_a, sexe_b

    for cel in sorted(monde["cellules"], key=lambda c: c["cellule_id"]):
        cid = cel["cellule_id"]
        pop = population[cid]

        # 1) Ressources + 2) Technologie
        rng_r = _rng(seed, tick_suivant, cid, "ressources")
        nouveau_stock, nouveau_niveau, _ = horloge.evoluer_ressources_et_technologie(
            stocks[cid], niveaux[cid], len(pop))
        nouveaux_stocks[cid] = nouveau_stock
        nouveaux_niveaux[cid] = nouveau_niveau
        niveaux_tech.append(nouveau_niveau)

        # 3) Mortalité
        rng_m = _rng(seed, tick_suivant, cid, "mortalite")
        vivants = []
        for h in pop:
            age = tick_suivant - h["ne_au_tick"]
            if horloge.meurt(age, niveaux[cid], rng_m):
                morts_a_appliquer.append(h["id"])
            else:
                vivants.append(h)

        # 4) Migration — décidée sur l'état du DÉBUT de tick ; un habitant qui migre
        # reste éligible couples/reproduction dans SA cellule d'origine ce même tick.
        rng_mig = _rng(seed, tick_suivant, cid, "migration")
        if cel["voisins"] and horloge.cellule_saturee(len(vivants), stocks[cid]):
            for h in vivants:
                if horloge.migre(rng_mig):
                    migrations_a_appliquer.append((h["id"], rng_mig.choice(cel["voisins"])))
                    migrations += 1

        # 5) Couples : dissolution puis formation
        rng_c = _rng(seed, tick_suivant, cid, "couples")
        actifs = couples_par_cellule[cid]
        dissous_ici = [c for c in actifs if horloge.dissout(rng_c)]
        couples_a_dissoudre.extend(c["id"] for c in dissous_ici)
        couples_dissous += len(dissous_ici)
        dissous_ids = {c["id"] for c in dissous_ici}
        deja_en_couple = ({c["habitant_a_id"] for c in actifs if c["id"] not in dissous_ids} |
                           {c["habitant_b_id"] for c in actifs if c["id"] not in dissous_ids})

        vivants_par_id = {h["id"]: h for h in vivants}
        celibataires_f = [h["id"] for h in vivants if h["sexe"] == "F"
                           and h["id"] not in deja_en_couple
                           and horloge.est_adulte_fecond(tick_suivant - h["ne_au_tick"])]
        celibataires_m = [h["id"] for h in vivants if h["sexe"] == "M"
                           and h["id"] not in deja_en_couple
                           and horloge.est_adulte_fecond(tick_suivant - h["ne_au_tick"])]
        nouveaux = horloge.former_couples(celibataires_f, celibataires_m, rng_c)
        couples_a_former.extend((cid, a, b) for a, b in nouveaux)
        couples_formes += len(nouveaux)
        nouvellement_pris = {a for a, _ in nouveaux} | {b for _, b in nouveaux}

        # 6) Reproduction — SEULS les couples déjà actifs AVANT ce tick tentent une
        # naissance (les couples formés à l'étape 5 ci-dessus attendent le tick
        # suivant — évite "formé et déjà parent le même tick").
        rng_n = _rng(seed, tick_suivant, cid, "naissances")
        for c in actifs:
            if c["id"] in dissous_ids:
                continue
            ha, hb = vivants_par_id.get(c["habitant_a_id"]), vivants_par_id.get(c["habitant_b_id"])
            if (ha and hb
                    and horloge.est_adulte_fecond(tick_suivant - ha["ne_au_tick"])
                    and horloge.est_adulte_fecond(tick_suivant - hb["ne_au_tick"])
                    and horloge.tente_naissance_couple(rng_n)):
                naissances_a_tenter.append((cid, ha["id"], hb["id"], ha["sexe"], hb["sexe"]))

        restants_f = [i for i in celibataires_f if i not in nouvellement_pris]
        restants_m = [i for i in celibataires_m if i not in nouvellement_pris]
        for a, b in horloge.tenter_rencontres_occasionnelles(restants_f, restants_m, rng_n):
            naissances_a_tenter.append((cid, a, b, "F", "M"))

    # --- Phase 3 : application des écritures (chaque groupe isolé) ---
    for cid, stock in nouveaux_stocks.items():
        try:
            stockage_spatial.ecrire_ressources_stock(monde_id, cid, stock)
            stockage_spatial.ecrire_niveau_technologie(monde_id, cid, nouveaux_niveaux[cid])
        except Exception as e:
            avertissements.append(f"Cellule {cid} : ressources/technologie non écrites : {e}")

    for enfant_id in morts_a_appliquer:
        try:
            stockage_spatial.marquer_mort(monde_id, enfant_id, tick_suivant)
            morts += 1
        except Exception as e:
            avertissements.append(f"Mort de {enfant_id} non appliquée : {e}")

    for enfant_id, nouvelle_cellule in migrations_a_appliquer:
        try:
            stockage_spatial.deplacer_placement(monde_id, enfant_id, nouvelle_cellule)
        except Exception as e:
            avertissements.append(f"Migration de {enfant_id} non appliquée : {e}")

    for couple_id in couples_a_dissoudre:
        try:
            stockage_horloge.dissoudre_couple(couple_id, tick_suivant)
        except Exception as e:
            avertissements.append(f"Dissolution du couple {couple_id} non appliquée : {e}")

    for cid, a, b in couples_a_former:
        try:
            stockage_horloge.former_couple(monde_id, cid, a, b, tick_suivant)
        except Exception as e:
            avertissements.append(f"Formation du couple {a}/{b} non appliquée : {e}")

    cellules_par_id = {c["cellule_id"]: c for c in monde["cellules"]}
    for cid, a, b, sexe_a, sexe_b in naissances_a_tenter:
        rng_naissance = _rng(seed, tick_suivant, cid, f"naissance:{a}:{b}")
        cellule = cellules_par_id[cid]
        latitude, longitude = horloge.derive_position_naissance(cellule["x"], cellule["y"])
        heure, utc_offset = horloge.derive_heure_et_offset(rng_naissance)
        corps = genome_moteur.Croisement(
            parent_a=genome_moteur.ReferenceParent(id=a, sexe=sexe_a),
            parent_b=genome_moteur.ReferenceParent(id=b, sexe=sexe_b),
            prenoms_enfant="", nom_enfant="",
            latitude_enfant=latitude, longitude_enfant=longitude,
            heure_naissance_enfant=heure, utc_offset_enfant=utc_offset,
            annee_enfant=min(9999, ANNEE_BASE_HORLOGE + tick_suivant),
            sexe_enfant=horloge.tirer_sexe(rng_naissance),
            monde_id=monde_id,
        )
        try:
            await genome_moteur.executer_croisement(corps, cle_api_val)
            naissances += 1
        except HTTPException as e:
            avertissements.append(f"Naissance {a}/{b} non aboutie : {e.detail}")
        except Exception as e:
            avertissements.append(f"Naissance {a}/{b} non aboutie : {e}")

    stockage_horloge.marquer_execution(monde_id, tick_suivant)

    return {
        "monde_id": monde_id, "tick_actuel": tick_suivant,
        "naissances": naissances, "morts": morts, "migrations": migrations,
        "couples_formes": couples_formes, "couples_dissous": couples_dissous,
        "niveau_technologie_moyen": (sum(niveaux_tech) / len(niveaux_tech)) if niveaux_tech else 0.0,
        "avertissements": avertissements,
    }
```

- [ ] **Step 4 : lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5 : lancer toute la suite pour vérifier l'absence de régression**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 6 : commit**

```bash
git add briques/world-engine/horloge_moteur.py briques/world-engine/test_horloge_moteur.py
git commit -m "feat(world-engine): horloge_moteur.py — orchestrateur du tick (executer_tick)"
```

---

### Task 7: Routes `/horloge`, wiring monde, scheduler in-process

**Files:**
- Modify: `briques/world-engine/main.py` (imports, `spatial_monde_creer`/`spatial_monde_forker`/`spatial_monde_supprimer`, nouvelles routes `/horloge`, scheduler)
- Modify: `briques/world-engine/conftest.py` (désactiver le scheduler en test)
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes : `stockage_horloge.*` (Task 3), `horloge_moteur.executer_tick` (Task 6).
- Produces : routes HTTP `/horloge/{mid}/tick`, `/horloge/{mid}/demarrer`, `/horloge/{mid}/arreter`, `GET /horloge/{mid}` — consommées par le manifest (Task 8) et par les utilisateurs finaux de la brique.

- [ ] **Step 1 : désactiver le scheduler pendant les tests**

Dans `briques/world-engine/conftest.py`, ajoute :

```python
os.environ.setdefault("HORLOGE_SCHEDULER_DESACTIVE", "1")  # jamais de boucle de fond réelle en test
```

- [ ] **Step 2 : écrire les tests API qui échouent**

Ajoute à `test_api.py` :

```python
def test_horloge_monde_a_une_horloge_des_sa_creation():
    r = client.post("/spatial/mondes", json={"nb_cellules": 10})
    mid = r.json()["id"]
    etat = client.get(f"/horloge/{mid}").json()
    assert etat == {"monde_id": mid, "tick_actuel": 0, "actif": False,
                     "intervalle_secondes": None, "derniere_execution": None}


def test_horloge_tick_manuel_avance_le_compteur():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    resultat = client.post(f"/horloge/{mid}/tick").json()
    assert resultat["tick_actuel"] == 1
    assert client.get(f"/horloge/{mid}").json()["tick_actuel"] == 1


def test_horloge_tick_monde_introuvable_404():
    r = client.post("/horloge/id-inconnu/tick")
    assert r.status_code == 404


def test_horloge_demarrer_puis_arreter():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    r = client.post(f"/horloge/{mid}/demarrer", json={"intervalle_secondes": 60})
    assert r.status_code == 200
    assert r.json()["actif"] is True
    r = client.post(f"/horloge/{mid}/arreter")
    assert r.json()["actif"] is False


def test_horloge_demarrer_intervalle_hors_bornes_422():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    r = client.post(f"/horloge/{mid}/demarrer", json={"intervalle_secondes": 1})
    assert r.status_code == 422


def test_horloge_fork_reprend_tick_mais_reste_inactif():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    client.post(f"/horloge/{mid}/tick")
    client.post(f"/horloge/{mid}/tick")
    fork_id = client.post(f"/spatial/mondes/{mid}/forker").json()["id"]
    etat_fork = client.get(f"/horloge/{fork_id}").json()
    assert etat_fork["tick_actuel"] == 2
    assert etat_fork["actif"] is False


def test_horloge_supprimer_monde_purge_horloge():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10}).json()["id"]
    client.delete(f"/spatial/mondes/{mid}")
    assert client.get(f"/horloge/{mid}").status_code == 404
```

- [ ] **Step 3 : lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python -m pytest test_api.py -k horloge -v`
Expected: FAIL — `404` génériques FastAPI (route inexistante) au lieu des réponses attendues

- [ ] **Step 4 : ajouter les imports et le modèle dans `main.py`**

En tête de `main.py`, ajoute :

```python
import asyncio
from datetime import datetime, timezone

import horloge_moteur
import stockage_horloge
```

Ajoute le modèle de requête (à côté de `CreerMonde`) :

```python
class DemarrerHorloge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervalle_secondes: int = Field(ge=5, le=86400)
```

- [ ] **Step 5 : wirer la création/le fork/la suppression de monde**

Remplace `spatial_monde_creer` :

```python
@app.post("/spatial/mondes", tags=["spatial"])
def spatial_monde_creer(body: CreerMonde, _cle: str = Depends(cle_api)):
    """Génère et persiste un nouveau monde : maillage Voronoï, biomes/ressources
    dérivés d'un bruit cohérent. `seed` généré si absent (renvoyé dans la réponse,
    même (nb_cellules, seed) ⇒ même monde). Un monde a TOUJOURS une horloge
    (Sprint C), en tick manuel par défaut."""
    seed = body.seed if body.seed is not None else Random().randrange(2**31)
    cellules = spatial.generer_monde(body.nb_cellules, seed)
    monde = stockage_spatial.creer_monde(_cle, cellules, seed)
    stockage_horloge.initialiser_horloge(monde["id"])
    return monde
```

Remplace `spatial_monde_forker` :

```python
@app.post("/spatial/mondes/{mid}/forker", tags=["spatial"])
def spatial_monde_forker(mid: str, _cle: str = Depends(cle_api)):
    """Clone un monde existant (cellules + enfants placés) sous un nouvel id
    indépendant. Le monde source n'est jamais modifié. L'horloge du fork reprend
    le tick du monde source mais reste inactive (Sprint C)."""
    nouveau = stockage_spatial.forker_monde(_cle, mid)
    if nouveau is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.copier_pour_fork(mid, nouveau["id"])
    return nouveau
```

Remplace `spatial_monde_supprimer` :

```python
@app.delete("/spatial/mondes/{mid}", status_code=204, tags=["spatial"])
def spatial_monde_supprimer(mid: str, _cle: str = Depends(cle_api)):
    if not stockage_spatial.supprimer_monde(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.supprimer_pour_monde(mid)
```

- [ ] **Step 6 : ajouter les routes `/horloge`**

Ajoute à la fin de `main.py` :

```python
@app.post("/horloge/{mid}/tick", tags=["horloge"])
async def horloge_tick(mid: str, _cle: str = Depends(cle_api)):
    """Avance manuellement ce monde d'exactement 1 tick (1 an narratif) — voir
    `horloge_moteur.executer_tick` pour le détail de la mécanique."""
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return await horloge_moteur.executer_tick(mid, _cle)


@app.post("/horloge/{mid}/demarrer", tags=["horloge"])
def horloge_demarrer(mid: str, body: DemarrerHorloge, _cle: str = Depends(cle_api)):
    """Active l'avancement automatique de ce monde (scheduler in-process, opt-in).
    Un monde nouvellement créé ou forké reste en tick manuel tant que cet endpoint
    n'est pas appelé."""
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.demarrer(mid, body.intervalle_secondes)
    return stockage_horloge.lire_horloge(mid)


@app.post("/horloge/{mid}/arreter", tags=["horloge"])
def horloge_arreter(mid: str, _cle: str = Depends(cle_api)):
    """Désactive l'avancement automatique (les ticks déjà passés restent acquis)."""
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.arreter(mid)
    return stockage_horloge.lire_horloge(mid)


@app.get("/horloge/{mid}", tags=["horloge"])
def horloge_lire(mid: str, _cle: str = Depends(cle_api)):
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return stockage_horloge.lire_horloge(mid)
```

- [ ] **Step 7 : ajouter le scheduler in-process**

Ajoute à la fin de `main.py` :

```python
SCHEDULER_INTERVALLE_S = int(os.getenv("HORLOGE_SCHEDULER_INTERVALLE_S", "5"))
_SCHEDULER_ACTIF = os.getenv("HORLOGE_SCHEDULER_DESACTIVE", "").strip() != "1"


async def _boucle_scheduler():
    """Tâche de fond in-process (pas de queue externe — volume modéré visé ce
    sprint, voir design). Vérifie périodiquement les horloges actives dont
    l'intervalle est écoulé et déclenche leur tick. Une erreur sur un monde
    n'interrompt jamais la boucle ni les autres mondes."""
    while True:
        await asyncio.sleep(SCHEDULER_INTERVALLE_S)
        maintenant = datetime.now(timezone.utc).isoformat()
        try:
            dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
        except Exception:
            continue
        for due in dues:
            try:
                await horloge_moteur.executer_tick(due["monde_id"], due["cle_api"])
            except Exception:
                continue


@app.on_event("startup")
async def _demarrer_scheduler():
    if _SCHEDULER_ACTIF:
        asyncio.create_task(_boucle_scheduler())
```

- [ ] **Step 8 : lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_api.py -k horloge -v`
Expected: PASS (7 tests)

- [ ] **Step 9 : lancer toute la suite**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS (aucune régression)

- [ ] **Step 10 : commit**

```bash
git add briques/world-engine/main.py briques/world-engine/conftest.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): routes /horloge + scheduler in-process opt-in par monde"
```

---

### Task 8: `manifest.json` — 4 nouvelles capacités

**Files:**
- Modify: `briques/world-engine/manifest.json`
- Test: `briques/world-engine/test_manifest_capacites.py` (existant, aucune modification de code)

**Interfaces:**
- Consumes : routes réelles de `main.py` (Task 7).
- Produces : rien (fichier de données consommé par le Cœur — hors périmètre de ce repo).

- [ ] **Step 1 : mettre à jour la description du manifest et le champ `offre`**

Dans `manifest.json`, modifie :

```json
  "description": "Prototype exploratoire : croise 2 profils cosmiques (via la brique personnages) pour produire un enfant dont le thème astral est calculé à une vraie date, avec un récit d'hérédité en post-traitement (coïncidence assumée, pas une vraie génétique astrale). Persiste les lignées (arbre généalogique) ET un maillage spatial (mondes Voronoï forkables, biomes/ressources) sur lequel les enfants naissent, ET une horloge de simulation (ticks/ères) qui fait vivre un monde : vieillissement/mortalité, migration, couples, reproduction. Troisième maillon du rapport d'architecture « World Engine » (Génome + Spatial + Horloge) : les mondes fédérés (pays→monde) et la mise à l'échelle (queue Redis/RabbitMQ) restent hors périmètre.",
```

```json
  "offre": ["croisement_genome_cosmique", "maillage_spatial", "horloge_simulation"],
```

- [ ] **Step 2 : ajouter `sexe_enfant` aux params de `genome_croiser`**

Dans la capacité `genome_croiser` existante, ajoute dans `params` (après `monde_id`) :

```json
        "sexe_enfant": {
          "type": "string",
          "description": "Sexe de l'enfant ('F'/'M', optionnel) — persisté sur l'enfant stocké (Sprint C). Nécessaire pour que l'horloge de simulation puisse l'apparier automatiquement en couple par la suite. Absent : jamais deviné, l'enfant restera non appariable par l'horloge."
        }
```

- [ ] **Step 3 : ajouter les 4 nouvelles capacités (à la fin de la liste `capacites`)**

```json
    {
      "nom": "horloge_tick",
      "description": "Avance manuellement un monde spatial d'exactement 1 tick (1 an narratif) : régénération/consommation des ressources et progression technologique par cellule, vieillissement et mortalité (réduite par la technologie), migration poussée par la rareté, formation/dissolution de couples, naissances automatiques (couples établis + rencontres occasionnelles rares) via le même mécanisme que genome_croiser. Renvoie un résumé (naissances, morts, migrations, couples formés/dissous, niveau de technologie moyen, avertissements).",
      "methode": "POST",
      "chemin": "/horloge/{mid}/tick",
      "params": {
        "mid": {"type": "string", "description": "Id du monde à faire avancer.", "requis": true}
      },
      "action": true
    },
    {
      "nom": "horloge_demarrer",
      "description": "Active l'avancement automatique d'un monde : un scheduler interne (in-process, pas de service externe) déclenchera un tick toutes les intervalle_secondes tant que l'horloge n'est pas arrêtée. Un monde nouvellement créé ou forké reste en tick manuel tant que cet endpoint n'est pas appelé.",
      "methode": "POST",
      "chemin": "/horloge/{mid}/demarrer",
      "params": {
        "mid": {"type": "string", "description": "Id du monde.", "requis": true},
        "intervalle_secondes": {"type": "integer", "description": "Délai entre deux ticks automatiques (5 à 86400 secondes).", "requis": true}
      },
      "action": true
    },
    {
      "nom": "horloge_arreter",
      "description": "Désactive l'avancement automatique d'un monde. Les ticks déjà passés restent acquis ; le tick manuel reste toujours possible.",
      "methode": "POST",
      "chemin": "/horloge/{mid}/arreter",
      "params": {
        "mid": {"type": "string", "description": "Id du monde.", "requis": true}
      },
      "action": true
    },
    {
      "nom": "horloge_lire",
      "description": "Lit l'état courant de l'horloge d'un monde : tick_actuel, actif (mode automatique ou non), intervalle_secondes, date de dernière exécution.",
      "methode": "GET",
      "chemin": "/horloge/{mid}",
      "params": {
        "mid": {"type": "string", "description": "Id du monde.", "requis": true}
      },
      "action": false
    }
```

(Insère ces 4 objets juste avant la fermeture `]` du tableau `capacites`, après `spatial_monde_supprimer` — n'oublie pas la virgule après le `}` de `spatial_monde_supprimer`.)

- [ ] **Step 4 : valider le JSON et lancer le filet de contrat manifeste↔route**

Run: `cd briques/world-engine && python -c "import json; json.load(open('manifest.json'))" && python -m pytest test_manifest_capacites.py -v`
Expected: pas d'erreur JSON, PASS (2 tests : chaque capacité pointe une route réelle, noms uniques)

- [ ] **Step 5 : commit**

```bash
git add briques/world-engine/manifest.json
git commit -m "docs(world-engine): manifest à jour — 4 nouvelles capacités horloge_* + sexe_enfant"
```

---

### Task 9: Scénario bout-en-bout + README

**Files:**
- Modify: `briques/world-engine/test_horloge_moteur.py` (scénario multi-ticks)
- Modify: `briques/world-engine/README.md`

**Interfaces:**
- Consumes : tout ce qui précède.
- Produces : rien de nouveau — validation de bout en bout.

- [ ] **Step 1 : écrire le test de scénario bout-en-bout**

Ajoute à `test_horloge_moteur.py` :

```python
@respx.mock
@pytest.mark.asyncio
async def test_scenario_plusieurs_ticks_population_evolue():
    """Bout-en-bout : peuple un monde de plusieurs adultes fécondables, avance
    suffisamment de ticks, vérifie qu'au moins une naissance OU une mort a eu lieu
    (les deux sont probabilistes — sur assez de ticks, au moins l'un des deux doit
    se produire, sinon la mécanique de tick ne fait rien d'observable)."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=PORTRAIT_FACTICE))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge"}]}))

    monde = _monde_avec_habitants("cle-scenario", n_cellules=1)
    for i in range(6):
        sexe = "F" if i % 2 == 0 else "M"
        # theme=PORTRAIT_FACTICE : certains de ces habitants seront réellement
        # croisés au fil des ticks (couples formés automatiquement par l'étape 5).
        _ajouter_habitant("cle-scenario", monde["id"], 0, sexe, ne_au_tick=-30, theme=PORTRAIT_FACTICE)
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 100.0})

    total_naissances = total_morts = 0
    for _ in range(50):
        resultat = await horloge_moteur.executer_tick(monde["id"], "cle-scenario")
        total_naissances += resultat["naissances"]
        total_morts += resultat["morts"]

    assert total_naissances > 0 or total_morts > 0
```

- [ ] **Step 2 : lancer et vérifier**

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -k scenario -v`
Expected: PASS

- [ ] **Step 3 : mettre à jour le README**

Dans `briques/world-engine/README.md`, remplace le titre et ajoute un paragraphe :

```markdown
# world-engine — Génome Cosmique + Maillage Spatial + Horloge de simulation

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir les specs :
- `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-persistance-lignees-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-maillage-spatial-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-horloge-simulation-design.md`

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de la brique `personnages` (port 5900) en HTTP pour
tout calcul astral — pas de duplication du moteur astro.

Génère et persiste aussi des mondes spatiaux (maillage Voronoï, biomes/ressources
par bruit cohérent, forkables pour représenter des lignées temporelles divergentes)
— voir `spatial.py` (génération pure) et `stockage_spatial.py` (persistance). Un
enfant peut être placé sur un monde à sa naissance via `monde_id` sur
`POST /genome/croiser`.

Fait vivre un monde au fil de ticks (`/horloge`, 1 tick = 1 an narratif) :
vieillissement/mortalité (réduite par la technologie locale), migration poussée
par la rareté des ressources, couples formés/dissous par hasard, reproduction
(couples établis + rencontres occasionnelles) — voir `horloge.py` (mécanique
pure) et `horloge_moteur.py` (orchestrateur). Déclenchement manuel
(`POST /horloge/{id}/tick`) ou automatique opt-in par monde
(`POST /horloge/{id}/demarrer`, scheduler in-process — pas de queue externe,
volume visé modéré ce sprint). Mondes fédérés (pays→monde) et mise à l'échelle
(traitement vectorisé, queue Redis/RabbitMQ) restent hors périmètre.

Port : 6220.
```

- [ ] **Step 4 : lancer toute la suite une dernière fois**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS (tous les tests)

- [ ] **Step 5 : commit**

```bash
git add briques/world-engine/test_horloge_moteur.py briques/world-engine/README.md
git commit -m "test(world-engine): scénario bout-en-bout multi-ticks + README à jour (Sprint C)"
```

---

## Plan Self-Review

**Couverture du design** : les 6 étapes du tick (ressources, technologie, mortalité, migration, couples, reproduction) sont dans Task 5/6 ; le double déclenchement manuel/auto dans Task 7 ; l'opt-in par monde et le fork `actif=false` dans Task 3/7 ; l'âge/vivant par PLACEMENT (pas par enfant) dans Task 4 ; la dérivation lieu/heure/offset depuis la cellule dans Task 5 ; la persistance du sexe (gap découvert en cours de planification, validé avec l'utilisateur) dans Task 2 ; le cloisonnement `cle_api`/404 sur les 4 nouvelles routes dans Task 7 ; le repli honnête (jamais de 500 sur une écriture partielle) dans Task 6.

**Incohérence corrigée en relecture** : le premier jet de Task 1 incluait déjà les changements de Task 2 (`sexe_enfant`) et Task 4 (`ne_au_tick` via `stockage_horloge`) dans le code de `genome_moteur.py` — une note explicite a été ajoutée dans Task 1 précisant que ces deux ajouts doivent être omis à ce stade et n'arriver qu'aux tasks correspondantes, pour éviter qu'un exécutant suive Task 1 et importe un module (`stockage_horloge`) qui n'existe pas encore.

**Ordre des tâches vérifié** : Task 4 (accesseurs `stockage_spatial`) doit précéder la mise à jour finale de `genome_moteur.executer_croisement` (lecture de `ne_au_tick` via `stockage_horloge`, qui doit lui-même exister — Task 3 avant Task 4). Task 6 dépend de Task 3+4+5. Task 7 dépend de Task 3+6.
