# Profils lecteurs & adaptation par âge (Studio) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à une même série du Studio (`briques/studio`, port 6060) d'être lue et écoutée à des niveaux d'âge différents en parallèle, via des profils lecteurs nommés (« Fils », « Fille ») dont la cible peut évoluer dans le temps, sans jamais réécrire le canon narratif.

**Architecture:** Nouvelle entité « profil lecteur », persistée en JSON un fichier par profil (même motif que les séries), scopée par identité (`cle_api`/`charger`, S187 — jamais de fuite entre tenants). Une nouvelle fonction `_adapter_cible()` dans `studio.py`, calquée sur `_traduire()` existante, adapte le registre (vocabulaire/longueur/intensité, jamais l'intrigue) d'un texte à la volée, sans jamais le stocker. Elle est branchée à deux points : une nouvelle route de lecture adaptée (texte affiché) et une extension de la route de production audio existante.

**Tech Stack:** FastAPI + Pydantic (existant), persistance fichiers JSON (existant, pas de DB), Gateway LLM via `agents._gateway_answer` (existant), front HTML/JS vanilla sans framework (existant, `front.html`).

## Global Constraints

- Toute nouvelle route est scopée par `cle: str = Depends(cle_api)` et respecte le motif 404 (jamais 403) sur une ressource d'une autre identité — même règle que `charger()` (`main.py:83-93`), voir `test_isolation_personne.py`.
- Aucune nouvelle dépendance : `_adapter_cible` réutilise `agents._gateway_answer` déjà importé dans `studio.py`. Pas de nouvelle librairie dans `requirements.txt`.
- L'adaptation par cible n'est **jamais stockée** — recalculée à chaque appel, comme la traduction existante (`_traduire`).
- L'adaptation ne change **jamais l'intrigue**, seulement le registre (vocabulaire, longueur, intensité) — contrainte posée dans le prompt système de `_adapter_cible`.
- Pas de modification de `manifest.json` dans ce plan : les profils sont un outil de gestion pour le parent via l'UI, pas une capacité pilotée par l'assistant (décision de portée, cohérente avec `langue_sortie` déjà absent de la capacité `studio_audio_produire` existante).
- Style du code : identifiants et commentaires en français, cohérents avec le reste de la brique. Docstrings courtes, une ligne si possible.
- Tests : `cd briques/studio && python3 -m pytest -q` doit rester vert à 0 dépendance externe après chaque tâche (mocker toute Gateway/HTTP, jamais d'appel réseau réel dans les tests — motif déjà en place, voir `test_langue.py`, `test_images.py`).
- Régime de preuve : chaque tâche est codée, testée et commitée localement au fil de l'eau (pas de rebuild Docker/HP dans ce plan — la preuve LIVE HP est un geste séparé, groupé plus tard, cf. mémoire du projet).

---

## Repérage (fichiers touchés)

- `briques/studio/studio.py` — persistance des profils + `_adapter_cible()`.
- `briques/studio/main.py` — routes `/profils` (CRUD), route `GET /series/{serie_id}/episodes/{n}/adapte`, extension de `POST /series/{serie_id}/audio`.
- `briques/studio/front.html` — panneau « Profils lecteurs », sélecteur « Lire pour… » sur chaque chapitre, sélecteur de profil sur le générateur audio.
- Nouveaux fichiers de test : `briques/studio/test_profils.py`, `briques/studio/test_cible_lecture.py`, `briques/studio/test_episode_adapte.py`, `briques/studio/test_audio_profil.py`.
- Extension : `briques/studio/test_front.py`.

---

### Task 1: Persistance des profils lecteurs (studio.py)

**Files:**
- Modify: `briques/studio/studio.py:34-38` (section persistance, juste après la déclaration de `ATELIERS_DIR`)
- Modify: `briques/studio/studio.py:80-83` (juste après `_save`, pour rester groupé avec la persistance des séries)
- Test: `briques/studio/test_persistance_profils.py`

**Interfaces:**
- Produces: `S.PROFILS_DIR: str`, `S._profil_path(profil_id: str) -> str`, `S._load_profil(profil_id: str) -> dict` (raises `FileNotFoundError` si absent), `S._save_profil(profil: dict) -> None`.

- [ ] **Step 1: Écrire les tests (échouants)**

Créer `briques/studio/test_persistance_profils.py` :

```python
"""Tests — persistance des profils lecteurs (un fichier par profil, S231).

Motif calqué sur la persistance des séries (`_path`/`_load`/`_save`), dans un sous-dossier
dédié (`PROFILS_DIR`) pour ne jamais collisionner avec un fichier de série."""
import os

import pytest

import studio as A


def test_profils_dir_est_un_sous_dossier_de_ateliers_dir():
    assert A.PROFILS_DIR == os.path.join(A.ATELIERS_DIR, "profils")
    assert os.path.isdir(A.PROFILS_DIR)


def test_save_puis_load_roundtrip():
    profil = {"id": "abc123", "nom": "Fils", "cible": "7-9",
              "cree_par": "perso", "cree_le": "2026-08-17T00:00:00+00:00"}
    A._save_profil(profil)
    relu = A._load_profil("abc123")
    assert relu == profil


def test_load_profil_absent_leve_filenotfound():
    with pytest.raises(FileNotFoundError):
        A._load_profil("inexistant-xyz")


def test_profil_path_ne_collisionne_pas_avec_une_serie():
    # Un id de série est un uuid4 hex ; un profil du même id reste dans un sous-dossier distinct.
    assert A._profil_path("meme-id") != A._path("meme-id")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_persistance_profils.py -v`
Expected: FAIL — `AttributeError: module 'studio' has no attribute 'PROFILS_DIR'`

- [ ] **Step 3: Implémenter dans `studio.py`**

Juste après la ligne `os.makedirs(ATELIERS_DIR, exist_ok=True)` (`studio.py:38`) :

```python
# Profils lecteurs (S231) : un fichier par profil, sous-dossier dédié pour ne jamais
# collisionner avec un fichier de série (même motif de nommage : uuid4 hex).
PROFILS_DIR = os.path.join(ATELIERS_DIR, "profils")
os.makedirs(PROFILS_DIR, exist_ok=True)
```

Juste après la fonction `_save` (`studio.py:80-82`) :

```python
def _profil_path(profil_id: str) -> str:
    return os.path.join(PROFILS_DIR, f"{profil_id}.json")


def _load_profil(profil_id: str) -> dict:
    p = _profil_path(profil_id)
    if not os.path.exists(p):
        raise FileNotFoundError(profil_id)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_profil(profil: dict) -> None:
    with open(_profil_path(profil["id"]), "w", encoding="utf-8") as f:
        json.dump(profil, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_persistance_profils.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_persistance_profils.py
git commit -m "feat(studio): persistance fichier des profils lecteurs (S231 P1)"
```

---

### Task 2: Routes CRUD `/profils` (main.py)

**Files:**
- Modify: `briques/studio/main.py` (nouveaux modèles Pydantic après `DefinirLangue`, `main.py:220-222` ; nouvel helper après `charger`, `main.py:83-93` ; nouvelles routes après le bloc `/langues`, `main.py:417-431`)
- Test: `briques/studio/test_profils.py`

**Interfaces:**
- Consumes: `S.PROFILS_DIR`, `S._profil_path`, `S._load_profil`, `S._save_profil` (Task 1) ; `S.CIBLES` (existant) ; `cle_api` (existant, `main.py:44-68`).
- Produces: `_profil_de(profil_id: str, identite: str) -> dict` (raises `HTTPException(404)`), routes `GET/POST /profils`, `PATCH/DELETE /profils/{profil_id}`.

- [ ] **Step 1: Écrire les tests (échouants)**

Créer `briques/studio/test_profils.py` :

```python
"""Tests — CRUD des profils lecteurs (S231), scopés par identité comme les séries (S187)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def test_creer_profil_ok():
    r = client.post("/profils", json={"nom": "Fils", "cible": "7-9"})
    assert r.status_code == 200
    body = r.json()
    assert body["nom"] == "Fils" and body["cible"] == "7-9"
    assert body["id"] and body["cree_le"]


def test_creer_profil_cible_inconnue_400():
    r = client.post("/profils", json={"nom": "Fille", "cible": "pas-une-cible"})
    assert r.status_code == 400


def test_creer_profil_nom_vide_422():
    r = client.post("/profils", json={"nom": "   ", "cible": "0-3"})
    assert r.status_code == 422


def test_lister_profils_contient_le_profil_cree():
    r = client.post("/profils", json={"nom": "Lister-moi", "cible": "4-6"})
    pid = r.json()["id"]
    ids = [p["id"] for p in client.get("/profils").json()]
    assert pid in ids


def test_modifier_cible_profil_le_fait_vieillir():
    pid = client.post("/profils", json={"nom": "Grandit", "cible": "0-3"}).json()["id"]
    r = client.patch(f"/profils/{pid}", json={"cible": "4-6"})
    assert r.status_code == 200 and r.json()["cible"] == "4-6"


def test_modifier_cible_inconnue_400():
    pid = client.post("/profils", json={"nom": "X", "cible": "0-3"}).json()["id"]
    r = client.patch(f"/profils/{pid}", json={"cible": "pas-une-cible"})
    assert r.status_code == 400


def test_renommer_profil():
    pid = client.post("/profils", json={"nom": "AncienNom", "cible": "0-3"}).json()["id"]
    r = client.patch(f"/profils/{pid}", json={"nom": "NouveauNom"})
    assert r.status_code == 200 and r.json()["nom"] == "NouveauNom"


def test_supprimer_profil():
    pid = client.post("/profils", json={"nom": "Ephemere", "cible": "0-3"}).json()["id"]
    assert client.delete(f"/profils/{pid}").status_code == 204
    assert client.get("/profils/inexistant-après-suppression").status_code in (404, 405)
    ids = [p["id"] for p in client.get("/profils").json()]
    assert pid not in ids


def test_profil_dautrui_404_en_lecture_modification_suppression(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    pid = client.post("/profils", json={"nom": "DeClaire", "cible": "0-3"},
                       headers=_entetes("claire")).json()["id"]
    entetes_marina = _entetes("marina")
    assert client.patch(f"/profils/{pid}", json={"nom": "Vole"},
                        headers=entetes_marina).status_code == 404
    assert client.delete(f"/profils/{pid}", headers=entetes_marina).status_code == 404
    ids_marina = [p["id"] for p in client.get("/profils", headers=entetes_marina).json()]
    assert pid not in ids_marina
    ids_claire = [p["id"] for p in client.get("/profils", headers=_entetes("claire")).json()]
    assert pid in ids_claire
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_profils.py -v`
Expected: FAIL — `404 Not Found` sur `POST /profils` (route inexistante)

- [ ] **Step 3: Implémenter dans `main.py`**

Juste après la classe `DefinirLangue` (`main.py:220-222`) :

```python
class CreerProfil(BaseModel):
    nom: str
    cible: str


class MajProfil(BaseModel):
    nom:   Optional[str] = None
    cible: Optional[str] = None
```

Juste après la fonction `charger` (`main.py:83-93`) :

```python
def _profil_de(profil_id: str, identite: str) -> dict:
    """Charge un profil lecteur (404 si absent OU d'une autre identité) — même motif que
    `charger()` pour les séries (S187) : ne révèle jamais l'existence d'un profil étranger."""
    try:
        profil = S._load_profil(profil_id)
    except FileNotFoundError:
        raise HTTPException(404, "Profil introuvable")
    if profil.get("cree_par") != identite:
        raise HTTPException(404, "Profil introuvable")
    return profil
```

Nouveau bloc de routes, juste après le bloc `# ── Langue de travail ──` (après `main.py:430`) :

```python
# ── Profils lecteurs (par âge, S231) ──────────────────────────────
@app.get("/profils", tags=["profils"])
def lister_profils(cle: str = Depends(cle_api)):
    out = []
    for fn in os.listdir(S.PROFILS_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(S.PROFILS_DIR, fn), encoding="utf-8") as f:
                p = json.load(f)
        except Exception:
            continue
        if p.get("cree_par") != cle:
            continue
        out.append(p)
    out.sort(key=lambda x: x.get("cree_le") or "")
    return out


@app.post("/profils", tags=["profils"])
def creer_profil(body: CreerProfil, cle: str = Depends(cle_api)):
    if body.cible not in S.CIBLES:
        raise HTTPException(400, f"Cible inconnue : {body.cible}")
    nom = body.nom.strip()
    if not nom:
        raise HTTPException(422, "Le nom du profil ne peut pas être vide.")
    profil = {
        "id": uuid.uuid4().hex, "nom": nom, "cible": body.cible,
        "cree_par": cle, "cree_le": datetime.now(timezone.utc).isoformat(),
    }
    S._save_profil(profil)
    return profil


@app.patch("/profils/{profil_id}", tags=["profils"])
def modifier_profil(profil_id: str, body: MajProfil, cle: str = Depends(cle_api)):
    profil = _profil_de(profil_id, cle)
    if body.nom is not None:
        nom = body.nom.strip()
        if not nom:
            raise HTTPException(422, "Le nom du profil ne peut pas être vide.")
        profil["nom"] = nom
    if body.cible is not None:
        if body.cible not in S.CIBLES:
            raise HTTPException(400, f"Cible inconnue : {body.cible}")
        profil["cible"] = body.cible
    S._save_profil(profil)
    return profil


@app.delete("/profils/{profil_id}", status_code=204, tags=["profils"])
def supprimer_profil(profil_id: str, cle: str = Depends(cle_api)):
    _profil_de(profil_id, cle)  # 404 si absent ou pas à `cle` — jamais de suppression à l'aveugle
    p = S._profil_path(profil_id)
    if os.path.exists(p):
        os.remove(p)
    return None
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_profils.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lancer la suite complète (non-régression)**

Run: `cd briques/studio && python3 -m pytest -q`
Expected: PASS, aucune régression sur les tests existants (séries, auth, isolation)

- [ ] **Step 6: Commit**

```bash
git add briques/studio/main.py briques/studio/test_profils.py
git commit -m "feat(studio): routes CRUD /profils, scopées par identité (S231 P2)"
```

---

### Task 3: `_adapter_cible()` — adaptation de registre par âge (studio.py)

**Files:**
- Modify: `briques/studio/studio.py` (juste après `_traduire`, `studio.py:338-362`)
- Test: `briques/studio/test_cible_lecture.py`

**Interfaces:**
- Consumes: `S.CIBLES`, `S.CIBLE_GUIDE` (existants, `studio.py:253-275`), `S._gateway_answer` (existant, importé depuis `agents`).
- Produces: `async def _adapter_cible(texte: str, cible: str) -> tuple[str, bool]`.

- [ ] **Step 1: Écrire les tests (échouants)**

Créer `briques/studio/test_cible_lecture.py` :

```python
"""Tests — `_adapter_cible` : adaptation de REGISTRE (vocabulaire/longueur/intensité) par
tranche d'âge, à la lecture, calquée sur `_traduire` (repli honnête, jamais de blocage).
Ne teste JAMAIS un vrai appel réseau : `_gateway_answer` est monkeypatché (S51/S231)."""
import asyncio

import studio as A


def _run(coro):
    return asyncio.run(coro)


def test_texte_vide_no_op():
    out, ok = _run(A._adapter_cible("", "7-9"))
    assert out == "" and ok is True


def test_cible_inconnue_no_op():
    out, ok = _run(A._adapter_cible("Bonjour le monde.", "pas-une-cible"))
    assert out == "Bonjour le monde." and ok is True


def test_adaptation_succes(monkeypatch):
    async def fake_gw(url, model, systeme, tache):
        return "Version simplifiée pour tout-petit."
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._adapter_cible("Une histoire un peu complexe pour un tout-petit.", "0-3"))
    assert ok is True
    assert out == "Version simplifiée pour tout-petit."


def test_adaptation_reponse_vide_repli(monkeypatch):
    async def fake_gw(*a):
        return "   "
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._adapter_cible("Texte original.", "7-9"))
    assert ok is False and out == "Texte original."


def test_adaptation_longueur_incoherente_repli(monkeypatch):
    # Réponse ridiculement plus courte que l'original → garde-fou anti-troncature.
    async def fake_gw(*a):
        return "Court."
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    original = "Un texte de référence assez long pour que le ratio de longueur déclenche le garde-fou anti-troncature de l'adaptation."
    out, ok = _run(A._adapter_cible(original, "7-9"))
    assert ok is False and out == original


def test_adaptation_gateway_injoignable_repli(monkeypatch):
    async def fake_gw(*a):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._adapter_cible("Texte original.", "7-9"))
    assert ok is False and out == "Texte original."
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_cible_lecture.py -v`
Expected: FAIL — `AttributeError: module 'studio' has no attribute '_adapter_cible'`

- [ ] **Step 3: Implémenter dans `studio.py`**

Juste après `_traduire` (`studio.py:338-362`) :

```python
async def _adapter_cible(texte: str, cible: str) -> tuple:
    """Adapte le REGISTRE (vocabulaire, longueur, intensité) d'un texte à une tranche d'âge —
    JAMAIS l'intrigue. Calquée sur `_traduire` : repli HONNÊTE (texte d'origine, `ok=False`)
    si la Gateway échoue, répond vide, ou si la longueur part trop loin de l'original (garde-
    fou anti-troncature/anti-délire — pas de liste de répliques à recompter ici, juste un
    texte continu, d'où un contrôle par ratio plutôt que par nombre d'entrées)."""
    if not texte or cible not in CIBLE_GUIDE:
        return texte, True
    label = CIBLES.get(cible, cible)
    guide = CIBLE_GUIDE[cible]
    try:
        adapte = await _gateway_answer(
            GW_URL, GW_MODEL,
            "Tu adaptes un script audio à un public précis, SANS jamais changer l'histoire, "
            "les personnages, ni les événements. Tu ajustes SEULEMENT le vocabulaire, la "
            "longueur des phrases et l'intensité émotionnelle. Tu préserves EXACTEMENT les "
            "balises [SFX]/[AMBIANCE]/[MUSIQUE] et les didascalies entre parenthèses.",
            f"PUBLIC CIBLE : {label}. {guide}\n\nAdapte ce texte à ce public, en conservant "
            f"scrupuleusement la MÊME histoire :\n\n{texte}")
    except Exception:  # noqa: BLE001
        return texte, False
    adapte = (adapte or "").strip()
    if not adapte:
        return texte, False
    ratio = len(adapte) / max(1, len(texte))
    if ratio < 0.3 or ratio > 3:
        return texte, False
    return adapte, True
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_cible_lecture.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_cible_lecture.py
git commit -m "feat(studio): _adapter_cible — adaptation de registre par âge, repli honnête (S231 P3)"
```

---

### Task 4: Route de lecture adaptée `GET /series/{serie_id}/episodes/{n}/adapte`

**Files:**
- Modify: `briques/studio/main.py` (nouvelle route, après le bloc `/langues`, à la suite du bloc profils de Task 2)
- Test: `briques/studio/test_episode_adapte.py`

**Interfaces:**
- Consumes: `charger` (existant), `_profil_de` (Task 2), `S._adapter_cible` (Task 3).
- Produces: route `GET /series/{serie_id}/episodes/{n}/adapte?profil_id=X` → `{texte, adapte, cible, profil_id}`.

- [ ] **Step 1: Écrire les tests (échouants)**

Créer `briques/studio/test_episode_adapte.py` :

```python
"""Tests — route GET /series/{id}/episodes/{n}/adapte (lecture adaptée par profil, S231).

`_adapter_cible` est monkeypatché en spy : ses propres scénarios (succès/repli) sont déjà
couverts par `test_cible_lecture.py`, ici on vérifie le CÂBLAGE (résolution du profil,
isolation, 404) via la route FastAPI."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _serie_avec_episode_direct():
    """Injecte un épisode directement (contourne la co-création de bible, hors périmètre ici)."""
    import studio as S
    sid = client.post("/series", json={"titre": "Adaptable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Il était une fois un dragon.",
                          "script_brut": "Il était une fois un dragon."}]
    S._save(serie)
    return sid


def test_texte_adapte_appelle_adapter_cible_avec_la_cible_du_profil(monkeypatch):
    appels = []

    async def fake_adapter(texte, cible):
        appels.append((texte, cible))
        return "Texte adapté.", True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)

    sid = _serie_avec_episode_direct()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body == {"texte": "Texte adapté.", "adapte": True, "cible": "7-9", "profil_id": pid}
    assert appels == [("Il était une fois un dragon.", "7-9")]


def test_episode_inexistant_404(monkeypatch):
    async def fake_adapter(texte, cible):
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)
    sid = _serie_avec_episode_direct()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/episodes/99/adapte", params={"profil_id": pid})
    assert r.status_code == 404


def test_profil_inexistant_404():
    sid = _serie_avec_episode_direct()
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": "inconnu-xyz"})
    assert r.status_code == 404


def test_profil_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    pid = client.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                       headers=entetes_claire).json()["id"]
    sid = client.post("/series", json={"titre": "SérieMarina"},
                      headers=entetes_marina).json()["id"]
    import studio as S
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Texte.", "script_brut": "Texte."}]
    S._save(serie)
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid},
                   headers=entetes_marina)
    assert r.status_code == 404


def test_serie_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    sid = client.post("/series", json={"titre": "SérieClaire"},
                      headers=entetes_claire).json()["id"]
    pid = client.post("/profils", json={"nom": "DeMarina", "cible": "7-9"},
                       headers=entetes_marina).json()["id"]
    r = client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid},
                   headers=entetes_marina)
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_episode_adapte.py -v`
Expected: FAIL — `404 Not Found` sur la route (inexistante)

- [ ] **Step 3: Implémenter dans `main.py`**

Ajouter à la fin du bloc profils créé en Task 2 :

```python
@app.get("/series/{serie_id}/episodes/{n}/adapte", tags=["profils"])
async def episode_adapte(serie_id: str, n: int, profil_id: str, cle: str = Depends(cle_api)):
    """Texte d'un chapitre adapté au registre du profil (jamais stocké, recalculé à chaque
    appel — même politique que la traduction au rendu)."""
    serie = charger(serie_id, cle)
    profil = _profil_de(profil_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Épisode {n} introuvable.")
    texte = ep.get("script_balise") or ep.get("script_brut") or ""
    adapte, ok = await S._adapter_cible(texte, profil["cible"])
    return {"texte": adapte, "adapte": ok, "cible": profil["cible"], "profil_id": profil_id}
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_episode_adapte.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lancer la suite complète (non-régression)**

Run: `cd briques/studio && python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add briques/studio/main.py briques/studio/test_episode_adapte.py
git commit -m "feat(studio): route GET episodes/{n}/adapte — lecture adaptée par profil (S231 P4)"
```

---

### Task 5: Extension de `POST /series/{serie_id}/audio` avec `profil_id`

**Files:**
- Modify: `briques/studio/main.py:206-209` (`FaireEpisode`), `briques/studio/main.py:978-1039` (`produire_audio`)
- Test: `briques/studio/test_audio_profil.py`

**Interfaces:**
- Consumes: `_profil_de` (Task 2), `S._adapter_cible` (Task 3).
- Produces: `FaireEpisode.profil_id: Optional[str]`, réponse de `/audio` enrichie de `"profil_id"`.

- [ ] **Step 1: Écrire les tests (échouants)**

Créer `briques/studio/test_audio_profil.py` :

```python
"""Tests — POST /series/{id}/audio avec `profil_id` (S231 P5).

Toute la chaîne réseau (Gateway pour la découpe en répliques, service voix pour le rendu)
est mockée — motif `test_images.py`/`test_langue.py`. On vérifie que `profil_id`, quand
fourni, adapte le script AVANT la découpe en répliques, et que son absence ne régresse pas
le chemin existant."""
import main
import studio as S


class _FauxClientVoix:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        class _Rep:
            def raise_for_status(self):
                pass

            def json(self):
                return {"url": "/fichiers/audio.mp3", "duree": 42}
        return _Rep()


def _mocker_chaine_production(monkeypatch, capture_adapter=None):
    """Mocke : découpe en répliques (Gateway), pool de voix, casting, rendu voix."""
    async def fake_repliques(*a, **k):
        return '[{"perso":"NARRATEUR","texte":"Il était une fois."}]'
    monkeypatch.setattr(main.agents, "_gateway_answer", fake_repliques)

    async def fake_pool(langue="fr"):
        return ["Thomas"]
    monkeypatch.setattr(S, "_voix_pool", fake_pool)

    import composition
    async def fake_caster(*a, **k):
        return None  # force le repli interne S._caster (aucun réseau)
    monkeypatch.setattr(composition, "caster", fake_caster)

    monkeypatch.setattr(S, "httpx", type("H", (), {"AsyncClient": _FauxClientVoix}))

    if capture_adapter is not None:
        async def fake_adapter(texte, cible):
            capture_adapter.append((texte, cible))
            return "Script adapté.", True
        monkeypatch.setattr(S, "_adapter_cible", fake_adapter)


def _serie_avec_episode():
    client = main.app
    from fastapi.testclient import TestClient
    c = TestClient(client)
    sid = c.post("/series", json={"titre": "Sonorisable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Il était une fois.",
                          "script_brut": "Il était une fois."}]
    S._save(serie)
    return c, sid


def test_audio_avec_profil_id_adapte_le_script_avant_les_repliques(monkeypatch):
    appels = []
    _mocker_chaine_production(monkeypatch, capture_adapter=appels)
    c, sid = _serie_avec_episode()
    pid = c.post("/profils", json={"nom": "Fille", "cible": "0-3"}).json()["id"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid})
    assert r.status_code == 200
    assert r.json()["profil_id"] == pid
    assert appels == [("Il était une fois.", "0-3")]


def test_audio_sans_profil_id_non_regression(monkeypatch):
    appels = []
    _mocker_chaine_production(monkeypatch, capture_adapter=appels)
    c, sid = _serie_avec_episode()

    r = c.post(f"/series/{sid}/audio", json={"n": 1})
    assert r.status_code == 200
    assert r.json()["profil_id"] is None
    assert appels == []  # _adapter_cible jamais appelé sans profil_id


def test_audio_profil_id_dautrui_404(monkeypatch):
    _mocker_chaine_production(monkeypatch)
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    sid = c.post("/series", json={"titre": "SérieMarina"}, headers=entetes_marina).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Texte.", "script_brut": "Texte."}]
    S._save(serie)
    pid = c.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                 headers=entetes_claire).json()["id"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid}, headers=entetes_marina)
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_audio_profil.py -v`
Expected: FAIL — `422 Unprocessable Entity` (`profil_id` pas reconnu par `FaireEpisode`) ou `KeyError` sur `"profil_id"` absent de la réponse

- [ ] **Step 3: Implémenter dans `main.py`**

`FaireEpisode` (`main.py:206-209`) gagne un champ :

```python
class FaireEpisode(BaseModel):
    branche:       Optional[str] = None
    n:             Optional[int] = None
    langue_sortie: Optional[str] = None
    profil_id:     Optional[str] = None
```

Dans `produire_audio` (`main.py:978-987`), juste après la résolution de `script` et avant l'appel à `agents._gateway_answer` pour la découpe en répliques :

```python
    script = ep.get("script_balise") or ep.get("script_brut") or ""

    if body.profil_id:
        profil = _profil_de(body.profil_id, cle)
        script, _ = await S._adapter_cible(script, profil["cible"])

    brut = await agents._gateway_answer(
```

Et dans le dictionnaire de retour (`main.py:1036-1039`), ajouter `profil_id` :

```python
    return {"url": res.get("url"), "duree": res.get("duree"),
            "casting": casting, "casting_source": casting_source,
            "repliques": len(segments),
            "langue_sortie": vers, "traduit": traduit,
            "profil_id": body.profil_id}
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_audio_profil.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lancer la suite complète (non-régression)**

Run: `cd briques/studio && python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add briques/studio/main.py briques/studio/test_audio_profil.py
git commit -m "feat(studio): profil_id sur POST /audio — cible et langue se combinent (S231 P5)"
```

---

### Task 6: Front — panneau « Profils lecteurs »

**Files:**
- Modify: `briques/studio/front.html` (markup statique dans la colonne gauche, après le panneau « Nouvelle série », `front.html:126-136` ; état + fonctions JS)
- Modify: `briques/studio/test_front.py` (marqueurs de présence)

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /profils` (Task 2), `CIBLES` (déjà chargé en JS par `init()`).
- Produces: état global JS `PROFILS: array`, fonction `chargerProfils()` (consommée par les Tasks 7 et 8).

- [ ] **Step 1: Écrire les tests (échouants)**

Ajouter à `briques/studio/test_front.py` :

```python
def test_front_expose_le_panneau_profils_lecteurs():
    html = client.get("/").text
    assert "Profils lecteurs" in html
    assert "creerProfil" in html and "chargerProfils" in html
    assert "/profils" in html
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/studio && python3 -m pytest test_front.py -k profils_lecteurs -v`
Expected: FAIL — chaînes absentes du HTML

- [ ] **Step 3: Implémenter dans `front.html`**

Markup — juste après la fermeture du panneau « Nouvelle série » (`front.html:136`, avant la fermeture du `<div>` de colonne gauche à la ligne 137) :

```html
      <div class="panel">
        <h2>Profils lecteurs</h2>
        <p class="hint">Un profil par lecteur (ex. « Fils », « Fille »). Sa tranche d'âge peut évoluer au fil du temps : change-la ici quand il grandit — ça s'applique aussitôt aux prochaines lectures et productions audio.</p>
        <div id="liste-profils"><p class="muted">Chargement…</p></div>
        <div class="row" style="margin-top:10px">
          <input id="pr-nom" placeholder="Prénom" style="flex:2">
          <select id="pr-cible" style="flex:2"></select>
        </div>
        <button class="ghost" style="width:100%;margin-top:8px" onclick="creerProfil()">+ Ajouter un profil</button>
        <div class="err" id="pr-err"></div>
      </div>
```

JS — état global (à côté de `let CIBLES=[], LANGUES=[], serieCourante=null;`, `front.html:173`) :

```js
let CIBLES=[], LANGUES=[], PROFILS=[], serieCourante=null;
```

Dans `init()`, juste après la ligne qui remplit `$('n-cible').innerHTML` (`front.html:191-192`), ajouter le remplissage de `pr-cible` :

```js
    $('pr-cible').innerHTML = '<option value="">— tranche d\'âge —</option>' +
      CIBLES.map(c=>`<option value="${esc(c.cle)}">${esc(c.label)}</option>`).join('');
```

Et à la fin de `init()`, juste avant `chargerListe();` (`front.html:195`), ajouter :

```js
  await chargerProfils();
```

(`init` devient `async function init(){` — déjà le cas.)

Nouvelles fonctions, après `chargerListe` (`front.html:198-217`) :

```js
// ── Profils lecteurs (S231) : globaux à l'atelier, un par lecteur ─
async function chargerProfils(){
  try{ PROFILS = await api('/profils'); }catch(e){ PROFILS = []; }
  renderProfils();
}

function renderProfils(){
  $('liste-profils').innerHTML = PROFILS.length ? PROFILS.map(p => `
    <div class="card" style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
      <b>${esc(p.nom)}</b>
      <select style="flex:1;min-width:150px" onchange="changerCibleProfil('${p.id}', this.value)">
        ${CIBLES.map(c=>`<option value="${esc(c.cle)}"${p.cible===c.cle?' selected':''}>${esc(c.label)}</option>`).join('')}
      </select>
      <div>
        <button class="sm ghost" onclick="renommerProfil('${p.id}', ${JSON.stringify(p.nom)})">✎</button>
        <button class="sm ghost" onclick="supprimerProfil('${p.id}')">✕</button>
      </div>
    </div>`).join('') : '<p class="muted">Aucun profil pour l\'instant.</p>';
}

async function creerProfil(){
  const nom = $('pr-nom').value.trim();
  const cible = $('pr-cible').value;
  $('pr-err').textContent='';
  if(!nom){ $('pr-err').textContent='⚠ Donne un prénom au profil.'; return; }
  if(!cible){ $('pr-err').textContent='⚠ Choisis une tranche d\'âge.'; return; }
  try{
    await api('/profils','POST',{nom, cible});
    $('pr-nom').value='';
    await chargerProfils(); toast('Profil « '+nom+' » créé 🎈');
  }catch(e){ $('pr-err').textContent='⚠ '+e.message; }
}

async function changerCibleProfil(id, cible){
  try{ await api('/profils/'+id,'PATCH',{cible}); await chargerProfils(); toast('Âge mis à jour 🎂'); }
  catch(e){ toast('⚠ '+e.message); }
}

async function renommerProfil(id, nomActuel){
  const nom = prompt('Nouveau prénom du profil :', nomActuel||'');
  if(nom===null) return;
  if(!nom.trim()){ toast('Le prénom ne peut pas être vide.'); return; }
  try{ await api('/profils/'+id,'PATCH',{nom}); await chargerProfils(); toast('Profil renommé'); }
  catch(e){ toast('⚠ '+e.message); }
}

async function supprimerProfil(id){
  const profil = PROFILS.find(p=>p.id===id);
  const ok = await confirmer({
    titre:'Supprimer le profil',
    message:`Le profil « ${profil?profil.nom:''} » sera supprimé. Les chapitres déjà écrits ne sont pas affectés.`,
    action:'Supprimer'});
  if(!ok) return;
  try{ await api('/profils/'+id,'DELETE'); await chargerProfils(); toast('Profil supprimé'); }
  catch(e){ toast('⚠ '+e.message); }
}
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd briques/studio && python3 -m pytest test_front.py -v`
Expected: PASS, toute la suite `test_front.py` (aucune régression)

- [ ] **Step 5: Vérification manuelle dans le navigateur**

```bash
cd briques/studio && STUDIO_DIR=/tmp/studio_manuel PORT=6060 python3 -m uvicorn main:app --port 6060 --reload
```

Ouvrir `http://127.0.0.1:6060/` : créer un profil « Fils » (7-9), un profil « Fille » (0-3), vérifier qu'ils apparaissent dans le panneau, changer la tranche d'âge de « Fille » via son sélecteur et vérifier la persistance après rechargement de la page (F5).

- [ ] **Step 6: Commit**

```bash
git add briques/studio/front.html briques/studio/test_front.py
git commit -m "feat(studio): front — panneau Profils lecteurs (créer/renommer/faire vieillir/supprimer) (S231 P6)"
```

---

### Task 7: Front — sélecteur « Lire pour… » sur chaque chapitre

**Files:**
- Modify: `briques/studio/front.html` (`renderEpisode`, `front.html:474-491` ; `vueChapitres`, `front.html:459-473`)
- Modify: `briques/studio/test_front.py`

**Interfaces:**
- Consumes: `PROFILS` (Task 6), route `GET /series/{id}/episodes/{n}/adapte` (Task 4).
- Produces: fonction `lirePour(n, profilId)`, clé `localStorage` `studio_dernier_profil_lecture`.

- [ ] **Step 1: Écrire les tests (échouants)**

Ajouter à `briques/studio/test_front.py` :

```python
def test_front_expose_le_selecteur_lire_pour():
    html = client.get("/").text
    assert "Lire pour" in html
    assert "lirePour" in html
    assert "/adapte" in html and "profil_id" in html
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/studio && python3 -m pytest test_front.py -k lire_pour -v`
Expected: FAIL

- [ ] **Step 3: Implémenter dans `front.html`**

Remplacer entièrement `renderEpisode` (`front.html:474-491`) par :

```js
function renderEpisode(ep){
  const langs = LANGUES.map(l=>`<option value="${l.code}">${esc(l.label)}</option>`).join('');
  const profilsOpts = '<option value="">— texte de référence —</option>' +
    PROFILS.map(p=>`<option value="${esc(p.id)}">${esc(p.nom)}</option>`).join('');
  return `<div class="card" id="ep-${ep.n}">
    <div class="ep-head"><h3>Chapitre ${ep.n} ${ep.fin_episode?'<span class="flag">fin d\'épisode</span>':''}</h3>
      <span class="muted">${esc(ep.consigne||'')}</span></div>
    <label>Lire pour…</label>
    <select id="lire-${ep.n}" onchange="lirePour(${ep.n}, this.value)">${profilsOpts}</select>
    <div class="recit" id="recit-${ep.n}">${md(ep.script_balise||ep.script_brut||'')}</div>
    <div class="row" style="margin-top:10px;align-items:end">
      <div style="flex:2"><label>Langue de l'audio</label><select id="lang-${ep.n}">${langs}</select></div>
      <button class="sm" onclick="produireAudio(${ep.n})">🔊 Produire l'audio</button>
      <button class="sm ghost" onclick="couverture(${ep.n})">🖼️ Couverture</button>
      <button class="sm ghost" onclick="teaser(${ep.n})">🎬 Bande-annonce</button>
    </div>
    ${ep.audio_url?`<audio controls src="${esc(ep.audio_url)}"></audio>
      <div class="hint">Casting : ${esc(JSON.stringify(ep.casting||{}))} <span class="flag ${ep.casting_source==='studio'?'studio':''}">${esc(ep.casting_source||'')}</span></div>`:''}
    ${ep.cover_url?`<img src="${esc(ep.cover_url)}" style="max-width:200px;border-radius:10px;margin-top:8px;display:block">`:''}
    ${mediaVideo(ep.teaser_url)}
  </div>`;
}

const LS_PROFIL_LECTURE = 'studio_dernier_profil_lecture';

async function lirePour(n, profilId){
  const recit = $('recit-'+n);
  if(!profilId){
    const ep = (S().episodes||[]).find(e=>e.n===n);
    recit.innerHTML = md(ep ? (ep.script_balise||ep.script_brut||'') : '');
    localStorage.removeItem(LS_PROFIL_LECTURE);
    return;
  }
  localStorage.setItem(LS_PROFIL_LECTURE, profilId);
  recit.innerHTML = '<span class="muted">Adaptation…</span>';
  const ep = (S().episodes||[]).find(e=>e.n===n);
  const reference = ep ? (ep.script_balise||ep.script_brut||'') : '';
  try{
    const r = await api(`/series/${S().id}/episodes/${n}/adapte?profil_id=${encodeURIComponent(profilId)}`);
    recit.innerHTML = md(r.texte) + (r.adapte ? '' :
      '<div class="hint">⚠ adaptation indisponible, texte de référence affiché.</div>');
  }catch(e){
    recit.innerHTML = md(reference) + '<div class="hint">⚠ '+esc(e.message)+' — texte de référence affiché.</div>';
  }
}

function appliquerDernierProfilLecture(){
  const dernier = localStorage.getItem(LS_PROFIL_LECTURE);
  if(!dernier) return;
  if(!PROFILS.some(p=>p.id===dernier)){ localStorage.removeItem(LS_PROFIL_LECTURE); return; }
  document.querySelectorAll('select[id^="lire-"]').forEach(sel=>{
    sel.value = dernier;
    const n = parseInt(sel.id.split('-')[1], 10);
    lirePour(n, dernier);
  });
}
```

Dans `vueChapitres` (`front.html:459-473`), ajouter l'appel après l'affectation du `innerHTML` :

```js
async function vueChapitres(){
  const s=S();
  let dec=null; try{ dec = await api(`/series/${s.id}/episodes`); }catch(e){}
  const eps = s.episodes||[];
  $('vue-corps').innerHTML = `<div class="panel"><h2>Chapitres</h2>
    ${dec?`<p class="hint">Épisode d'écoute ≈ ${dec.cible_minutes||12} min → ~${dec.chapitres_par_episode||'?'} chapitres. ${eps.length} chapitre(s) écrit(s).</p>`:''}
    <label>Direction pour le prochain chapitre (facultatif)</label>
    <input id="ch-dir" placeholder="On suit l'antagoniste cette fois…">
    <button style="margin-top:10px" id="btn-ep" onclick="ecrireChapitre()">✍️ Écrire le chapitre ${eps.length+1}</button>
    <div class="err" id="ch-err"></div>
    <div id="ch-liste" style="margin-top:14px">
      ${eps.slice().reverse().map(ep=>renderEpisode(ep)).join('') || '<p class="muted">Aucun chapitre. Lance le premier !</p>'}
    </div>
  </div>`;
  appliquerDernierProfilLecture();
}
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd briques/studio && python3 -m pytest test_front.py -v`
Expected: PASS, toute la suite

- [ ] **Step 5: Vérification manuelle dans le navigateur**

Avec le serveur de Task 6 déjà lancé (ou relancé) : créer une série, écrire un premier chapitre (Bible express), ouvrir l'onglet Chapitres, sélectionner le profil « Fils » dans « Lire pour… » — le texte doit se recharger et refléter l'appel réseau à `/adapte` (observable dans les logs uvicorn). Recharger la page (F5) : le profil « Fils » doit rester sélectionné.

- [ ] **Step 6: Commit**

```bash
git add briques/studio/front.html briques/studio/test_front.py
git commit -m "feat(studio): front — lecture adaptée par profil sur les chapitres, dernier choix mémorisé (S231 P7)"
```

---

### Task 8: Front — sélecteur de profil sur le générateur audio

**Files:**
- Modify: `briques/studio/front.html` (`renderEpisode` — ligne de production audio, `produireAudio`)
- Modify: `briques/studio/test_front.py`

**Interfaces:**
- Consumes: `PROFILS` (Task 6), `POST /series/{id}/audio` avec `profil_id` (Task 5).

- [ ] **Step 1: Écrire les tests (échouants)**

Ajouter à `briques/studio/test_front.py` :

```python
def test_front_expose_le_selecteur_profil_sur_audio():
    html = client.get("/").text
    assert "aud-profil-" in html
    assert "profil_id" in html and "produireAudio" in html
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/studio && python3 -m pytest test_front.py -k profil_sur_audio -v`
Expected: FAIL — `aud-profil-` absent du HTML

- [ ] **Step 3: Implémenter dans `front.html`**

Dans `renderEpisode` (modifiée en Task 7), remplacer la ligne de production audio :

```js
    <div class="row" style="margin-top:10px;align-items:end">
      <div style="flex:2"><label>Langue de l'audio</label><select id="lang-${ep.n}">${langs}</select></div>
      <button class="sm" onclick="produireAudio(${ep.n})">🔊 Produire l'audio</button>
```

par :

```js
    <div class="row" style="margin-top:10px;align-items:end">
      <div style="flex:2"><label>Langue de l'audio</label><select id="lang-${ep.n}">${langs}</select></div>
      <div style="flex:2"><label>Pour qui</label><select id="aud-profil-${ep.n}">${profilsOpts}</select></div>
      <button class="sm" onclick="produireAudio(${ep.n})">🔊 Produire l'audio</button>
```

Et remplacer `produireAudio` (`front.html:498-502`) par :

```js
async function produireAudio(n){
  const sortie=$('lang-'+n).value;
  const profilId=$('aud-profil-'+n).value;
  toast('🔊 Sonorisation…');
  try{ await api(`/series/${S().id}/audio`,'POST',{n, langue_sortie:sortie, profil_id: profilId||null}); await refresh(); vue('Chapitres'); toast('Audio prêt 🔊'); }
  catch(e){ toast('⚠ '+e.message); }
}
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd briques/studio && python3 -m pytest test_front.py -v`
Expected: PASS, toute la suite

- [ ] **Step 5: Vérification manuelle dans le navigateur**

Sur la même série que Task 7 : sélectionner le profil « Fille » dans « Pour qui » (à côté de la langue de l'audio), cliquer « Produire l'audio ». Sans service voix réel branché en local, l'appel échouera proprement (toast d'erreur) — vérifier que le `profil_id` est bien envoyé en observant la requête dans les DevTools réseau du navigateur (Network → payload de `POST /audio`).

- [ ] **Step 6: Commit**

```bash
git add briques/studio/front.html briques/studio/test_front.py
git commit -m "feat(studio): front — sélecteur de profil sur la production audio (S231 P8)"
```

---

## Self-Review (fait avant remise du plan)

**Couverture du spec** — chaque section de `docs/superpowers/specs/2026-08-17-studio-profils-lecteurs-cible.md` a une tâche :
- §1 Profils lecteurs (scopés par identité) → Tasks 1, 2.
- §2 Adaptation du texte affiché → Tasks 3, 4.
- §3 Adaptation de l'audio → Tasks 3, 5.
- §4 Front (panneau, sélecteur lecture, sélecteur audio) → Tasks 6, 7, 8.
- Modèle de données (fichier par profil) → Task 1.
- Erreurs/dégradation (repli honnête, 404 isolation, aucun profil) → couvert dans Tasks 3, 4, 5 (tests dédiés) et Task 7 (front, repli sur texte de référence + purge `localStorage`).
- Hors périmètre (pas de contenu divergent, pas de cache, pas de rattachement série, pas de suggestion auto) → respecté : aucune tâche n'introduit ces mécanismes.

**Cohérence des types/signatures** — vérifié : `_adapter_cible(texte: str, cible: str) -> tuple` (Task 3) est le seul point d'appel, utilisé identiquement en Task 4 (`await S._adapter_cible(texte, profil["cible"])`) et Task 5 (`await S._adapter_cible(script, profil["cible"])`). `_profil_de(profil_id, cle)` (Task 2) est réutilisé sans changement de signature en Tasks 4 et 5. Le JSON de profil (`{id, nom, cible, cree_par, cree_le}`) est identique dans Task 1 (persistance) et Task 2 (routes).

**Aucun placeholder** — chaque step contient le code réel, pas de « TODO »/« gérer les erreurs plus tard ».

**Ordre des tâches** — respecte les dépendances : persistance (1) → CRUD (2) → fonction pure d'adaptation (3, indépendante de 1/2) → route lecture (4, dépend de 1+2+3) → route audio (5, dépend de 1+2+3) → front panneau (6, dépend de 2) → front lecture (7, dépend de 4+6) → front audio (8, dépend de 5+6).
