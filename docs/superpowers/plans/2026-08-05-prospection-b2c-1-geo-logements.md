# Prospection B2C — geo : type `logement` + fournisseur DPE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La brique `geo` sait ingérer et exposer des logements (adresse + grade DPE,
jamais de nom de propriétaire) comme un nouveau type d'objet `geo_objects`, au même
titre que les entreprises — sans toucher au pipeline Sirene existant.

**Architecture:** Nouveau fichier `fournisseurs_logements.py` (motif identique à
`fournisseurs.py` : `Mock`/fournisseur réel, factory, bascule par variable d'env
dédiée). `domaine.py` gagne la normalisation ADEME→`geo_objects` et la conversion
Lambert93→WGS84 (les coordonnées ADEME ne sont pas en latitude/longitude).
`main.py` route vers ce nouveau fournisseur à l'ingestion (`/ingestion/executer`)
quand `zone["type"] == "logement"`, et `/prospection/enrichir-lot` saute
entièrement la recherche du « site officiel » (qui n'a pas de sens pour un
logement) pour ce type.

**Tech Stack:** FastAPI, SQLite (stdlib `sqlite3`), `httpx`, nouvelle dépendance
`pyproj==3.7.2` (conversion de projection cartographique — jamais réimplémentée à
la main, trop risqué d'erreur silencieuse en géodésie).

## Global Constraints

- Aucun nom de personne (propriétaire) ne doit jamais apparaître dans les données
  produites par cette brique — seulement l'adresse et les caractéristiques du bien
  (cf. contrainte légale MAJIC documentée dans
  `docs/superpowers/specs/2026-08-05-prospection-b2c-signal-identite-design.md`).
- Fournisseur réel désactivé par défaut ; bascule explicite par variable d'env
  (`GEO_FOURNISSEUR_LOGEMENTS=reel`), jamais de détection silencieuse — même motif
  que `GEO_FOURNISSEUR` existant.
- Aucun changement de comportement observable pour les zones/objets `entreprise`
  existants — additif uniquement.
- API ADEME utilisée : `https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant`
  — vérifiée LIVE le 2026-08-05 (voir Task 4), sans clé.

---

### Task 1: Conversion Lambert93 → WGS84 (`domaine.py`)

Les coordonnées de l'API ADEME (`coordonnee_cartographique_x_ban`/`_y_ban`) sont en
projection Lambert93 (EPSG:2154, mètres), pas en latitude/longitude. `geo_objects`
exige des degrés décimaux WGS84 (`domaine.valider_point` borne ±90/±180). On utilise
`pyproj` (bibliothèque de référence, PROJ derrière) plutôt qu'une formule maison —
une erreur de conversion géodésique serait un bug silencieux (coordonnées plausibles
mais fausses), pas une exception.

**Files:**
- Modify: `briques/geo/requirements.txt`
- Modify: `briques/geo/domaine.py`
- Test: `briques/geo/test_domaine.py`

**Interfaces:**
- Produces: `domaine.lambert93_vers_wgs84(x: float, y: float) -> tuple[float, float]`
  (renvoie `(latitude, longitude)`), utilisé par la Task 2.

- [ ] **Step 1: Ajouter la dépendance**

Modifier `briques/geo/requirements.txt` :

```txt
# Brique geo — GeoHub cartographique. Dépendances minces et épinglées.
# Le métier (fraîcheur, validations, normalisation) est en Python pur (domaine.py) ;
# l'index spatial est le R*Tree du sqlite3 de la stdlib : aucun service de plus.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
pyproj==3.7.2
```

- [ ] **Step 2: Écrire le test de conversion (référence réelle vérifiée)**

Ajouter à la fin de `briques/geo/test_domaine.py` :

```python
def test_lambert93_vers_wgs84_sur_un_point_reel_carcassonne():
    # Coordonnées Lambert93 RÉELLES d'un DPE à Carcassonne (vérifié LIVE ADEME,
    # 2026-08-05, numero_dpe 2611E0031228S). Référence calculée avec pyproj
    # 3.7.2 (EPSG:2154 → EPSG:4326) : lat=43.21658904532542, lon=2.3590970608354813.
    latitude, longitude = domaine.lambert93_vers_wgs84(647889.49, 6235475.96)
    assert latitude == pytest.approx(43.21659, abs=1e-4)
    assert longitude == pytest.approx(2.35910, abs=1e-4)


def test_lambert93_vers_wgs84_hors_de_france_leve():
    with pytest.raises(ValueError):
        domaine.lambert93_vers_wgs84(0.0, 0.0)
```

Vérifier que `import pytest` est déjà présent en tête de `test_domaine.py` (sinon
l'ajouter).

- [ ] **Step 3: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/geo && python3 -m pytest test_domaine.py -k lambert93 -v`
Expected: FAIL avec `AttributeError: module 'domaine' has no attribute 'lambert93_vers_wgs84'`

- [ ] **Step 4: Implémenter la conversion**

Ajouter dans `briques/geo/domaine.py`, après les imports existants :

```python
from pyproj import Transformer

_LAMBERT93_VERS_WGS84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
```

Puis à la suite de `bbox_union` (fin du fichier avant `_dirigeant_dict`) :

```python
def lambert93_vers_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convertit des coordonnées Lambert93 (EPSG:2154, mètres — le système utilisé par
    l'API ADEME/DPE) en latitude/longitude WGS84 (degrés décimaux). `always_xy=True` sur
    le Transformer : `transform` prend/rend (x=lon, y=lat) dans cet ordre, d'où l'inversion
    du renvoi. Lève ValueError (via valider_point) si le résultat sort des bornes
    terrestres — un signe que les coordonnées d'entrée n'étaient pas du Lambert93 valide."""
    longitude, latitude = _LAMBERT93_VERS_WGS84.transform(x, y)
    valider_point(latitude, longitude)
    return latitude, longitude
```

- [ ] **Step 5: Installer la dépendance et lancer le test**

Run: `cd briques/geo && pip install -r requirements.txt && python3 -m pytest test_domaine.py -k lambert93 -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add briques/geo/requirements.txt briques/geo/domaine.py briques/geo/test_domaine.py
git commit -m "feat(geo): conversion Lambert93→WGS84 pour les coordonnées ADEME"
```

---

### Task 2: Normalisation d'un logement DPE (`domaine.py`)

**Files:**
- Modify: `briques/geo/domaine.py`
- Test: `briques/geo/test_domaine.py`

**Interfaces:**
- Consumes: `domaine.lambert93_vers_wgs84(x, y) -> (latitude, longitude)` (Task 1),
  `domaine.valider_point` (existant).
- Produces: `domaine.normaliser_logement(brute: dict) -> dict | None`, utilisé par
  `fournisseurs_logements.DpeAdeme` (Task 4). Objet renvoyé au format `geo_objects` :
  `{"type": "logement", "latitude": float, "longitude": float,
  "date_reference": str | None, "ref_externe": str, "source": "dpe-ademe",
  "metadata": {"adresse": str, "commune": str, "code_postal": str,
  "grade_dpe": str, "surface_m2": float | None, "periode_construction": str | None}}`.

**Payload brut ADEME** (champs RÉELS, vérifiés LIVE le 2026-08-05 via
`curl -G "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines" --data-urlencode "size=1"`) :
`numero_dpe`, `etiquette_dpe` (A à G), `adresse_ban`, `nom_commune_ban`,
`code_postal_ban`, `coordonnee_cartographique_x_ban`/`_y_ban` (Lambert93),
`date_etablissement_dpe`, `periode_construction` (une PÉRIODE, ex. `"avant 1948"` —
PAS une année exacte), `surface_habitable_logement`, `type_batiment` (`"maison"`,
`"immeuble"`, ...).

- [ ] **Step 1: Écrire les tests (payload figé, zéro réseau)**

Ajouter à `briques/geo/test_domaine.py` :

```python
# Payload RÉEL (figé, vérifié LIVE 2026-08-05 sur data.ademe.fr, dataset
# dpe03existant) — une maison à Carcassonne, grade F.
PAYLOAD_DPE = {
    "numero_dpe": "2611E0067705R",
    "etiquette_dpe": "F",
    "adresse_ban": "8 Rue Petite Cote de la Cite 11000 Carcassonne",
    "nom_commune_ban": "Carcassonne",
    "code_postal_ban": "11000",
    "coordonnee_cartographique_x_ban": 648048.69,
    "coordonnee_cartographique_y_ban": 6234349.45,
    "date_etablissement_dpe": "2025-03-14",
    "periode_construction": "avant 1948",
    "surface_habitable_logement": 88.7,
    "type_batiment": "maison",
}


def test_normaliser_logement_payload_reel():
    objet = domaine.normaliser_logement(PAYLOAD_DPE)
    assert objet["type"] == "logement"
    assert objet["latitude"] == pytest.approx(43.2077, abs=1e-3)
    assert objet["longitude"] == pytest.approx(2.3579, abs=1e-3)
    assert objet["ref_externe"] == "2611E0067705R"
    assert objet["source"] == "dpe-ademe"
    assert objet["date_reference"] == "2025-03-14"
    assert objet["metadata"] == {
        "adresse": "8 Rue Petite Cote de la Cite 11000 Carcassonne",
        "commune": "Carcassonne", "code_postal": "11000", "grade_dpe": "F",
        "surface_m2": 88.7, "periode_construction": "avant 1948",
    }


def test_normaliser_logement_sans_numero_dpe_rend_none():
    sans_id = {**PAYLOAD_DPE, "numero_dpe": None}
    assert domaine.normaliser_logement(sans_id) is None


def test_normaliser_logement_sans_coordonnees_rend_none():
    sans_coords = {**PAYLOAD_DPE, "coordonnee_cartographique_x_ban": None}
    assert domaine.normaliser_logement(sans_coords) is None


def test_normaliser_logement_champs_optionnels_absents():
    minimal = {"numero_dpe": "X1", "etiquette_dpe": "G",
              "coordonnee_cartographique_x_ban": 648048.69,
              "coordonnee_cartographique_y_ban": 6234349.45}
    objet = domaine.normaliser_logement(minimal)
    assert objet["metadata"] == {"adresse": "", "commune": "", "code_postal": "",
                                 "grade_dpe": "G", "surface_m2": None,
                                 "periode_construction": None}
    assert objet["date_reference"] is None
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/geo && python3 -m pytest test_domaine.py -k normaliser_logement -v`
Expected: FAIL avec `AttributeError: module 'domaine' has no attribute 'normaliser_logement'`

- [ ] **Step 3: Implémenter**

Ajouter dans `briques/geo/domaine.py`, à la suite de `lambert93_vers_wgs84` :

```python
def normaliser_logement(brute: dict) -> dict | None:
    """Payload brut de l'API ADEME (Observatoire DPE, dataset `dpe03existant`) → objet
    `geo_objects` type="logement", ou None si inexploitable (pas de numéro DPE, pas de
    coordonnées). `ref_externe` = numéro DPE (identifiant stable ADEME, sert l'upsert).
    `metadata` NE CONTIENT JAMAIS de nom de personne — uniquement l'adresse et les
    caractéristiques du bien (adresse, commune, grade, surface, période de
    construction). `periode_construction` est une PÉRIODE (ex. "avant 1948"), l'API ne
    fournit pas d'année exacte de construction."""
    numero_dpe = brute.get("numero_dpe")
    if not numero_dpe:
        return None
    try:
        x = float(brute.get("coordonnee_cartographique_x_ban"))
        y = float(brute.get("coordonnee_cartographique_y_ban"))
        latitude, longitude = lambert93_vers_wgs84(x, y)
    except (TypeError, ValueError):
        return None
    return {
        "type": "logement",
        "latitude": latitude,
        "longitude": longitude,
        "date_reference": brute.get("date_etablissement_dpe"),
        "ref_externe": numero_dpe,
        "source": "dpe-ademe",
        "metadata": {
            "adresse": brute.get("adresse_ban") or "",
            "commune": brute.get("nom_commune_ban") or "",
            "code_postal": brute.get("code_postal_ban") or "",
            "grade_dpe": brute.get("etiquette_dpe") or "",
            "surface_m2": brute.get("surface_habitable_logement"),
            "periode_construction": brute.get("periode_construction"),
        },
    }
```

Ajouter aussi l'entrée `"logement"` dans `REGLES_FRAICHEUR` (même règle que
`entreprise`, la date de référence étant celle du DPE) :

```python
REGLES_FRAICHEUR: dict[str, list[tuple[int, str]]] = {
    "entreprise": [(30, "rouge"), (90, "orange")],
    "logement": [(30, "rouge"), (90, "orange")],
    "_defaut": [(30, "rouge"), (90, "orange")],
}
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/geo && python3 -m pytest test_domaine.py -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/geo/domaine.py briques/geo/test_domaine.py
git commit -m "feat(geo): normalisation d'un logement DPE vers geo_objects"
```

---

### Task 3: `MockLogements` déterministe (`fournisseurs_logements.py`)

Nouveau fichier, séparé de `fournisseurs.py` (B2B) — zéro risque de régression sur
le pipeline Sirene qui tourne déjà en production.

**Files:**
- Create: `briques/geo/fournisseurs_logements.py`
- Test: `briques/geo/test_fournisseurs_logements.py`

**Interfaces:**
- Consumes: rien (Mock pur, aucune I/O).
- Produces: `fournisseurs_logements.MockLogements` (classe, attribut `nom = "mock-logements"`,
  méthode `peut_traiter(zone: dict) -> str | None`, méthode
  `logements_recents(zone: dict, depuis: str | None = None) -> list[dict]`), utilisé
  par `main.py` (Task 7).

- [ ] **Step 1: Écrire les tests**

Créer `briques/geo/test_fournisseurs_logements.py` :

```python
"""Fournisseurs de logements : mock déterministe, normalisation DPE (payload figé),
bascule env — même motif que test_fournisseurs.py (B2B)."""
import pytest

import domaine
import fournisseurs_logements as fl

ZONE = {"id": "zone-test-logements", "nom": "Carcassonne", "type": "logement",
        "communes": [{"code": "11069", "nom": "Carcassonne"}],
        "parametres": {"grades_dpe": ["E", "F", "G"]},
        "lat_min": 43.15, "lon_min": 2.30, "lat_max": 43.25, "lon_max": 2.40,
        "derniere_ingestion": None}


def test_mock_est_deterministe_et_couvre_les_grades_demandes():
    a = fl.MockLogements().logements_recents(ZONE)
    b = fl.MockLogements().logements_recents(ZONE)
    assert a == b and len(a) >= 5
    for objet in a:
        assert objet["type"] == "logement"
        assert ZONE["lat_min"] <= objet["latitude"] <= ZONE["lat_max"]
        assert ZONE["lon_min"] <= objet["longitude"] <= ZONE["lon_max"]
        assert objet["source"] == "simule-logement" and objet["ref_externe"]
        assert objet["metadata"]["grade_dpe"] in {"E", "F", "G"}
        assert "nom" not in objet["metadata"] and "proprietaire" not in objet["metadata"]


def test_mock_couvre_les_trois_pastilles():
    from datetime import datetime, timezone
    maintenant = datetime.now(timezone.utc)
    pastilles = {domaine.pastille_fraicheur("logement", o["date_reference"], maintenant)
                 for o in fl.MockLogements().logements_recents(ZONE)}
    assert pastilles == {"rouge", "orange", "bleu"}


def test_mock_traite_toute_zone():
    assert fl.MockLogements().peut_traiter(ZONE) is None
    assert fl.MockLogements().peut_traiter({**ZONE, "communes": []}) is None
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/geo && python3 -m pytest test_fournisseurs_logements.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'fournisseurs_logements'`

- [ ] **Step 3: Implémenter**

Créer `briques/geo/fournisseurs_logements.py` :

```python
"""Fournisseurs de LOGEMENTS — famille séparée de `fournisseurs.py` (entreprises) :
fichier distinct pour que le pipeline Sirene existant ne coure aucun risque de
régression. Contrat identique en esprit (mock déterministe d'abord, fournisseur réel
derrière une bascule env explicite), mais une méthode différente
(`logements_recents`, pas `entreprises_recentes`) — un logement n'a ni SIRET ni site
officiel, ce n'est pas la même forme d'objet.

`MockLogements` : logements SIMULÉS, déterministes par zone (seed = id de zone).
JAMAIS de nom de personne dans les metadata — seulement adresse et caractéristiques
du bien, cohérent avec la contrainte légale (fichiers fonciers inaccessibles)."""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

_ADRESSES_SIMULEES = ["12 Rue des Lilas", "4 Impasse du Moulin", "7 Chemin de la Combe",
                      "21 Rue Basse", "3 Place du Marché", "9 Rue Haute",
                      "15 Allée des Tilleuls", "2 Rue de la Fontaine"]
_GRADES_SIMULES = ["F", "G", "E", "F", "E", "G", "F", "E"]
_AGES_JOURS = [3, 15, 45, 70, 120, 200, 10, 60]   # couvre rouge / orange / bleu


class MockLogements:
    """Déterministe (seed = id de zone) : deux appels produisent les MÊMES points."""
    nom = "mock-logements"

    def peut_traiter(self, zone: dict) -> str | None:
        return None   # le simulé traite toute zone

    def logements_recents(self, zone: dict, depuis: str | None = None) -> list[dict]:
        alea = random.Random(zone["id"])
        maintenant = datetime.now(timezone.utc)
        commune = (zone.get("communes") or [{"nom": zone.get("nom", "")}])[0]["nom"]
        grades_demandes = (zone.get("parametres") or {}).get("grades_dpe") or ["E", "F", "G"]
        objets = []
        for i, (adresse, age) in enumerate(zip(_ADRESSES_SIMULEES, _AGES_JOURS)):
            lat = alea.uniform(zone["lat_min"], zone["lat_max"])
            lon = alea.uniform(zone["lon_min"], zone["lon_max"])
            grade = _GRADES_SIMULES[i % len(_GRADES_SIMULES)]
            if grade not in grades_demandes:
                grade = grades_demandes[i % len(grades_demandes)]
            objets.append({
                "type": "logement", "latitude": lat, "longitude": lon,
                "date_reference": (maintenant - timedelta(days=age)).date().isoformat(),
                "ref_externe": f"simule-logement-{zone['id'][:8]}-{i}",
                "source": "simule-logement",
                "metadata": {"adresse": f"{adresse}, {commune}", "commune": commune,
                             "code_postal": "", "grade_dpe": grade,
                             "surface_m2": 70.0 + i * 5, "periode_construction": "avant 1948"},
            })
        return objets
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/geo && python3 -m pytest test_fournisseurs_logements.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/geo/fournisseurs_logements.py briques/geo/test_fournisseurs_logements.py
git commit -m "feat(geo): MockLogements déterministe (fournisseur logements, mock)"
```

---

### Task 4: `DpeAdeme` — fournisseur réel + factory (`fournisseurs_logements.py`)

**Contrat API vérifié LIVE le 2026-08-05** (requêtes réelles exécutées pendant la
conception) :

```
GET https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines
    ?code_insee_ban_in=<codes INSEE séparés par virgule>
    &etiquette_dpe_in=<grades séparés par virgule, ex. E,F,G>
    &type_batiment_eq=maison
    &size=100
    &select=numero_dpe,etiquette_dpe,adresse_ban,nom_commune_ban,code_postal_ban,
            coordonnee_cartographique_x_ban,coordonnee_cartographique_y_ban,
            date_etablissement_dpe,periode_construction,surface_habitable_logement
```

Réponse : `{"total": int, "next": "<URL complète pour la page suivante>" | absent,
"results": [...]}`. **Pagination par curseur** (le champ `next` est une URL COMPLÈTE
qui embarque déjà tous les paramètres + un curseur `after` — pas une pagination par
numéro de page comme l'API Sirene). Sans clé API. Le paramètre générique `qs=` (
recherche libre data-fair) a renvoyé 403 depuis l'environnement où cette vérification
a été faite (pare-feu/réseau, cause non déterminée) — les filtres `<champ>_eq=`/
`<champ>_in=` utilisés ci-dessus fonctionnent et ont été vérifiés à l'instant, donc
c'est ce qu'on utilise, sans dépendre de `qs`.

`type_batiment_eq=maison` est un choix délibéré : le cas d'usage (convaincre UN
propriétaire d'installer des panneaux) ne s'applique pas à un logement en
copropriété (décision collective, pas individuelle) — filtré à la source.

**Files:**
- Modify: `briques/geo/fournisseurs_logements.py`
- Test: `briques/geo/test_fournisseurs_logements.py`

**Interfaces:**
- Consumes: `domaine.normaliser_logement` (Task 2).
- Produces: `fournisseurs_logements.DpeAdeme` (classe, `nom = "dpe-ademe"`),
  `fournisseurs_logements.etat_config_logements() -> dict`,
  `fournisseurs_logements.fournisseur_logements() -> MockLogements | DpeAdeme` —
  utilisés par `main.py` (Task 7).

- [ ] **Step 1: Écrire les tests (HTTP mocké, zéro réseau réel)**

Ajouter à `briques/geo/test_fournisseurs_logements.py` :

```python
import httpx


# Payload RÉEL (figé, vérifié LIVE 2026-08-05, dataset dpe03existant, 2 résultats).
PAGE_1_ADEME = {
    "total": 422,
    "next": "https://data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/"
            "lines?size=1&after=CURSEUR-FICTIF",
    "results": [{
        "numero_dpe": "2611E0206181R", "etiquette_dpe": "E",
        "adresse_ban": "1 Rue Fictive 11000 Carcassonne", "nom_commune_ban": "Carcassonne",
        "code_postal_ban": "11000", "coordonnee_cartographique_x_ban": 648048.69,
        "coordonnee_cartographique_y_ban": 6234349.45,
        "date_etablissement_dpe": "2025-01-01", "periode_construction": "avant 1948",
        "surface_habitable_logement": 88.7,
    }],
}
PAGE_2_ADEME_DERNIERE = {"total": 422, "results": [{
    "numero_dpe": "2111E0136972P", "etiquette_dpe": "F",
    "adresse_ban": "2 Rue Fictive 11000 Carcassonne", "nom_commune_ban": "Carcassonne",
    "code_postal_ban": "11000", "coordonnee_cartographique_x_ban": 648048.69,
    "coordonnee_cartographique_y_ban": 6234349.45,
    "date_etablissement_dpe": "2025-01-02", "periode_construction": "avant 1948",
    "surface_habitable_logement": 60.0,
}]}   # pas de clé "next" = dernière page


class _FauxClientAdeme:
    """Simule httpx.Client : 1er GET → PAGE_1 (a un `next`), 2e GET (sur l'URL `next`
    reçue) → PAGE_2 (sans `next`, la boucle s'arrête)."""
    def __init__(self, *a, **k):
        self.appels = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self.appels += 1
        corps = PAGE_1_ADEME if self.appels == 1 else PAGE_2_ADEME_DERNIERE
        return httpx.Response(200, json=corps, request=httpx.Request("GET", url))


def test_dpe_ademe_pagine_par_curseur_jusqua_next_absent(monkeypatch):
    monkeypatch.setattr(fl.httpx, "Client", _FauxClientAdeme)
    objets = fl.DpeAdeme().logements_recents(ZONE)
    assert len(objets) == 2
    assert {o["ref_externe"] for o in objets} == {"2611E0206181R", "2111E0136972P"}
    assert all(o["type"] == "logement" for o in objets)


def test_dpe_ademe_peut_traiter_exige_des_communes():
    sans_communes = {**ZONE, "communes": []}
    assert "commune" in fl.DpeAdeme().peut_traiter(sans_communes).lower()
    assert fl.DpeAdeme().peut_traiter(ZONE) is None


def test_bascule_fournisseur_logements_par_env(monkeypatch):
    monkeypatch.delenv("GEO_FOURNISSEUR_LOGEMENTS", raising=False)
    assert fl.etat_config_logements()["fournisseur"] == "mock-logements"
    assert isinstance(fl.fournisseur_logements(), fl.MockLogements)
    monkeypatch.setenv("GEO_FOURNISSEUR_LOGEMENTS", "reel")
    etat = fl.etat_config_logements()
    assert etat["fournisseur"] == "dpe-ademe" and etat["configure"]
    assert isinstance(fl.fournisseur_logements(), fl.DpeAdeme)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/geo && python3 -m pytest test_fournisseurs_logements.py -k "ademe or bascule" -v`
Expected: FAIL avec `AttributeError: module 'fournisseurs_logements' has no attribute 'DpeAdeme'`

- [ ] **Step 3: Implémenter**

Ajouter en tête de `briques/geo/fournisseurs_logements.py` (après le docstring) :

```python
import httpx

import domaine

_DPE_API_URL = os.getenv("GEO_DPE_URL",
                         "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant")
_CHAMPS_DPE = ("numero_dpe,etiquette_dpe,adresse_ban,nom_commune_ban,code_postal_ban,"
              "coordonnee_cartographique_x_ban,coordonnee_cartographique_y_ban,"
              "date_etablissement_dpe,periode_construction,surface_habitable_logement")
```

Puis à la suite de `MockLogements` :

```python
class DpeAdeme:
    """API ouverte ADEME (Observatoire DPE, dataset `dpe03existant`), SANS clé, bascule
    explicite `GEO_FOURNISSEUR_LOGEMENTS=reel`. Filtre par communes (code INSEE) × grade
    DPE — nécessite des communes (pas de recherche par rayon sur cette API, contrairement
    à Sirene `/near_point`). Ne cible que les MAISONS (`type_batiment_eq=maison`) : le
    cas d'usage (convaincre un propriétaire individuel) ne s'applique pas à un logement
    en copropriété. Pagination par CURSEUR (le champ `next` de la réponse est l'URL
    complète de la page suivante), pas par numéro de page."""
    nom = "dpe-ademe"

    def peut_traiter(self, zone: dict) -> str | None:
        if not zone.get("communes"):
            return (f"zone « {zone['nom']} » ignorée : le fournisseur {self.nom} "
                    "nécessite des communes (code INSEE) — pas de recherche par rayon "
                    "sur l'API ADEME.")
        return None

    def logements_recents(self, zone: dict, depuis: str | None = None) -> list[dict]:
        codes = ",".join(c["code"] for c in zone["communes"])
        grades = (zone.get("parametres") or {}).get("grades_dpe") or ["E", "F", "G"]
        params = {"code_insee_ban_in": codes, "etiquette_dpe_in": ",".join(grades),
                  "type_batiment_eq": "maison", "size": 100, "select": _CHAMPS_DPE}
        pages_max = int(os.getenv("GEO_PAGES_MAX_LOGEMENTS", "10"))
        objets: list[dict] = []
        url, params_actuels = f"{_DPE_API_URL}/lines", params
        with httpx.Client(timeout=30) as client:
            for _ in range(pages_max):
                r = client.get(url, params=params_actuels)
                r.raise_for_status()
                d = r.json()
                for brute in d.get("results", []):
                    objet = domaine.normaliser_logement(brute)
                    if objet:
                        objets.append(objet)
                url = d.get("next")
                if not url:
                    break
                params_actuels = None   # `next` embarque déjà tous les paramètres
        return objets


def etat_config_logements() -> dict:
    if os.getenv("GEO_FOURNISSEUR_LOGEMENTS", "").strip().lower() == "reel":
        return {"configure": True, "fournisseur": DpeAdeme.nom,
                "message": "Données RÉELLES : ADEME Observatoire DPE (data.ademe.fr). "
                           "Veille par zone à communes × grade DPE (maisons individuelles)."}
    return {"configure": False, "fournisseur": MockLogements.nom,
            "message": "Données SIMULÉES (mock honnête) : posez "
                       "GEO_FOURNISSEUR_LOGEMENTS=reel pour brancher l'API ADEME."}


def fournisseur_logements() -> "MockLogements | DpeAdeme":
    if etat_config_logements()["configure"]:
        return DpeAdeme()
    return MockLogements()
```

- [ ] **Step 4: Lancer tous les tests du fichier**

Run: `cd briques/geo && python3 -m pytest test_fournisseurs_logements.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add briques/geo/fournisseurs_logements.py briques/geo/test_fournisseurs_logements.py
git commit -m "feat(geo): fournisseur DPE ADEME réel (bascule GEO_FOURNISSEUR_LOGEMENTS)"
```

---

### Task 5: Zones — colonne `parametres` (`stockage.py`)

**Files:**
- Modify: `briques/geo/stockage.py`
- Test: `briques/geo/test_ingestion.py`

**Interfaces:**
- Produces: `stockage.creer_zone(..., parametres: dict | None = None)` — le dict
  `zone` renvoyé par `_zone_dict` gagne la clé `"parametres"`. Utilisé par `main.py`
  (Task 6).

- [ ] **Step 1: Écrire le test de migration douce + round-trip**

Ajouter à `briques/geo/test_ingestion.py` :

```python
def test_zone_porte_ses_parametres():
    r = client.post("/zones", json={"nom": "Passoires Carcassonne", "type": "logement",
                                    "communes": ["11000"],
                                    "parametres": {"grades_dpe": ["E", "F", "G"]}},
                    headers=CLE)
    assert r.status_code == 201
    assert r.json()["parametres"] == {"grades_dpe": ["E", "F", "G"]}


def test_zone_sans_parametres_rend_dict_vide():
    r = client.post("/zones", json={"nom": "Sans param", "lat": 43.6, "lon": 2.2,
                                    "rayon_km": 10}, headers=CLE)
    assert r.json()["parametres"] == {}
```

(Ce test utilise `communes: ["11000"]` — vérifier que `geographie.resoudre_communes`
est déjà mocké ailleurs dans ce fichier de test, sinon le test réseau existant
`test_communes.py` montre le motif `_FauxGeoAPI` à réutiliser ; si
`test_ingestion.py` ne mocke pas encore `geographie`, ajouter le même mock que
`test_communes.py::_FauxGeoAPI` en tête de ce test.)

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/geo && python3 -m pytest test_ingestion.py -k parametres -v`
Expected: FAIL (soit 422 de validation Pydantic, soit `KeyError: 'parametres'`)

- [ ] **Step 3: Implémenter la migration + le round-trip**

Dans `briques/geo/stockage.py`, fonction `init()`, ajouter à la liste des
migrations douces existante :

```python
        for alter in ("ALTER TABLE geo_zones ADD COLUMN naf TEXT",
                      "ALTER TABLE geo_zones ADD COLUMN communes TEXT",
                      "ALTER TABLE geo_zones ADD COLUMN parametres TEXT"):
            try:
                c.execute(alter)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente
```

Dans `_zone_dict` :

```python
def _zone_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "lat_min": r["lat_min"], "lon_min": r["lon_min"],
            "lat_max": r["lat_max"], "lon_max": r["lon_max"], "type": r["type"],
            "naf": r["naf"], "communes": json.loads(r["communes"] or "[]"),
            "parametres": json.loads(r["parametres"] or "{}"),
            "active": bool(r["active"]), "cree_le": r["cree_le"],
            "derniere_ingestion": r["derniere_ingestion"]}
```

Dans `creer_zone` (signature ET corps) :

```python
def creer_zone(tenant: str, nom: str, bbox: tuple[float, float, float, float],
               type_: str = "entreprise", naf: str | None = None,
               communes: list[dict] | None = None,
               parametres: dict | None = None) -> dict:
    zid = _id()
    with _conn() as c:
        c.execute(
            "INSERT INTO geo_zones (id, tenant, nom, lat_min, lon_min, lat_max, lon_max,"
            " type, naf, communes, parametres, cree_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (zid, tenant, nom, bbox[0], bbox[1], bbox[2], bbox[3], type_, naf,
             json.dumps(communes or [], ensure_ascii=False),
             json.dumps(parametres or {}, ensure_ascii=False), _maintenant()))
        r = c.execute("SELECT * FROM geo_zones WHERE id = ?", (zid,)).fetchone()
    return _zone_dict(r)
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/geo && python3 -m pytest test_ingestion.py -v`
Expected: PASS (tous les tests, anciens et nouveaux — la base de test est recréée à
chaque run via `conftest.py`, donc pas de base existante à migrer réellement ici ;
la migration douce est surtout documentée pour la base de PRODUCTION existante)

- [ ] **Step 5: Commit**

```bash
git add briques/geo/stockage.py briques/geo/test_ingestion.py
git commit -m "feat(geo): zones — colonne parametres (JSON, migration douce)"
```

---

### Task 6: `main.py` — `ZoneEntree.parametres` + branchement `creer_zone`

**Files:**
- Modify: `briques/geo/main.py`

**Interfaces:**
- Consumes: `stockage.creer_zone(..., parametres=...)` (Task 5).
- Produces: route `POST /zones` accepte et renvoie `parametres`.

- [ ] **Step 1: Modifier `ZoneEntree` et `creer_zone`**

Dans `briques/geo/main.py`, `ZoneEntree` :

```python
class ZoneEntree(BaseModel):
    nom: str
    type: str = "entreprise"
    naf: Optional[str] = None
    communes: Optional[list[str]] = None
    bbox: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    rayon_km: Optional[float] = None
    parametres: Optional[dict] = None   # ex. {"grades_dpe": ["E","F","G"]} pour type=logement
```

Dans `creer_zone` (route `POST /zones`), dernier `return` :

```python
    return stockage.creer_zone(
        tenant, corps.nom, boite, type_=corps.type, naf=corps.naf,
        communes=[{"code": c["code"], "nom": c["nom"]} for c in communes],
        parametres=corps.parametres)
```

- [ ] **Step 2: Lancer la suite complète du fichier pour vérifier la non-régression**

Run: `cd briques/geo && python3 -m pytest test_ingestion.py -v`
Expected: PASS (identique à la fin de la Task 5 — cette task ne fait que relier ce
qui a déjà été testé)

- [ ] **Step 3: Commit**

```bash
git add briques/geo/main.py
git commit -m "feat(geo): route /zones accepte et renvoie parametres"
```

---

### Task 7: Ingestion — dispatch par type de zone (`main.py`)

**Files:**
- Modify: `briques/geo/main.py`
- Test: `briques/geo/test_ingestion.py`

**Interfaces:**
- Consumes: `fournisseurs_logements.fournisseur_logements()` (Task 4),
  `fournisseurs.fournisseur()` (existant).
- Produces: `POST /ingestion/executer` gagne la clé de réponse
  `"fournisseur_logements"` (additive — `"fournisseur"` garde EXACTEMENT son
  sens actuel : le fournisseur entreprises configuré).

- [ ] **Step 1: Écrire le test (zone logement + zone entreprise dans le même run)**

Ajouter à `briques/geo/test_ingestion.py` :

```python
def test_ingestion_traite_zone_logement_avec_son_propre_fournisseur():
    cle = {"X-API-Key": "ingestion-logements"}
    client.post("/zones", json={"nom": "Passoires", "type": "logement",
                                "communes": ["11000"],
                                "parametres": {"grades_dpe": ["E", "F", "G"]}},
                headers=cle)
    res = client.post("/ingestion/executer", headers=cle).json()
    assert res["fournisseur"] == "mock"                  # entreprises : inchangé
    assert res["fournisseur_logements"] == "mock-logements"
    assert res["nouveaux"] >= 5
    objets = client.get("/objets", params={"bbox": "43.0,2.0,43.5,2.5"},
                        headers=cle).json()
    assert any(o["type"] == "logement" for o in objets["objets"])


def test_ingestion_zone_logement_sans_communes_avertit():
    cle = {"X-API-Key": "ingestion-logements-sans-communes"}
    client.post("/zones", json={"nom": "Rayon logement", "type": "logement",
                                "lat": 43.6, "lon": 2.2, "rayon_km": 10}, headers=cle)
    res = client.post("/ingestion/executer", headers=cle).json()
    assert res["nouveaux"] == 0
    assert len(res["avertissements"]) == 1 and "commune" in res["avertissements"][0].lower()
```

Corriger le test existant `test_ingestion_sans_zone_ne_fait_rien` (le format de
réponse gagne une clé, l'égalité stricte du dict doit en tenir compte) :

```python
def test_ingestion_sans_zone_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(main, "_pousser_connexion",
                        lambda t: (_ for _ in ()).throw(AssertionError("pas de push")))
    res = client.post("/ingestion/executer",
                      headers={"X-API-Key": "personne"}).json()
    assert res == {"zones": 0, "nouveaux": 0, "maj": 0, "fournisseur": "mock",
                   "fournisseur_logements": "mock-logements", "avertissements": []}
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/geo && python3 -m pytest test_ingestion.py -v`
Expected: FAIL (`test_ingestion_traite_zone_logement_avec_son_propre_fournisseur` :
`KeyError: 'fournisseur_logements'` ; `test_ingestion_sans_zone_ne_fait_rien` :
dict inégal)

- [ ] **Step 3: Implémenter le dispatch dans `executer_ingestion`**

Remplacer dans `briques/geo/main.py` :

```python
@app.post("/ingestion/executer")
def executer_ingestion(tenant: str = Depends(tenant_actuel)):
    """Passe la veille sur toutes les zones ACTIVES du tenant : fournisseur dédié au TYPE
    de la zone (Sirene pour entreprise/association, DPE ADEME pour logement — mock ou
    réel selon la bascule env de chacun) → upsert par référence externe → décompte
    honnête nouveaux/mis-à-jour. Appelée par l'horloge du Cœur ou à la main. Push 🗺️ si
    découvertes."""
    zones = stockage.lister_zones(tenant, seulement_actives=True)
    nouveaux, maj = 0, 0
    avertissements: list[str] = []
    for zone in zones:
        if zone.get("type") == "logement":
            prov = fournisseurs_logements.fournisseur_logements()
            recuperer = prov.logements_recents
        else:
            prov = fournisseurs.fournisseur()
            recuperer = prov.entreprises_recentes
        message = prov.peut_traiter(zone)
        if message:
            avertissements.append(message)
            continue
        try:
            trouves = recuperer(zone, depuis=zone["derniere_ingestion"])
        except Exception as ex:  # noqa: BLE001 — une zone en échec ne bloque pas les autres
            logger.warning("Geo ingestion zone « %s » : %s", zone["nom"], ex)
            continue
        for objet in trouves:
            _, est_nouveau = stockage.upsert_objet(
                tenant, type_=objet["type"], latitude=objet["latitude"],
                longitude=objet["longitude"], date_reference=objet["date_reference"],
                source=objet["source"], ref_externe=objet["ref_externe"],
                metadata=objet["metadata"])
            nouveaux += est_nouveau
            maj += not est_nouveau
        stockage.maj_derniere_ingestion(zone["id"])
    if nouveaux:
        _pousser_connexion(f"🗺️ Veille geo : {nouveaux} nouvelle(s) entreprise(s)/"
                           f"logement(s) détecté(s) sur {len(zones)} zone(s).")
    return {"zones": len(zones), "nouveaux": nouveaux, "maj": maj,
            "fournisseur": fournisseurs.etat_config()["fournisseur"],
            "fournisseur_logements": fournisseurs_logements.etat_config_logements()["fournisseur"],
            "avertissements": avertissements}
```

Ajouter l'import en tête du fichier (à côté des imports `fournisseurs`, `stockage`) :

```python
import fournisseurs_logements
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/geo && python3 -m pytest test_ingestion.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Lancer TOUTE la suite geo pour vérifier la non-régression globale**

Run: `cd briques/geo && python3 -m pytest -v`
Expected: PASS (tous les fichiers de test de la brique)

- [ ] **Step 6: Commit**

```bash
git add briques/geo/main.py briques/geo/test_ingestion.py
git commit -m "feat(geo): ingestion route les zones logement vers le fournisseur DPE"
```

---

### Task 8: `enrichir-lot` — branche logement (`main.py`)

Le second étage du pipeline (`/prospection/enrichir-lot`) fait aujourd'hui une
recherche web du « site officiel » — sans objet pour un logement. Pour ce type, un
objet déjà ingéré (adresse + grade DPE connus) est un prospect complet dès le
départ.

**Files:**
- Modify: `briques/geo/main.py`
- Test: `briques/geo/test_prospection.py`

**Interfaces:**
- Produces: `_prospect_crm_logement(objet: dict) -> dict` (nouvelle fonction),
  `POST /prospection/enrichir-lot` avec `type="logement"` (ou `zone_id` d'une zone
  `logement`) ne fait plus AUCUN appel à la brique recherche.

- [ ] **Step 1: Écrire les tests (zéro mock réseau nécessaire pour la branche logement)**

Ajouter à `briques/geo/test_prospection.py` :

```python
def _objet_logement(cle, adresse, grade="F"):
    r = client.post("/objets", headers=cle,
                    json={"type": "logement", "latitude": 43.606, "longitude": 2.24,
                          "metadata": {"adresse": adresse, "commune": "CASTRES",
                                      "code_postal": "81100", "grade_dpe": grade,
                                      "surface_m2": 90.0, "periode_construction": "avant 1948"}})
    return r.json()["id"]


def test_prospecter_lot_logement_saute_la_recherche_web():
    """Aucun mock `enrichissement.httpx` posé : si le code appelait la recherche web
    pour un logement, ce test échouerait par une vraie tentative réseau (timeout/erreur)
    plutôt que par une assertion — la garantie est structurelle, pas un mock qui espionne."""
    cle = {"X-API-Key": "lot-logement"}
    _objet_logement(cle, "12 Rue des Lilas 81100 Castres")
    _objet_logement(cle, "4 Impasse du Moulin 81100 Castres", grade="G")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "type": "logement", "limite": 10})
    assert r.status_code == 200
    corps = r.json()
    assert corps["compte"]["ok"] == 2
    assert len(corps["prospects"]) == 2
    p = corps["prospects"][0]
    assert p["adresse"] and p["grade_dpe"] in {"F", "G"}
    assert "email" not in p and "entreprise" not in p and "nom" not in p


def test_prospecter_lot_logement_via_zone_id():
    cle = {"X-API-Key": "lot-logement-zone"}
    zone = client.post("/zones", headers=cle,
                       json={"nom": "Castres logements", "type": "logement",
                             "bbox": BBOX}).json()
    _objet_logement(cle, "7 Chemin de la Combe 81100 Castres")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"zone_id": zone["id"], "limite": 10})
    assert r.status_code == 200 and r.json()["compte"]["ok"] == 1
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/geo && python3 -m pytest test_prospection.py -k logement -v`
Expected: FAIL (`KeyError: 'adresse'` — le code actuel renvoie la vue `_prospect_crm`
entreprise pour tous les types)

- [ ] **Step 3: Implémenter**

Ajouter dans `briques/geo/main.py`, à la suite de `_prospect_crm` :

```python
def _prospect_crm_logement(objet: dict) -> dict:
    """Vue « prête pour le CRM » d'un logement : pas d'email/téléphone/site (n'existent
    pas pour un bien), JAMAIS de nom de personne (contrainte légale — fichiers fonciers
    inaccessibles à une entreprise commerciale) — seulement l'adresse et les
    caractéristiques du bien."""
    m = objet.get("metadata") or {}
    return {"objet_id": objet["id"], "adresse": m.get("adresse"), "commune": m.get("commune"),
            "code_postal": m.get("code_postal"), "grade_dpe": m.get("grade_dpe"),
            "surface_m2": m.get("surface_m2"), "periode_construction": m.get("periode_construction"),
            "ref_externe": objet.get("ref_externe"), "source": objet.get("source")}
```

Modifier `enrichir_lot`, dans la boucle `for objet in objets:` — insérer la branche
logement AVANT le code entreprise existant :

```python
    for objet in objets:
        if type_ == "logement":
            prospects.append(_prospect_crm_logement(objet))
            compte["ok"] += 1
            continue
        meta = objet["metadata"]
        if not corps.force and (meta.get("email") or meta.get("site")):
            compte["deja_enrichi"] += 1
        else:
            try:
                rapport, objet = _enrichir_et_enregistrer(tenant, objet)
                compte[rapport["statut"]] = compte.get(rapport["statut"], 0) + 1
            except httpx.HTTPError as e:
                stockage.journaliser_enrichissement(tenant, objet["id"], statut="erreur",
                                                    resultat={"detail": str(e)})
                compte["erreur"] += 1
            meta = objet["metadata"]
        if meta.get("email") or meta.get("telephone") or meta.get("site"):
            prospects.append(_prospect_crm(objet))
```

(Le reste de la fonction — signature, résolution de `type_`/`boite`, `return` final
— ne change pas.)

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/geo && python3 -m pytest test_prospection.py -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Lancer TOUTE la suite geo**

Run: `cd briques/geo && python3 -m pytest -v`
Expected: PASS (tous les fichiers)

- [ ] **Step 6: Commit**

```bash
git add briques/geo/main.py briques/geo/test_prospection.py
git commit -m "feat(geo): enrichir-lot saute la recherche web pour les logements"
```

---

## Self-Review

**Couverture spec** (`docs/superpowers/specs/2026-08-05-prospection-b2c-signal-identite-design.md`,
section « Backend — geo ») : `normaliser_logement` (Task 2) ✓, `REGLES_FRAICHEUR`
(Task 2) ✓, `MockLogements`/`DpeAdeme` fichier séparé (Task 3-4) ✓, migration
`parametres` (Task 5) ✓, branchement ingestion (Task 7) ✓, branchement
`enrichir-lot` + `_prospect_crm_logement` (Task 8) ✓. La correction apportée à la
spec (deux étages distincts ingestion/enrichir-lot) est reflétée dans les Tasks
7 et 8 séparément, pas fusionnée à tort.

**Aucun nom de personne** : vérifié explicitement dans
`test_prospecter_lot_logement_saute_la_recherche_web` (`"email" not in p`, etc.) et
`test_mock_est_deterministe_et_couvre_les_grades_demandes` (`"nom" not in
metadata`) — le garde-fou légal a son propre test, pas une vérification incidente.

**Cohérence des types** : `logements_recents(zone, depuis=None) -> list[dict]` a la
même forme dans `MockLogements` (Task 3) et `DpeAdeme` (Task 4).
`fournisseur_logements()` renvoie l'un ou l'autre (Task 4), consommé identiquement
par `main.py` (Task 7) via `prov.logements_recents` — pas de divergence de nom de
méthode entre les deux classes.

**Hors périmètre de ce plan** (rappel, cf. spec) : combinaison multi-critères
(un seul fournisseur logement existe), imagerie aérienne, résolution d'identité
propriétaire.
