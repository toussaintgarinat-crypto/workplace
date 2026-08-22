# World Engine — Génome Cosmique Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nouvelle brique `briques/world-engine` (port 6220) exposant `POST /genome/croiser`, qui croise 2 profils cosmiques (via la brique `personnages`) pour produire un enfant au thème astronomiquement réel, avec un récit d'hérédité en post-traitement.

**Architecture:** Brique FastAPI stateless standard (CORS + clé API), qui n'importe AUCUN code de `personnages` — elle l'appelle en HTTP (`httpx.AsyncClient`) via `PERSONNAGES_URL`. Toute la logique métier pure (fusion de description, conversion signe→date, comparaison des 10 corps) vit dans `fusion.py`, testable sans réseau. `personnages_client.py` isole les appels HTTP (mockés en test via `respx`). `main.py` orchestre les deux.

**Tech Stack:** FastAPI, httpx (client async), pytest + pytest-asyncio + respx (tests), Docker.

## Global Constraints

- Aucune persistance (stateless uniquement) — voir spec, section Architecture.
- `world-engine` ne duplique jamais le moteur astro : tout calcul de thème passe par un appel HTTP à `personnages` (`/holistique/portrait`, `/holistique/recherche-inverse`).
- Le lieu de naissance de l'enfant (`latitude_enfant`, `longitude_enfant`) est un paramètre **obligatoire** de l'appel — jamais deviné ni moyenné.
- `exemple_date` de `/holistique/recherche-inverse` n'est **jamais** utilisé comme date machine (voir spec, correction de conception) — seul le champ structuré `signes[0]["signe"]` est exploité.
- Repli honnête : `personnages` injoignable → 502 ; fiche parent invalide → 422 propagée telle quelle ; aucun signe reconnu dans la description fusionnée → 422 (jamais de repli sur une valeur arbitraire).
- Port de la brique : **6220** (premier port libre après 6210, vérifié dans tous les `manifest.json` existants).
- Référence de spec : `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`.

---

## Task 1: Squelette de la brique

**Files:**
- Create: `briques/world-engine/requirements.txt`
- Create: `briques/world-engine/requirements-dev.txt`
- Create: `briques/world-engine/Dockerfile`
- Create: `briques/world-engine/README.md`
- Create: `briques/world-engine/conftest.py`
- Create: `briques/world-engine/main.py` (squelette minimal : CORS, auth, `/sante`)
- Test: `briques/world-engine/test_api.py` (juste `/sante` et l'auth à ce stade)

**Interfaces:**
- Produces: `main.app` (instance FastAPI), `main.cle_api` (dépendance FastAPI d'auth), `main.API_KEYS` (set).

- [ ] **Step 1: Créer `requirements.txt`**

```
# Brique world-engine — croisement de profils cosmiques. Aucune lib lourde : la
# logique est du Python pur (stdlib), seul l'appel à `personnages` sort en HTTP.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

- [ ] **Step 2: Créer `requirements-dev.txt`**

```
# Dépendances de test uniquement (le socle pytest/pytest-asyncio/httpx est fourni
# par scripts/tests_briques.sh). respx simule les réponses de `personnages` sans
# réseau — indispensable puisque cette brique ne fait QUE des appels sortants.
respx==0.22.0
```

- [ ] **Step 3: Créer `Dockerfile`**

```
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6220"]
```

- [ ] **Step 4: Créer `README.md`**

```markdown
# world-engine — Génome Cosmique

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir la spec : `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`.

Stateless : aucune donnée n'est persistée. Dépend de la brique `personnages`
(port 5900) en HTTP — pas de duplication du moteur astro.

Port : 6220.
```

- [ ] **Step 5: Créer `conftest.py`**

```python
"""Config de test : mode auth OUVERT avant tout import de main (comme personnages)."""
import os

os.environ.setdefault("API_KEYS", "")
```

- [ ] **Step 6: Écrire le squelette `main.py`**

```python
"""Brique « world-engine » — croisement de 2 profils cosmiques (génome cosmique).

Stateless : entrée → sortie, rien stocké. Dépend de `personnages` (port 5900) en
HTTP pour tout calcul astral — ne duplique jamais le moteur.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="World Engine — Génome Cosmique", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
if os.getenv("WORLD_ENGINE_KEY", "").strip():
    API_KEYS.add(os.getenv("WORLD_ENGINE_KEY").strip())


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API (header X-API-Key ou Authorization: Bearer).

    API_KEYS vide (défaut dev) = mode ouvert. Même motif que `briques/personnages`."""
    if not API_KEYS:
        return "public"
    cle = x_api_key
    if not cle and authorization and authorization.startswith("Bearer "):
        cle = authorization[7:]
    if cle not in API_KEYS:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return cle


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "brique": "world-engine"}
```

- [ ] **Step 7: Écrire `test_api.py` (santé + auth)**

```python
"""Tests API de world-engine."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_auth_rejette_cle_absente_quand_api_keys_configuree(monkeypatch):
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    c = TestClient(main.app)
    assert c.get("/sante").status_code == 200  # /sante n'est pas protégée
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
```

- [ ] **Step 8: Lancer les tests**

Run: `cd briques/world-engine && python3 -m pip install -r requirements.txt -r requirements-dev.txt pytest pytest-asyncio && python3 -m pytest . -q`
Expected: `2 passed`

- [ ] **Step 9: Commit**

```bash
git add briques/world-engine/requirements.txt briques/world-engine/requirements-dev.txt \
        briques/world-engine/Dockerfile briques/world-engine/README.md \
        briques/world-engine/conftest.py briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): squelette brique (santé + auth)"
```

---

## Task 2: `fusion.py` — conversion signe → date

**Files:**
- Create: `briques/world-engine/fusion.py`
- Test: `briques/world-engine/test_fusion.py`

**Interfaces:**
- Consumes: rien (fonction pure).
- Produces: `fusion.SIGNE_PLAGES: dict[str, tuple[int, int]]`, `fusion.date_pour_signe(signe: str, annee: int) -> str`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
"""Tests de fusion.py — logique pure de world-engine, sans réseau."""
import fusion


def test_date_pour_signe_vierge():
    assert fusion.date_pour_signe("Vierge", 1990) == "1990-08-23"


def test_date_pour_signe_capricorne_reste_dans_l_annee_donnee():
    """Capricorne est à cheval sur le nouvel an (22 déc → 19 jan) : on ancre sur le
    DÉBUT de plage (22 décembre), qui reste toujours dans l'année demandée."""
    assert fusion.date_pour_signe("Capricorne", 2000) == "2000-12-22"


def test_date_pour_signe_verseau_janvier():
    assert fusion.date_pour_signe("Verseau", 2010) == "2010-01-20"
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python3 -m pytest test_fusion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fusion'`

- [ ] **Step 3: Implémenter**

```python
"""Logique pure de croisement cosmique — aucun appel réseau ici, tout est testable
en isolation. Les 12 plages de dates du zodiaque occidental sont un savoir
calendaire public, indépendant du moteur astro de `personnages` (pas de
duplication du moteur : on ne recalcule aucune position planétaire ici)."""

# (mois, jour) de DÉBUT de chaque signe. On ancre systématiquement sur le début de
# plage : Capricorne (22 déc → 19 jan) reste ainsi toujours dans l'année demandée,
# aucun cas particulier de bascule d'année à gérer.
SIGNE_PLAGES: dict[str, tuple[int, int]] = {
    "Bélier": (3, 21), "Taureau": (4, 20), "Gémeaux": (5, 21), "Cancer": (6, 21),
    "Lion": (7, 23), "Vierge": (8, 23), "Balance": (9, 23), "Scorpion": (10, 23),
    "Sagittaire": (11, 22), "Capricorne": (12, 22), "Verseau": (1, 20), "Poissons": (2, 19),
}


def date_pour_signe(signe: str, annee: int) -> str:
    """Date ISO plausible (début de plage) pour naître sous `signe`, dans `annee`.

    Ce choix d'année n'a AUCUNE signification d'hérédité (comme le lieu de
    naissance) — c'est un choix pratique pour obtenir une vraie date calculable."""
    mois, jour = SIGNE_PLAGES[signe]
    return f"{annee:04d}-{mois:02d}-{jour:02d}"
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python3 -m pytest test_fusion.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/fusion.py briques/world-engine/test_fusion.py
git commit -m "feat(world-engine): conversion signe→date (fusion.date_pour_signe)"
```

---

## Task 3: `fusion.py` — fusion de description parentale

**Files:**
- Modify: `briques/world-engine/fusion.py`
- Modify: `briques/world-engine/test_fusion.py`

**Interfaces:**
- Consumes: `theme_a`, `theme_b` = réponses complètes de `POST /holistique/portrait` de `personnages` (dict avec clés `portrait.forces` (list[str]), `theme_complet.dominantes.planete.dominante` (str), `theme_complet.dominantes.signe.dominant` (str)).
- Produces: `fusion.MOTS_MUTATION: list[str]`, `fusion.fusionner_description(theme_a: dict, theme_b: dict, mutation_rate: float, rng) -> tuple[str, bool]` — `rng` est tout objet exposant `.random() -> float` et `.choice(seq) -> Any` (typiquement `random.Random`).

- [ ] **Step 1: Écrire le test qui échoue**

```python
class _RngFactice:
    """Faux générateur aléatoire : renvoie des valeurs FIXÉES pour un test déterministe
    (plutôt que de chercher une seed qui tombe juste — plus lisible, jamais fragile)."""
    def __init__(self, valeur_random: float, choix: str = ""):
        self._valeur = valeur_random
        self._choix = choix

    def random(self) -> float:
        return self._valeur

    def choice(self, seq):
        return self._choix


def _theme_portrait_factice(forces, dominante_planete, dominante_signe) -> dict:
    return {
        "portrait": {"forces": forces},
        "theme_complet": {"dominantes": {
            "planete": {"dominante": dominante_planete},
            "signe": {"dominant": dominante_signe},
        }},
    }


def test_fusionner_description_sans_mutation():
    theme_a = _theme_portrait_factice(["Sagesse", "Stabilité", "Émotivité"], "Mercure", "Vierge")
    theme_b = _theme_portrait_factice(["Courage", "Passion", "Loyauté"], "Mars", "Bélier")
    rng = _RngFactice(valeur_random=0.99)   # > mutation_rate → pas de mutation
    description, mutation_survenue = fusion.fusionner_description(theme_a, theme_b, 0.10, rng)
    assert mutation_survenue is False
    for mot in ("Sagesse", "Stabilité", "Courage", "Passion", "Mercure", "Mars", "Vierge", "Bélier"):
        assert mot in description


def test_fusionner_description_avec_mutation_forcee():
    theme_a = _theme_portrait_factice(["Sagesse", "Stabilité", "Émotivité"], "Mercure", "Vierge")
    theme_b = _theme_portrait_factice(["Courage", "Passion", "Loyauté"], "Mars", "Bélier")
    rng = _RngFactice(valeur_random=0.01, choix=fusion.MOTS_MUTATION[0])   # < mutation_rate
    description, mutation_survenue = fusion.fusionner_description(theme_a, theme_b, 0.10, rng)
    assert mutation_survenue is True
    assert fusion.MOTS_MUTATION[0] in description
```

(ajouter ces imports/fonctions en haut de `test_fusion.py`, sous `import fusion`)

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python3 -m pytest test_fusion.py -v`
Expected: FAIL — `AttributeError: module 'fusion' has no attribute 'fusionner_description'`

- [ ] **Step 3: Implémenter**

Ajouter à la fin de `fusion.py` :

```python
# Traits « mutants » : pool local à world-engine, volontairement indépendant des
# tables de significations de `personnages` (pure flaveur narrative, pas de lien
# avec le moteur astro — donc pas d'import de code entre les deux briques).
MOTS_MUTATION = [
    "Rébellion", "Étrangeté", "Prescience", "Chaos créateur", "Magnétisme sombre",
    "Don occulte", "Instabilité géniale", "Charisme brut", "Intuition foudroyante",
    "Ombre habitée", "Force tellurique", "Éclat imprévisible",
]


def fusionner_description(theme_a: dict, theme_b: dict, mutation_rate: float, rng) -> tuple[str, bool]:
    """Fusionne les traits dominants de 2 réponses `/holistique/portrait` en une
    description texte, destinée à `/holistique/recherche-inverse`.

    Avec probabilité `mutation_rate` (tirée via `rng.random()`), injecte un trait
    absent des deux parents (`rng.choice(MOTS_MUTATION)`). Renvoie
    (description, mutation_survenue)."""
    forces_a = theme_a["portrait"]["forces"][:2]
    forces_b = theme_b["portrait"]["forces"][:2]
    dom_a = theme_a["theme_complet"]["dominantes"]
    dom_b = theme_b["theme_complet"]["dominantes"]
    traits = [*forces_a, *forces_b,
              dom_a["planete"]["dominante"], dom_b["planete"]["dominante"],
              dom_a["signe"]["dominant"], dom_b["signe"]["dominant"]]

    mutation_survenue = rng.random() < mutation_rate
    if mutation_survenue:
        traits.append(rng.choice(MOTS_MUTATION))

    return "Personnage combinant " + ", ".join(traits) + ".", mutation_survenue
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python3 -m pytest test_fusion.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/fusion.py briques/world-engine/test_fusion.py
git commit -m "feat(world-engine): fusion des traits parents en description (fusion.fusionner_description)"
```

---

## Task 4: `fusion.py` — comparaison des 10 corps (hérédité)

**Files:**
- Modify: `briques/world-engine/fusion.py`
- Modify: `briques/world-engine/test_fusion.py`

**Interfaces:**
- Consumes: `dix_corps_enfant`, `dix_corps_a`, `dix_corps_b` = valeur de `theme_complet["dix_corps"]` (dict keyed par nom de corps : `"Soleil"`, `"Lune"`, …, chaque valeur ayant au moins la clé `"signe"`).
- Produces: `fusion.CORPS: list[str]` (les 10 noms, dans l'ordre), `fusion.comparer_dix_corps(dix_corps_enfant: dict, dix_corps_a: dict, dix_corps_b: dict) -> dict` → `{"par_corps": [{"corps": str, "signe_enfant": str, "origine": "A"|"B"|"commun"|"mutation"}], "resume": {"A": int, "B": int, "commun": int, "mutation": int}}`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
def _dix_corps(signes: dict) -> dict:
    """signes = {"Soleil": "Vierge", ...} → forme minimale de theme_complet.dix_corps."""
    return {corps: {"signe": signe} for corps, signe in signes.items()}


def test_comparer_dix_corps_repartition():
    enfant = _dix_corps({
        "Soleil": "Vierge", "Lune": "Bélier", "Mercure": "Cancer",
        "Vénus": "Lion", "Mars": "Gémeaux", "Jupiter": "Balance",
        "Saturne": "Scorpion", "Uranus": "Sagittaire", "Neptune": "Capricorne",
        "Pluton": "Verseau",
    })
    parent_a = _dix_corps({c: "Vierge" for c in fusion.CORPS})       # matche Soleil seul
    parent_b = _dix_corps({c: "Bélier" for c in fusion.CORPS})       # matche Lune seul
    heredite = fusion.comparer_dix_corps(enfant, parent_a, parent_b)
    assert heredite["resume"] == {"A": 1, "B": 1, "commun": 0, "mutation": 8}
    soleil = next(c for c in heredite["par_corps"] if c["corps"] == "Soleil")
    assert soleil == {"corps": "Soleil", "signe_enfant": "Vierge", "origine": "A"}


def test_comparer_dix_corps_commun_aux_deux_parents():
    enfant = _dix_corps({c: "Poissons" for c in fusion.CORPS})
    parent_a = _dix_corps({c: "Poissons" for c in fusion.CORPS})
    parent_b = _dix_corps({c: "Poissons" for c in fusion.CORPS})
    heredite = fusion.comparer_dix_corps(enfant, parent_a, parent_b)
    assert heredite["resume"] == {"A": 0, "B": 0, "commun": 10, "mutation": 0}
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python3 -m pytest test_fusion.py -v`
Expected: FAIL — `AttributeError: module 'fusion' has no attribute 'CORPS'`

- [ ] **Step 3: Implémenter**

Ajouter à la fin de `fusion.py` :

```python
CORPS = ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
         "Saturne", "Uranus", "Neptune", "Pluton"]


def comparer_dix_corps(dix_corps_enfant: dict, dix_corps_a: dict, dix_corps_b: dict) -> dict:
    """Compare le signe de chacun des 10 corps de l'enfant à ceux des 2 parents.

    C'est un post-traitement NARRATIF : le thème de l'enfant est calculé
    indépendamment (vraie date, vraie astronomie) — une correspondance de signe
    est donc une coïncidence assumée, pas une vraie hérédité génétique."""
    par_corps = []
    resume = {"A": 0, "B": 0, "commun": 0, "mutation": 0}
    for corps in CORPS:
        signe_e = dix_corps_enfant[corps]["signe"]
        match_a = signe_e == dix_corps_a[corps]["signe"]
        match_b = signe_e == dix_corps_b[corps]["signe"]
        if match_a and match_b:
            origine = "commun"
        elif match_a:
            origine = "A"
        elif match_b:
            origine = "B"
        else:
            origine = "mutation"
        resume[origine] += 1
        par_corps.append({"corps": corps, "signe_enfant": signe_e, "origine": origine})
    return {"par_corps": par_corps, "resume": resume}
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python3 -m pytest test_fusion.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/fusion.py briques/world-engine/test_fusion.py
git commit -m "feat(world-engine): comparaison des 10 corps enfant/parents (fusion.comparer_dix_corps)"
```

---

## Task 5: `personnages_client.py` — appels HTTP vers `personnages`

**Files:**
- Create: `briques/world-engine/personnages_client.py`
- Test: `briques/world-engine/test_personnages_client.py`

**Interfaces:**
- Consumes: rien de world-engine (module autonome).
- Produces: `personnages_client.PERSONNAGES_URL: str`, `personnages_client.PersonnagesIndisponible` (Exception), `async personnages_client.portrait(fiche: dict) -> httpx.Response`, `async personnages_client.recherche_inverse(description: str) -> httpx.Response`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
"""Tests de personnages_client.py — aucun appel réseau réel (respx intercepte tout)."""
import json

import httpx
import pytest
import respx

import personnages_client as pc


@respx.mock
@pytest.mark.asyncio
async def test_portrait_appelle_la_bonne_url_avec_la_fiche():
    route = respx.post(f"{pc.PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    fiche = {"prenoms": "Aria", "date_naissance": "1990-09-05"}
    r = await pc.portrait(fiche)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert json.loads(route.calls.last.request.content) == fiche


@respx.mock
@pytest.mark.asyncio
async def test_portrait_injoignable_leve_personnages_indisponible():
    respx.post(f"{pc.PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=httpx.ConnectError("connexion refusée"))
    with pytest.raises(pc.PersonnagesIndisponible):
        await pc.portrait({"date_naissance": "1990-09-05"})


@respx.mock
@pytest.mark.asyncio
async def test_recherche_inverse_appelle_la_bonne_url():
    route = respx.post(f"{pc.PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": []}))
    r = await pc.recherche_inverse("description de test")
    assert r.status_code == 200
    assert route.called
    envoye = json.loads(route.calls.last.request.content)
    assert envoye == {"description": "description de test", "combien": 1}
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python3 -m pip install -r requirements-dev.txt pytest-asyncio && python3 -m pytest test_personnages_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'personnages_client'`

- [ ] **Step 3: Implémenter**

```python
"""Client HTTP vers la brique `personnages` — SEUL point de contact avec le moteur
astro. world-engine n'importe jamais de code de `personnages` : tout calcul de
thème passe par ces 2 appels."""
import os

import httpx

PERSONNAGES_URL = os.getenv("PERSONNAGES_URL", "http://host.docker.internal:5900")
_PERSONNAGES_CLE = os.getenv("PERSONNAGES_KEY")
_ENTETES = {"X-API-Key": _PERSONNAGES_CLE} if _PERSONNAGES_CLE else {}


class PersonnagesIndisponible(Exception):
    """La brique `personnages` n'a pas répondu (réseau/DNS/timeout) — jamais de
    donnée inventée pour compenser : l'appelant doit répondre 502."""


async def portrait(fiche: dict) -> httpx.Response:
    """POST /holistique/portrait — traditions + portrait + theme_complet réels."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            return await client.post(f"{PERSONNAGES_URL}/holistique/portrait",
                                      json=fiche, headers=_ENTETES)
        except httpx.HTTPError as e:
            raise PersonnagesIndisponible(str(e)) from e


async def recherche_inverse(description: str) -> httpx.Response:
    """POST /holistique/recherche-inverse — description → signes/nombres plausibles.

    `combien=1` : world-engine n'a besoin que du signe le mieux classé."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            return await client.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse",
                                      json={"description": description, "combien": 1},
                                      headers=_ENTETES)
        except httpx.HTTPError as e:
            raise PersonnagesIndisponible(str(e)) from e
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python3 -m pytest test_personnages_client.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/world-engine/personnages_client.py briques/world-engine/test_personnages_client.py
git commit -m "feat(world-engine): client HTTP vers personnages (portrait + recherche_inverse)"
```

---

## Task 6: `main.py` — route `POST /genome/croiser`

**Files:**
- Modify: `briques/world-engine/main.py`
- Modify: `briques/world-engine/test_api.py`

**Interfaces:**
- Consumes: `fusion.fusionner_description`, `fusion.date_pour_signe`, `fusion.comparer_dix_corps` (Tasks 2-4) ; `personnages_client.portrait`, `personnages_client.recherche_inverse`, `personnages_client.PersonnagesIndisponible` (Task 5).
- Produces: route `POST /genome/croiser` (voir Pydantic models ci-dessous), montée sur `main.app`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `test_api.py` (après les imports existants, ajouter `import respx`, `import httpx` en haut du fichier) :

```python
PERSONNAGES_URL = "http://host.docker.internal:5900"

_FICHE_A = {"prenoms": "Théo", "date_naissance": "1985-03-10", "heure_naissance": "08:00",
            "latitude": 48.85, "longitude": 2.35, "utc_offset": 1.0}
_FICHE_B = {"prenoms": "Léa", "date_naissance": "1988-07-22", "heure_naissance": "16:20",
            "latitude": 45.76, "longitude": 4.83, "utc_offset": 2.0}


def _portrait_factice(dominante_planete="Mercure", dominante_signe="Vierge",
                       signe_dix_corps="Vierge") -> dict:
    """`signe_dix_corps` est appliqué IDENTIQUEMENT aux 10 corps (fixture minimale) —
    fait varier ce paramètre entre 2 appels pour tester la comparaison d'hérédité."""
    return {
        "traditions": {"signe_solaire": {"nom": "Vierge"}},
        "portrait": {"archetype": "Le Gardien", "forces": ["Sagesse", "Stabilité", "Émotivité"],
                     "faiblesse": "Combativité"},
        "theme_complet": {
            "dominantes": {"planete": {"dominante": dominante_planete},
                            "signe": {"dominant": dominante_signe}},
            "dix_corps": {c: {"signe": signe_dix_corps} for c in
                          ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                           "Saturne", "Uranus", "Neptune", "Pluton"]},
        },
        "empreinte": [], "glossaire": [],
    }


@respx.mock
def test_genome_croiser_chemin_heureux():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),   # parent A
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),        # parent B
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])    # enfant
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "prenoms_enfant": "Nova", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    data = r.json()
    assert data["enfant"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"
    assert data["heredite"]["resume"] == {"A": 10, "B": 0, "commun": 0, "mutation": 0}
    assert data["mutation_survenue"] is False
    assert "description_genome" in data


@respx.mock
def test_genome_croiser_personnages_injoignable_502():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(side_effect=httpx.ConnectError("down"))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44})
    assert r.status_code == 502


@respx.mock
def test_genome_croiser_fiche_parent_invalide_propage_422():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(422, json={"detail": "Fiche insuffisante."}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"prenoms": "X"}, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_aucun_signe_reconnu_422():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice()))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": []}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44})
    assert r.status_code == 422
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python3 -m pytest test_api.py -v`
Expected: FAIL — `404` (route `/genome/croiser` inexistante) sur les 4 nouveaux tests.

- [ ] **Step 3: Implémenter la route dans `main.py`**

Ajouter en haut de `main.py`, avec les autres imports :

```python
from datetime import date
from random import Random

from pydantic import BaseModel

import fusion
import personnages_client
```

Ajouter avant la définition de `/sante` (ou juste après) :

```python
class FicheParent(BaseModel):
    """Même forme que FicheHolistique côté personnages — sous-ensemble minimal
    pour ce prototype (pas de systeme_numerologie/langue_sortie ici, YAGNI)."""
    prenoms: str = ""
    nom: str = ""
    date_naissance: str = ""
    heure_naissance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset: Optional[float] = None


class Croisement(BaseModel):
    parent_a: FicheParent
    parent_b: FicheParent
    prenoms_enfant: str = ""
    nom_enfant: str = ""
    latitude_enfant: float      # jamais deviné : requis
    longitude_enfant: float     # jamais deviné : requis
    utc_offset_enfant: Optional[float] = None
    annee_enfant: Optional[int] = None   # défaut : année courante, sans signification d'hérédité
    mutation_rate: float = 0.10
```

Ajouter la route :

```python
@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`) pour produire un enfant au
    thème astronomiquement réel, avec un récit d'hérédité en post-traitement
    (comparaison des 10 corps aux 2 parents — coïncidence assumée, pas une vraie
    génétique astrale)."""
    try:
        ra = await personnages_client.portrait(body.parent_a.model_dump())
        rb = await personnages_client.portrait(body.parent_b.model_dump())
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if ra.status_code != 200:
        raise HTTPException(ra.status_code, f"Parent A : {ra.json().get('detail', ra.text)}")
    if rb.status_code != 200:
        raise HTTPException(rb.status_code, f"Parent B : {rb.json().get('detail', rb.text)}")
    theme_a, theme_b = ra.json(), rb.json()

    description, mutation_survenue = fusion.fusionner_description(
        theme_a, theme_b, body.mutation_rate, Random())

    try:
        rri = await personnages_client.recherche_inverse(description)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if rri.status_code != 200:
        raise HTTPException(rri.status_code, f"Recherche inverse : {rri.json().get('detail', rri.text)}")
    signes = rri.json().get("signes") or []
    if not signes:
        raise HTTPException(422, "Impossible de dériver un signe pour l'enfant à partir "
                                  "de cette description fusionnée.")

    annee = body.annee_enfant or date.today().year
    date_enfant = fusion.date_pour_signe(signes[0]["signe"], annee)

    fiche_enfant = {
        "prenoms": body.prenoms_enfant, "nom": body.nom_enfant,
        "date_naissance": date_enfant, "heure_naissance": None,
        "latitude": body.latitude_enfant, "longitude": body.longitude_enfant,
        "utc_offset": body.utc_offset_enfant,
    }
    try:
        re_ = await personnages_client.portrait(fiche_enfant)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if re_.status_code != 200:
        raise HTTPException(re_.status_code, f"Enfant : {re_.json().get('detail', re_.text)}")
    theme_enfant = re_.json()

    heredite = fusion.comparer_dix_corps(
        theme_enfant["theme_complet"]["dix_corps"],
        theme_a["theme_complet"]["dix_corps"],
        theme_b["theme_complet"]["dix_corps"])

    return {"parentA": theme_a, "parentB": theme_b, "description_genome": description,
            "enfant": theme_enfant, "heredite": heredite, "mutation_survenue": mutation_survenue}
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python3 -m pytest test_api.py -v`
Expected: `6 passed` (2 de la Task 1 + 4 nouveaux)

- [ ] **Step 5: Lancer toute la suite de la brique**

Run: `cd briques/world-engine && python3 -m pytest . -v`
Expected: `16 passed` (6 dans test_api.py + 7 dans test_fusion.py + 3 dans test_personnages_client.py)

- [ ] **Step 6: Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_api.py
git commit -m "feat(world-engine): route POST /genome/croiser (orchestration complète)"
```

---

## Task 7: `manifest.json` + filet manifeste↔route

**Files:**
- Create: `briques/world-engine/manifest.json`
- Test: `briques/world-engine/test_manifest_capacites.py`

**Interfaces:**
- Consumes: `main.app` (Task 1).
- Produces: rien pour les tasks suivantes (dernier maillon du code applicatif).

- [ ] **Step 1: Écrire le test qui échoue**

```python
"""Filet de contrat manifeste↔route (même motif que briques/personnages) : le
manifest est ce que le Cœur lit pour piloter world-engine — une capacité qui
pointe une route inexistante casserait l'assistant en silence."""
import json
import re
from pathlib import Path

import main

_ICI = Path(__file__).parent
_MANIFEST = json.loads((_ICI / "manifest.json").read_text())


def _gabarit(chemin: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", chemin)


def test_chaque_capacite_pointe_une_route_reelle():
    reelles = set()
    for r in main.app.routes:
        for methode in getattr(r, "methods", set()) or set():
            reelles.add((methode, _gabarit(getattr(r, "path", ""))))
    manquantes = [(c["nom"], c["methode"], c["chemin"]) for c in _MANIFEST["capacites"]
                  if (c["methode"], _gabarit(c["chemin"])) not in reelles]
    assert not manquantes, f"Capacités sans route correspondante : {manquantes}"


def test_noms_de_capacites_uniques():
    noms = [c["nom"] for c in _MANIFEST["capacites"]]
    assert len(noms) == len(set(noms))
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python3 -m pytest test_manifest_capacites.py -v`
Expected: FAIL — `FileNotFoundError` (manifest.json inexistant)

- [ ] **Step 3: Créer `manifest.json`**

```json
{
  "nom": "world-engine",
  "famille": "metier",
  "version": "0.1.0",
  "description": "Prototype exploratoire : croise 2 profils cosmiques (via la brique personnages) pour produire un enfant dont le thème astral est calculé à une vraie date, avec un récit d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents — coïncidence assumée, pas une vraie génétique astrale). Premier maillon du rapport d'architecture « World Engine » : la simulation temporelle et la cartographie restent hors périmètre tant que ce croisement ne prouve pas son intérêt narratif.",
  "role": "world-engine",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/world-engine",
  "port": 6220,
  "url_sante": "http://host.docker.internal:6220/sante",
  "depends_on": ["personnages"],
  "offre": ["croisement_genome_cosmique"],
  "besoin": ["personnages"],
  "taches": [],
  "capacites": [
    {
      "nom": "genome_croiser",
      "description": "Croise 2 profils cosmiques (fiches parents avec date/heure/lieu de naissance) pour produire un enfant : thème astral calculé à une vraie date indépendante, avec un récit d'hérédité comparant les 10 corps de l'enfant aux 2 parents. Le lieu de naissance de l'enfant est indispensable (jamais deviné). Analyse, ne persiste rien.",
      "methode": "POST",
      "chemin": "/genome/croiser",
      "params": {
        "parent_a": {
          "type": "object",
          "description": "Fiche du parent A : prenoms, nom, date_naissance ('AAAA-MM-JJ', requis), heure_naissance ('HH:MM'), latitude, longitude, utc_offset.",
          "requis": true
        },
        "parent_b": {
          "type": "object",
          "description": "Fiche du parent B, même forme que parent_a.",
          "requis": true
        },
        "prenoms_enfant": {
          "type": "string",
          "description": "Prénom(s) de l'enfant à naître."
        },
        "nom_enfant": {
          "type": "string",
          "description": "Nom de famille de l'enfant."
        },
        "latitude_enfant": {
          "type": "number",
          "description": "Latitude du lieu de naissance de l'enfant. Obligatoire : jamais deviné ni moyenné entre les parents.",
          "requis": true
        },
        "longitude_enfant": {
          "type": "number",
          "description": "Longitude EST-positive du lieu de naissance de l'enfant. Obligatoire.",
          "requis": true
        },
        "utc_offset_enfant": {
          "type": "number",
          "description": "Décalage local→UTC au lieu de naissance de l'enfant (optionnel)."
        },
        "annee_enfant": {
          "type": "integer",
          "description": "Année de naissance de l'enfant (optionnel, défaut : année courante). Choix pratique sans signification d'hérédité — comme le lieu."
        },
        "mutation_rate": {
          "type": "number",
          "description": "Probabilité (0.0-1.0, défaut 0.10) d'injecter un trait absent des 2 parents dans la description fusionnée avant recherche du signe de l'enfant."
        }
      },
      "action": false
    }
  ]
}
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd briques/world-engine && python3 -m pytest test_manifest_capacites.py -v`
Expected: `2 passed`

- [ ] **Step 5: Lancer toute la suite finale**

Run: `cd briques/world-engine && python3 -m pytest . -v`
Expected: `18 passed` (16 précédents + 2 dans test_manifest_capacites.py)

- [ ] **Step 6: Valider le JSON et commit**

```bash
python3 -c "import json; json.load(open('briques/world-engine/manifest.json'))" && echo "JSON valide"
git add briques/world-engine/manifest.json briques/world-engine/test_manifest_capacites.py
git commit -m "feat(world-engine): manifest + filet manifeste↔route (capacité genome_croiser)"
```

---

## Task 8: Docker Compose + build local

**Files:**
- Create: `briques/world-engine/docker-compose.yml`

**Interfaces:** aucune (déploiement).

- [ ] **Step 1: Créer `docker-compose.yml`**

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
      # PERSONNAGES_KEY (clé d'intégration Cœur) vient du .env racine via env_file —
      # NE PAS la redéclarer en `PERSONNAGES_KEY=${PERSONNAGES_KEY:-}` (piège « env
      # shadow » : chaîne vide qui écraserait la vraie valeur).
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6220/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

- [ ] **Step 2: Build local et fumée**

Run:
```bash
cd briques/world-engine && docker compose up -d --build
sleep 3
curl -s localhost:6220/sante
```
Expected: `{"statut":"ok","brique":"world-engine"}`

- [ ] **Step 3: Arrêter le conteneur de test local**

Run: `cd briques/world-engine && docker compose down`
Expected: conteneur arrêté proprement.

- [ ] **Step 4: Commit**

```bash
git add briques/world-engine/docker-compose.yml
git commit -m "feat(world-engine): docker-compose (port 6220, dépend de personnages)"
```

---

## Task 9: Preuve d'intégration bout-en-bout (contre `personnages` réel)

**Files:** aucun fichier créé — vérification manuelle avant de considérer le prototype prouvé.

**Interfaces:** aucune.

- [ ] **Step 1: Lancer `personnages` en local (mode ouvert) si ce n'est pas déjà fait**

Run: `cd briques/personnages && docker compose up -d`
Expected: conteneur `workplace_personnages` `healthy`.

- [ ] **Step 2: Lancer `world-engine` local en pointant sur `personnages` réel**

Run: `cd briques/world-engine && docker compose up -d --build`
Expected: conteneur `workplace_world_engine` `healthy`.

- [ ] **Step 3: Appeler `/genome/croiser` avec 2 fiches réelles**

Run:
```bash
curl -s -X POST localhost:6220/genome/croiser -H "Content-Type: application/json" -d '{
  "parent_a": {"prenoms": "Théo", "date_naissance": "1985-03-10", "heure_naissance": "08:00",
               "latitude": 48.85, "longitude": 2.35, "utc_offset": 1.0},
  "parent_b": {"prenoms": "Léa", "date_naissance": "1988-07-22", "heure_naissance": "16:20",
               "latitude": 45.76, "longitude": 4.83, "utc_offset": 2.0},
  "prenoms_enfant": "Nova", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
  "mutation_rate": 0.10
}' | python3 -m json.tool
```
Expected: réponse 200 avec `parentA`, `parentB`, `description_genome`, `enfant` (thème complet réel), `heredite.resume` (4 clés A/B/commun/mutation sommant à 10), `mutation_survenue` (bool).

- [ ] **Step 4: Vérifier qu'une fiche parent invalide échoue proprement**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:6220/genome/croiser -H "Content-Type: application/json" -d '{
  "parent_a": {"prenoms": "X"}, "parent_b": {"prenoms": "Y", "date_naissance": "1988-07-22"},
  "latitude_enfant": 43.6, "longitude_enfant": 1.44}'
```
Expected: `422`

- [ ] **Step 5: Nettoyer**

Run: `cd briques/world-engine && docker compose down`

Ce Task 10 est le jalon de décision : si le récit d'hérédité produit (via `description_genome` et `heredite`) est jugé narrativement intéressant par l'utilisateur, les phases suivantes du rapport d'architecture (Spatial, Horloge, Compilateur) peuvent être brainstormées à leur tour. Sinon, le prototype reste isolé (une seule brique, zéro impact sur le reste de Workplace) et peut être retiré sans dette.
