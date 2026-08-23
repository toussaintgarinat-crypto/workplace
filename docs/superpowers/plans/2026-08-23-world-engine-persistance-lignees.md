# World Engine — Persistance des lignées (Sprint A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à `briques/world-engine` une persistance des enfants générés par `POST /genome/croiser`, pour pouvoir les réutiliser comme parents d'un croisement suivant et reconstruire une lignée sur plusieurs générations.

**Architecture:** Nouveau module `stockage.py` (SQLite, motif calqué sur `briques/personnages/stockage.py`) cloisonné par `cle_api`. `POST /genome/croiser` accepte pour chaque parent soit une fiche brute (comportement actuel), soit `{"id": "..."}` référençant un enfant déjà stocké, et persiste automatiquement (best-effort) l'enfant qu'il produit. Quatre nouvelles routes exposent la lecture/liste/suppression et la reconstruction récursive de l'arbre.

**Tech Stack:** FastAPI 0.115.6, Pydantic v2 (transitif via FastAPI), sqlite3 (stdlib), pytest + respx pour les tests (aucune nouvelle dépendance).

## Global Constraints

- Cloisonnement par `cle_api` sur toute donnée stockée — jamais de fuite entre clés API, même en mode ouvert (`cle_api == "public"`).
- Aucune fuite d'existence d'id entre clés : un id absent OU appartenant à une autre `cle_api` répond identiquement en **404** (jamais 403).
- Un id de parent invalide dans `POST /genome/croiser` (mauvais id, ou fiche malformée mêlant `id` et champs de fiche) répond en **404** ou **422** Pydantic natif — jamais confondu avec le 422 « fiche parent insuffisante » existant qui vient de `personnages`.
- Un échec d'écriture SQLite après un croisement calculé avec succès ne fait **jamais** échouer la requête (`enfant_id: null` + `avertissement`, pas de 500).
- Chaque nouvelle capacité assistant est ajoutée à `manifest.json` dans la même tâche que sa route (convention `feedback-exposer-nouvelles-fonctionnalites-assistant`).
- Toute nouvelle route est couverte par le filet manifeste↔route existant (`test_manifest_capacites.py`) — aucune modification de ce fichier n'est nécessaire, il est déjà générique.

---

## File Structure

- **Create** `briques/world-engine/stockage.py` — CRUD SQLite de la table `enfants`, cloisonné par `cle_api`.
- **Create** `briques/world-engine/test_stockage.py` — tests unitaires du module ci-dessus, sans FastAPI.
- **Modify** `briques/world-engine/conftest.py` — DB de test temporaire (même motif que `personnages/conftest.py`).
- **Modify** `briques/world-engine/main.py` — `ReferenceParent`, `ParentInput`, helper `_theme_parent`, persistance automatique dans `genome_croiser`, 4 nouvelles routes (`GET /genome/enfants`, `GET /genome/enfants/{eid}`, `DELETE /genome/enfants/{eid}`, `GET /genome/arbre/{eid}`).
- **Modify** `briques/world-engine/test_api.py` — tests des nouveaux comportements de `/genome/croiser` et des 4 nouvelles routes.
- **Modify** `briques/world-engine/manifest.json` — `genome_croiser` passe `action: true`, 4 nouvelles capacités.
- **Modify** `briques/world-engine/docker-compose.yml` — `WORLD_ENGINE_DB` + volume `world_engine_data`.

---

### Task 1: Module de stockage SQLite

**Files:**
- Create: `briques/world-engine/stockage.py`
- Modify: `briques/world-engine/conftest.py`
- Test: `briques/world-engine/test_stockage.py`

**Interfaces:**
- Produces: `stockage.creer(cle_api: str, prenoms: str, nom: str, parent_a_id: str | None, parent_b_id: str | None, theme: dict, description_genome: str, heredite: dict, mutation_survenue: bool) -> str` (renvoie l'id créé)
- Produces: `stockage.lister(cle_api: str) -> list[dict]` (chaque dict : `id, prenoms, nom, parent_a_id, parent_b_id, cree_le`)
- Produces: `stockage.lire(cle_api: str, eid: str) -> dict | None` (dict complet : `id, prenoms, nom, parent_a_id, parent_b_id, theme, description_genome, heredite, mutation_survenue, cree_le`)
- Produces: `stockage.supprimer(cle_api: str, eid: str) -> bool`
- Produces: `stockage.DB_PATH: str` (lu depuis `WORLD_ENGINE_DB`, défaut `/data/world_engine.db`)

- [ ] **Step 1: Mettre à jour `conftest.py` pour une DB de test temporaire**

Remplace le contenu de `briques/world-engine/conftest.py` :

```python
"""Config de test : DB temporaire + mode auth ouvert AVANT tout import des modules."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "world_engine_test.db")
os.environ["WORLD_ENGINE_DB"] = _db
os.environ.setdefault("API_KEYS", "")     # mode ouvert → tenant "public"

if os.path.exists(_db):
    os.remove(_db)
```

- [ ] **Step 2: Écrire le test qui échoue**

Créer `briques/world-engine/test_stockage.py` :

```python
"""Tests du stockage SQLite des enfants générés (couche persistance du Sprint A)."""
import stockage


def _theme_factice(signe="Vierge") -> dict:
    return {
        "traditions": {"signe_solaire": {"nom": signe}},
        "portrait": {"archetype": "Le Gardien", "forces": ["Sagesse", "Stabilité"]},
        "theme_complet": {
            "dominantes": {"planete": {"dominante": "Mercure"}, "signe": {"dominant": signe}},
            "dix_corps": {c: {"signe": signe} for c in
                          ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                           "Saturne", "Uranus", "Neptune", "Pluton"]},
        },
    }


def test_creer_puis_lire():
    eid = stockage.creer("cle-a", "Nova", "Test", None, None,
                          _theme_factice(), "desc genome", {"resume": {"A": 5}}, False)
    assert isinstance(eid, str) and eid

    e = stockage.lire("cle-a", eid)
    assert e["id"] == eid
    assert e["prenoms"] == "Nova"
    assert e["nom"] == "Test"
    assert e["parent_a_id"] is None
    assert e["parent_b_id"] is None
    assert e["theme"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"
    assert e["description_genome"] == "desc genome"
    assert e["heredite"] == {"resume": {"A": 5}}
    assert e["mutation_survenue"] is False
    assert e["cree_le"]


def test_lire_introuvable_renvoie_none():
    assert stockage.lire("cle-a", "id-inconnu") is None


def test_lire_cloisonne_par_cle_api():
    eid = stockage.creer("cle-b", "Secret", "", None, None,
                          _theme_factice(), "d", {"resume": {}}, False)
    assert stockage.lire("cle-b", eid) is not None
    assert stockage.lire("autre-cle", eid) is None


def test_lister_cloisonne_et_ordonne():
    stockage.creer("cle-c", "Premier", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    eid2 = stockage.creer("cle-c", "Second", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    resultats = stockage.lister("cle-c")
    assert [e["prenoms"] for e in resultats] == ["Second", "Premier"]  # plus récent d'abord
    assert "theme" not in resultats[0]  # liste allégée, pas le snapshot complet
    assert resultats[0]["id"] == eid2
    assert stockage.lister("cle-vide") == []


def test_lister_expose_les_ids_parents():
    gp = stockage.creer("cle-d", "GrandParent", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    p = stockage.creer("cle-d", "Parent", "", gp, None, _theme_factice(), "d", {"resume": {}}, False)
    resultats = {e["id"]: e for e in stockage.lister("cle-d")}
    assert resultats[p]["parent_a_id"] == gp
    assert resultats[p]["parent_b_id"] is None


def test_supprimer():
    eid = stockage.creer("cle-e", "Nova", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    assert stockage.supprimer("cle-e", eid) is True
    assert stockage.lire("cle-e", eid) is None


def test_supprimer_introuvable_renvoie_false():
    assert stockage.supprimer("cle-e", "id-inconnu") is False


def test_supprimer_cloisonne_par_cle_api():
    eid = stockage.creer("cle-f", "Nova", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    assert stockage.supprimer("autre-cle", eid) is False   # ne supprime pas chez une autre clé
    assert stockage.lire("cle-f", eid) is not None          # toujours là
```

- [ ] **Step 3: Lancer les tests pour vérifier l'échec**

Run: `cd briques/world-engine && python -m pytest test_stockage.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'stockage'`

- [ ] **Step 4: Implémenter `stockage.py`**

Créer `briques/world-engine/stockage.py` :

```python
"""Stockage des enfants générés par `POST /genome/croiser` — persistance AUTOMATIQUE
(contrairement à `personnages/stockage.py` qui est opt-in) : c'est ce qui permet
d'enchaîner les générations sans geste explicite à chaque croisement. Cloisonné par
`cle_api`, même motif que `personnages`."""
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
    c.execute("""CREATE TABLE IF NOT EXISTS enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_enfant_cle ON enfants(cle_api)")
    return c


def _ligne_complete(r: sqlite3.Row) -> dict:
    d = json.loads(r["donnees"])
    return {"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
            "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"],
            "theme": d["theme"], "description_genome": d["description_genome"],
            "heredite": d["heredite"], "mutation_survenue": d["mutation_survenue"],
            "cree_le": r["cree_le"]}


def creer(cle_api: str, prenoms: str, nom: str, parent_a_id: str | None, parent_b_id: str | None,
          theme: dict, description_genome: str, heredite: dict, mutation_survenue: bool) -> str:
    """Persiste un enfant généré par un croisement. Renvoie son id.

    `theme` = snapshot COMPLET renvoyé par `personnages` (traditions/portrait/
    theme_complet) — la même forme qu'une fiche parent en sortie de
    `personnages_client.portrait`, pour pouvoir être réinjecté tel quel comme
    parent d'un croisement suivant sans rappeler `personnages`."""
    eid = uuid.uuid4().hex
    donnees = {"theme": theme, "description_genome": description_genome,
               "heredite": heredite, "mutation_survenue": mutation_survenue}
    with _conn() as c:
        c.execute("""INSERT INTO enfants (id, cle_api, prenoms, nom, parent_a_id, parent_b_id, donnees, cree_le)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (eid, cle_api, prenoms or "", nom or "", parent_a_id, parent_b_id,
                   json.dumps(donnees, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return eid


def lister(cle_api: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, prenoms, nom, parent_a_id, parent_b_id, cree_le FROM enfants "
            "WHERE cle_api=? ORDER BY cree_le DESC", (cle_api,)).fetchall()
    return [{"id": r["id"], "prenoms": r["prenoms"], "nom": r["nom"],
             "parent_a_id": r["parent_a_id"], "parent_b_id": r["parent_b_id"],
             "cree_le": r["cree_le"]} for r in rows]


def lire(cle_api: str, eid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM enfants WHERE id=? AND cle_api=?", (eid, cle_api)).fetchone()
    return _ligne_complete(r) if r else None


def supprimer(cle_api: str, eid: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM enfants WHERE id=? AND cle_api=?", (eid, cle_api))
    return cur.rowcount > 0
```

- [ ] **Step 5: Relancer les tests pour vérifier le succès**

Run: `cd briques/world-engine && python -m pytest test_stockage.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/stockage.py briques/world-engine/test_stockage.py briques/world-engine/conftest.py
git commit -m "feat(world-engine): stockage SQLite des enfants générés, cloisonné par cle_api"
```

---

### Task 2: Réutiliser un enfant stocké comme parent (`{"id": "..."}`)

**Files:**
- Modify: `briques/world-engine/main.py`
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `stockage.lire(cle_api, eid) -> dict | None` (Task 1) — champ `theme` réutilisé tel quel comme `theme_a`/`theme_b`.
- Produces: `ReferenceParent` (Pydantic model, champ `id: str`, `extra="forbid"`), `ParentInput = Union[ReferenceParent, FicheParent]`, `_theme_parent(parent: ParentInput, cle_api_val: str, qui: str) -> dict` (coroutine) — utilisés par Task 3, 4, 5.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `briques/world-engine/test_api.py` (après les imports existants, ajouter `import stockage` ; les tests eux vont après `test_genome_croiser_401_personnages_devient_502`) :

```python
import stockage
```

```python
@respx.mock
def test_genome_croiser_parent_a_par_id_reutilise_stockage():
    """parent_a peut être {"id": ...} référençant un enfant déjà stocké : son thème
    est relu depuis stockage.py, personnages n'est PAS rappelé pour ce parent."""
    theme_stocke = _portrait_factice("Mercure", "Vierge", "Vierge")
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          theme_stocke, "desc", {"resume": {}}, False)

    route_portrait = respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),   # parent B
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])  # enfant
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))

    r = client.post("/genome/croiser", json={
        "parent_a": {"id": eid}, "parent_b": _FICHE_B,
        "prenoms_enfant": "Nova2", "heure_naissance_enfant": "10:00",
        "latitude_enfant": 43.6, "longitude_enfant": 1.44, "utc_offset_enfant": 1.0,
        "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    assert route_portrait.call_count == 2  # parent B + enfant seulement — PAS parent A


@respx.mock
def test_genome_croiser_parent_id_introuvable_404():
    """@respx.mock sans aucune route enregistrée : si l'id-lookup régressait vers un
    appel réseau, ça lèverait plutôt que de pendre sur host.docker.internal."""
    r = client.post("/genome/croiser", json={
        "parent_a": {"id": "id-inconnu"}, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0})
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `cd briques/world-engine && python -m pytest test_api.py -k "par_id or introuvable_404" -v`
Expected: FAIL — `{"id": eid}` échoue actuellement la validation Pydantic de `FicheParent` (champ `id` inattendu, mais `FicheParent` accepte encore les champs en trop par défaut) ou produit un 422 générique, pas le comportement attendu.

- [ ] **Step 3: Implémenter dans `main.py`**

Modifier les imports en haut du fichier :

```python
from typing import Optional, Union
```
(remplace `from typing import Optional`)

```python
from pydantic import BaseModel, ConfigDict, Field
```
(remplace `from pydantic import BaseModel, Field`)

Ajouter après les imports existants (`import fusion` / `import personnages_client`) :

```python
import stockage
```

Modifier `FicheParent` pour interdire les champs en trop (nécessaire pour distinguer sans ambiguïté une fiche brute d'une référence `{"id": ...}`) :

```python
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


class ReferenceParent(BaseModel):
    """Référence à un enfant déjà stocké (Sprint A), utilisable comme parent d'un
    nouveau croisement — évite de recopier date/heure/lieu de naissance d'un
    enfant déjà généré. `extra="forbid"` sur les deux modèles rend le choix entre
    fiche brute et référence déterministe pour Pydantic (aucun input valide ne
    peut matcher les deux à la fois)."""
    model_config = ConfigDict(extra="forbid")

    id: str


ParentInput = Union[ReferenceParent, FicheParent]
```

Modifier `Croisement` pour utiliser `ParentInput` :

```python
class Croisement(BaseModel):
    parent_a: ParentInput
    parent_b: ParentInput
```
(remplace `parent_a: FicheParent` / `parent_b: FicheParent` — le reste de la classe est inchangé)

Ajouter juste avant `@app.post("/genome/croiser", ...)` :

```python
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
        r = await personnages_client.portrait(parent.model_dump())
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if r.status_code != 200:
        _propager_ou_502(r, qui)
    theme = r.json()
    _exiger_theme_complet(theme, qui)
    return theme
```

Remplacer le début de `genome_croiser` (les deux blocs de résolution parent_a/parent_b) par :

```python
@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel, avec
    un récit d'hérédité en post-traitement. L'enfant produit est automatiquement
    stocké (best-effort)."""
    theme_a = await _theme_parent(body.parent_a, _cle, "Parent A")
    theme_b = await _theme_parent(body.parent_b, _cle, "Parent B")

    description, mutation_survenue = fusion.fusionner_description(
        theme_a, theme_b, body.mutation_rate, Random())
```

Le reste de la fonction (`recherche_inverse` jusqu'au `return`) reste inchangé pour cette tâche — Task 3 y ajoutera la persistance.

- [ ] **Step 4: Relancer les tests pour vérifier le succès**

Run: `cd briques/world-engine && python -m pytest test_api.py -v`
Expected: PASS (tous les tests, y compris les 2 nouveaux et les tests existants inchangés — le refactor préserve l'ordre séquentiel A-avant-B)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): parent_a/parent_b acceptent un enfant stocké par id"
```

---

### Task 3: Persistance automatique de l'enfant produit

**Files:**
- Modify: `briques/world-engine/main.py`
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `stockage.creer(...)` (Task 1), `_theme_parent`, `ParentInput`, `ReferenceParent` (Task 2)
- Produces: réponse de `POST /genome/croiser` enrichie de `enfant_id: str | None` et `avertissement: str | None`

- [ ] **Step 1: Écrire les tests qui échouent**

Modifier `test_genome_croiser_chemin_heureux` dans `test_api.py` : ajouter après `assert "description_genome" in data` :

```python
    assert isinstance(data["enfant_id"], str) and data["enfant_id"]
    assert data["avertissement"] is None
    stocke = stockage.lire("public", data["enfant_id"])
    assert stocke["prenoms"] == "Nova"
    assert stocke["parent_a_id"] is None   # parent_a était une fiche brute, pas une référence
    assert stocke["parent_b_id"] is None
```

Ajouter un nouveau test à la fin du fichier :

```python
@respx.mock
def test_genome_croiser_stockage_echoue_repond_quand_meme(monkeypatch):
    """Un échec d'écriture SQLite après un croisement réussi ne fait jamais échouer
    la requête : le calcul est bon, seule la persistance a un problème."""
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))

    def _echec(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(main.stockage, "creer", _echec)

    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "heure_naissance_enfant": "10:00", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "utc_offset_enfant": 1.0, "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    data = r.json()
    assert data["enfant_id"] is None
    assert data["avertissement"] is not None and "disque plein" in data["avertissement"]
```

Ajouter aussi, juste après l'import `import stockage` ajouté en Task 2 :

```python
import main
```

(déjà présent en tête de fichier — vérifier qu'il l'est ; sinon l'ajouter, `main.stockage` doit être accessible pour `monkeypatch.setattr`)

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `cd briques/world-engine && python -m pytest test_api.py -k "chemin_heureux or stockage_echoue" -v`
Expected: FAIL — `KeyError: 'enfant_id'` (champ absent de la réponse actuelle)

- [ ] **Step 3: Implémenter dans `main.py`**

Modifier la fin de `genome_croiser` (à partir du calcul de `heredite`) :

```python
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

    return {"parentA": theme_a, "parentB": theme_b, "description_genome": description,
            "enfant": theme_enfant, "heredite": heredite, "mutation_survenue": mutation_survenue,
            "enfant_id": enfant_id, "avertissement": avertissement}
```

- [ ] **Step 4: Relancer les tests pour vérifier le succès**

Run: `cd briques/world-engine && python -m pytest test_api.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): persistance automatique (best-effort) de l'enfant produit"
```

---

### Task 4: Lister, lire, supprimer un enfant stocké

**Files:**
- Modify: `briques/world-engine/main.py`
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `stockage.lister`, `stockage.lire`, `stockage.supprimer` (Task 1)
- Produces: `GET /genome/enfants`, `GET /genome/enfants/{eid}`, `DELETE /genome/enfants/{eid}`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `test_api.py` :

```python
def test_genome_enfants_lister_et_lire():
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          _portrait_factice(), "desc", {"resume": {"A": 1}}, False)

    r = client.get("/genome/enfants")
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()]
    assert eid in ids
    assert "theme" not in r.json()[0]   # liste allégée

    r2 = client.get(f"/genome/enfants/{eid}")
    assert r2.status_code == 200
    assert r2.json()["prenoms"] == "Nova"
    assert r2.json()["theme"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"


def test_genome_enfant_lire_introuvable_404():
    r = client.get("/genome/enfants/id-inconnu")
    assert r.status_code == 404


def test_genome_enfants_cloisonnes_par_cle_api(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    eid = main.stockage.creer("cle-x", "Secret", "", None, None,
                               _portrait_factice(), "d", {"resume": {}}, False)
    r_x = c.get("/genome/enfants", headers={"X-API-Key": "cle-x"})
    r_y = c.get("/genome/enfants", headers={"X-API-Key": "cle-y"})
    assert any(e["id"] == eid for e in r_x.json())
    assert not any(e["id"] == eid for e in r_y.json())
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)


def test_genome_enfant_supprimer():
    eid = stockage.creer("public", "Nova", "Test", None, None,
                          _portrait_factice(), "d", {"resume": {}}, False)
    r = client.delete(f"/genome/enfants/{eid}")
    assert r.status_code == 204
    assert client.get(f"/genome/enfants/{eid}").status_code == 404


def test_genome_enfant_supprimer_introuvable_404():
    r = client.delete("/genome/enfants/id-inconnu")
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `cd briques/world-engine && python -m pytest test_api.py -k "genome_enfant" -v`
Expected: FAIL avec 404 (routes inexistantes)

- [ ] **Step 3: Implémenter dans `main.py`**

Ajouter après la fonction `genome_croiser` :

```python
@app.get("/genome/enfants", tags=["genome"])
def genome_enfants_lister(_cle: str = Depends(cle_api)):
    return stockage.lister(_cle)


@app.get("/genome/enfants/{eid}", tags=["genome"])
def genome_enfant_lire(eid: str, _cle: str = Depends(cle_api)):
    enfant = stockage.lire(_cle, eid)
    if enfant is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return enfant


@app.delete("/genome/enfants/{eid}", status_code=204, tags=["genome"])
def genome_enfant_supprimer(eid: str, _cle: str = Depends(cle_api)):
    if not stockage.supprimer(_cle, eid):
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
```

- [ ] **Step 4: Relancer les tests pour vérifier le succès**

Run: `cd briques/world-engine && python -m pytest test_api.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): lister/lire/supprimer les enfants stockés"
```

---

### Task 5: Reconstruction de l'arbre généalogique

**Files:**
- Modify: `briques/world-engine/main.py`
- Test: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `stockage.lire` (Task 1)
- Produces: `GET /genome/arbre/{eid}`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `test_api.py` :

```python
def test_genome_arbre_trois_generations():
    gp = stockage.creer("public", "GrandParent", "", None, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    p = stockage.creer("public", "Parent", "", gp, None,
                        _portrait_factice(), "d", {"resume": {}}, False)
    e = stockage.creer("public", "Enfant", "", p, None,
                        _portrait_factice(), "d", {"resume": {}}, False)

    r = client.get(f"/genome/arbre/{e}")
    assert r.status_code == 200
    arbre = r.json()
    assert arbre["id"] == e
    assert arbre["parent_a"]["id"] == p
    assert arbre["parent_a"]["parent_a"]["id"] == gp
    assert arbre["parent_a"]["parent_a"]["parent_a"] is None
    assert arbre["parent_b"] is None


def test_genome_arbre_branche_tronquee_apres_suppression():
    gp = stockage.creer("public", "GrandParent", "", None, None,
                         _portrait_factice(), "d", {"resume": {}}, False)
    e = stockage.creer("public", "Enfant", "", gp, None,
                        _portrait_factice(), "d", {"resume": {}}, False)
    stockage.supprimer("public", gp)

    r = client.get(f"/genome/arbre/{e}")
    assert r.status_code == 200
    assert r.json()["parent_a"] is None   # gp supprimé, branche tronquée, pas d'erreur


def test_genome_arbre_racine_introuvable_404():
    r = client.get("/genome/arbre/id-inconnu")
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `cd briques/world-engine && python -m pytest test_api.py -k "genome_arbre" -v`
Expected: FAIL avec 404 (route inexistante)

- [ ] **Step 3: Implémenter dans `main.py`**

Ajouter après les routes de Task 4 :

```python
def _noeud_arbre(cle_api_val: str, eid: str) -> dict | None:
    """Reconstruit récursivement la lignée d'un enfant stocké. S'arrête dès qu'un
    parent est absent (fiche brute d'origine, ou enfant stocké supprimé entre-temps
    — les deux cas sont indistinguables et traités pareil : branche `null`)."""
    enfant = stockage.lire(cle_api_val, eid)
    if enfant is None:
        return None
    return {
        "id": enfant["id"], "prenoms": enfant["prenoms"], "nom": enfant["nom"],
        "parent_a": _noeud_arbre(cle_api_val, enfant["parent_a_id"]) if enfant["parent_a_id"] else None,
        "parent_b": _noeud_arbre(cle_api_val, enfant["parent_b_id"]) if enfant["parent_b_id"] else None,
    }


@app.get("/genome/arbre/{eid}", tags=["genome"])
def genome_arbre_lire(eid: str, _cle: str = Depends(cle_api)):
    noeud = _noeud_arbre(_cle, eid)
    if noeud is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return noeud
```

- [ ] **Step 4: Relancer les tests pour vérifier le succès**

Run: `cd briques/world-engine && python -m pytest test_api.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): reconstruction récursive de l'arbre généalogique"
```

---

### Task 6: Manifest — capacités assistant

**Files:**
- Modify: `briques/world-engine/manifest.json`

**Interfaces:**
- Consumes: routes de Task 2 à 5 (le filet `test_manifest_capacites.py`, déjà existant et générique, valide que chaque capacité pointe une route réelle)

- [ ] **Step 1: Modifier `manifest.json`**

Dans la capacité `genome_croiser` existante :
- Changer `"action": false` → `"action": true` (persiste désormais un enfant)
- Mettre à jour la `description` du champ `parent_a` :
  `"Fiche du parent A : prenoms, nom, date_naissance ('AAAA-MM-JJ', requis), heure_naissance ('HH:MM'), latitude, longitude, utc_offset — OU {\"id\": \"...\"} référençant un enfant déjà stocké par un croisement précédent (relu sans rappeler personnages). heure_naissance/latitude/longitude sont EFFECTIVEMENT nécessaires pour une fiche brute : sans eux, personnages renvoie un thème dégradé et l'appel échoue en 422."`
- Même mise à jour pour `parent_b` (remplacer `"même forme que parent_a"` par `"Fiche du parent B, même forme que parent_a (fiche brute OU {\"id\": \"...\"}), mêmes contraintes."`)
- Ajouter à la fin de la `description` de la capacité (après la phrase sur le lieu de naissance) : `" L'enfant produit est automatiquement stocké (enfant_id dans la réponse) et peut être réutilisé comme parent d'un croisement suivant."`

Ajouter 4 nouvelles capacités dans le tableau `capacites`, après `genome_croiser` :

```json
    {
      "nom": "genome_enfants_lister",
      "description": "Liste les enfants générés par des croisements précédents et stockés (id, prénoms, nom, ids des parents s'ils étaient eux-mêmes des enfants stockés, date de création). Cloisonné par clé API : ne montre jamais les enfants d'un autre client.",
      "methode": "GET",
      "chemin": "/genome/enfants",
      "params": {},
      "action": false
    },
    {
      "nom": "genome_enfant_lire",
      "description": "Lit la fiche complète d'un enfant stocké : thème astral, récit d'hérédité, description fusionnée, ids des parents.",
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
    {
      "nom": "genome_arbre_lire",
      "description": "Reconstruit récursivement la lignée d'un enfant stocké (parents, grands-parents…) en remontant les ids stockés. S'arrête dès qu'un parent était une fiche brute (pas un enfant stocké) ou a été supprimé — la branche vaut alors null, jamais une erreur.",
      "methode": "GET",
      "chemin": "/genome/arbre/{eid}",
      "params": {
        "eid": {
          "type": "string",
          "description": "Id de l'enfant stocké dont on veut reconstruire la lignée.",
          "requis": true
        }
      },
      "action": false
    },
    {
      "nom": "genome_enfant_supprimer",
      "description": "Supprime un enfant stocké. Pas de suppression en cascade : un descendant qui le référence verra sa branche tronquée dans genome_arbre_lire (traitée comme absente, pas une erreur).",
      "methode": "DELETE",
      "chemin": "/genome/enfants/{eid}",
      "params": {
        "eid": {
          "type": "string",
          "description": "Id de l'enfant stocké à supprimer.",
          "requis": true
        }
      },
      "action": true
    }
```

- [ ] **Step 2: Vérifier le filet manifeste↔route**

Run: `cd briques/world-engine && python -m pytest test_manifest_capacites.py -v`
Expected: PASS (2 tests — chaque capacité pointe une route réelle, noms uniques)

- [ ] **Step 3: Lancer la suite complète**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS (tous les tests du module)

- [ ] **Step 4: Commit**

```bash
git add briques/world-engine/manifest.json
git commit -m "docs(world-engine): manifest à jour — 4 nouvelles capacités + genome_croiser action=true"
```

---

### Task 7: Volume Docker pour la persistance

**Files:**
- Modify: `briques/world-engine/docker-compose.yml`

- [ ] **Step 1: Modifier `docker-compose.yml`**

```yaml
services:
  world-engine:
    build: .
    container_name: workplace_world_engine
    image: workplace/world-engine:0.1.0
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6220:6220"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # joindre `personnages` sous Linux
    environment:
      - PORT=6220
      - PERSONNAGES_URL=http://host.docker.internal:5900
      - WORLD_ENGINE_DB=/data/world_engine.db
      # PERSONNAGES_KEY (clé d'intégration Cœur) vient du .env racine via env_file —
      # NE PAS la redéclarer en `PERSONNAGES_KEY=${PERSONNAGES_KEY:-}` (piège « env
      # shadow » : chaîne vide qui écraserait la vraie valeur).
    volumes:
      - world_engine_data:/data   # lignées d'enfants générés (persistance Sprint A)
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6220/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  world_engine_data:
```

- [ ] **Step 2: Valider la syntaxe compose**

Run: `cd briques/world-engine && docker compose config --quiet`
Expected: aucune sortie, code de sortie 0 (compose valide)

- [ ] **Step 3: Rebuild et preuve d'intégration réelle**

```bash
cd briques/world-engine && docker compose up -d --build
sleep 3
curl -s http://localhost:6220/sante
```
Expected : `{"statut":"ok","brique":"world-engine"}`. Puis un croisement réel suivi d'un `GET /genome/enfants` (contre `personnages` déjà démarré, comme dans le protocole d'évaluation exécuté le 2026-08-23) pour prouver que la persistance survit dans le conteneur reconstruit.

- [ ] **Step 4: Commit**

```bash
git add briques/world-engine/docker-compose.yml
git commit -m "feat(world-engine): volume world_engine_data pour la persistance des lignées"
```

---

## Self-Review

**Spec coverage** — chaque section de `2026-08-23-world-engine-persistance-lignees-design.md` a une tâche :
- Stockage automatique → Task 1, 3
- Réutilisation par id → Task 2
- Cloisonnement `cle_api` → Task 1 (tests), Task 4 (test isolation via API)
- Endpoint d'arbre → Task 5
- Suppression → Task 4
- Manifest → Task 6
- Volume Docker → Task 7

**Écart corrigé par rapport au libellé littéral du spec** : le spec décrit `donnees` comme `{theme_complet, description_genome, heredite, mutation_survenue}`. En écrivant le plan, `theme_complet` seul s'est révélé insuffisant : `fusion.fusionner_description` (réutilisée quand un enfant stocké sert de parent) lit aussi `theme["portrait"]["forces"]` et `theme["traditions"]`, absents de `theme_complet`. Le plan stocke donc le **snapshot complet** (`theme` = toute la réponse `personnages`, pas seulement `theme_complet`) sous la clé `theme` — cohérent avec l'intention du spec (réutilisation directe comme parent) mais avec la forme correcte. Aucun autre écart.

**Placeholders** — aucun « TBD »/« TODO » ; chaque step contient le code complet.

**Cohérence des types** — `stockage.creer(...)` a la même signature partout où il est appelé (Task 1 tests, Task 3 `main.py`, Task 4/5 tests de seed) ; `stockage.lire(...)` renvoie toujours le même schéma de dict, utilisé identiquement en Task 2 (`enfant["theme"]`), Task 4 (`GET /genome/enfants/{eid}`) et Task 5 (`_noeud_arbre`).
