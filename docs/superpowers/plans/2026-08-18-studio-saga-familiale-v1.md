# Studio — V1 saga familiale (journal, lecture interactive, valeurs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter au Studio (`briques/studio`) trois briques V1 : un journal d'écoute/choix
par profil visible par le parent, un écran de lecture interactive de l'arbre des choix
pour l'enfant (limité au contenu déjà écrit), et une valeur humaine suggérée par le
Script Doctor sur chaque chapitre.

**Architecture:** Persistance JSON par fichier (motif existant `_load_profil`/
`_save_profil`) : un fichier journal par profil (`{profil_id}-journal.json`), une valeur
sur chaque épisode existant, un petit fichier de réglages par compte pour le nom de
famille cosmétique. Nouveaux endpoints FastAPI dans `main.py` scopés `cree_par` (motif
S187 déjà en place). Nouvelle page front `lecture.html` (mode enfant, séparée de
`front.html`).

**Tech Stack:** Python 3 / FastAPI (déjà en place), persistance fichier JSON (pas de DB),
pytest (tests offline, pas de dépendance réseau — tout LLM est monkeypatché), JS vanilla
côté front (aucune dépendance ajoutée).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-08-18-studio-saga-familiale-v1-design.md`.
- ADR de référence : `docs/decisions/2026-08-18-studio-famille-compte-unique-portabilite-profil.md`
  — toute donnée propre à un enfant est indexée par `profil_id`, jamais fusionnée dans le
  JSON de la série.
- Aucune génération de contenu à la volée pendant que l'enfant écoute : une branche non
  écrite renvoie 404, jamais un appel LLM en direct.
- Tous les tests sont OFFLINE : tout appel LLM (`agents._gateway_answer`, `agents.demander`,
  `studio._adapter_cible`, `studio._demander`) est monkeypatché, jamais réellement invoqué.
- Suivre l'auth existante (`Depends(cle_api)`, `charger()`, `_profil_de()`) — ne jamais
  introduire un nouveau mécanisme d'isolation.
- Chaque route en écriture (POST/PATCH/DELETE) ajoutée au manifest doit être `action: true`
  (contrat vérifié par `test_manifest_capacites.py`).
- Commandes de test à exécuter depuis `briques/studio/` : `python3 -m pytest <fichier> -v`.

---

## Task 1: Journal — persistance par profil (studio.py)

**Files:**
- Modify: `briques/studio/studio.py` (ajout après la section profils lecteurs, ~ligne 105)
- Test: `briques/studio/test_journal_profil.py`

**Interfaces:**
- Produces: `_journal_path(profil_id: str) -> str`, `_load_journal(profil_id: str) -> list`,
  `_ajouter_evenement(profil_id: str, evenement: dict) -> dict` (complète `id`/`quand` si
  absents, append-only, persiste dans `PROFILS_DIR/{profil_id}-journal.json`).

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_journal_profil.py
"""Tests — journal d'écoute/choix par profil (V1 saga familiale).

Motif calqué sur la persistance des profils (`_load_profil`/`_save_profil`) : un fichier
par profil, préfixé par le même id pour rester portable (ADR 2026-08-18)."""
import os

import studio as A


def test_journal_path_prefixe_par_profil_id():
    assert A._journal_path("abc123") == os.path.join(A.PROFILS_DIR, "abc123-journal.json")


def test_load_journal_absent_renvoie_liste_vide():
    assert A._load_journal("inexistant-xyz") == []


def test_ajouter_evenement_persiste_et_complete_id_quand():
    ev = A._ajouter_evenement("p1", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    assert ev["id"]
    assert ev["quand"]
    assert A._load_journal("p1") == [ev]


def test_ajouter_evenement_deux_fois_conserve_lordre():
    A._ajouter_evenement("p2", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    A._ajouter_evenement("p2", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 2})
    evenements = A._load_journal("p2")
    assert [e["episode_n"] for e in evenements] == [1, 2]


def test_journal_isole_entre_deux_profils():
    A._ajouter_evenement("p3", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    assert A._load_journal("p4") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_journal_profil.py -v`
Expected: FAIL avec `AttributeError: module 'studio' has no attribute '_journal_path'`

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/studio.py`, juste après `_save_profil` (après la ligne 104) :

```python
# ── Journal d'écoute/choix par profil (V1 saga familiale) ────────
# Un fichier par profil, préfixé par le même id que le profil (portabilité, cf. ADR
# 2026-08-18) : append-only, gardé séparé de PROFILS_DIR/{profil_id}.json pour ne pas
# mélanger l'identité/config du profil (rarement modifiée) et son activité (modifiée à
# chaque écoute).

def _journal_path(profil_id: str) -> str:
    return os.path.join(PROFILS_DIR, f"{profil_id}-journal.json")


def _load_journal(profil_id: str) -> list:
    p = _journal_path(profil_id)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("evenements", [])


def _ajouter_evenement(profil_id: str, evenement: dict) -> dict:
    """Ajoute un événement au journal d'un profil (append-only). Complète `id`/`quand`
    si absents ; ne les écrase jamais s'ils sont déjà fournis."""
    complet = dict(evenement)
    complet.setdefault("id", uuid.uuid4().hex)
    complet.setdefault("quand", datetime.now(timezone.utc).isoformat())
    evenements = _load_journal(profil_id)
    evenements.append(complet)
    with open(_journal_path(profil_id), "w", encoding="utf-8") as f:
        json.dump({"profil_id": profil_id, "evenements": evenements}, f,
                   ensure_ascii=False, indent=2)
    return complet
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_journal_profil.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_journal_profil.py
git commit -m "feat(studio): persistance du journal d'écoute/choix par profil"
```

---

## Task 2: Journal — endpoint de lecture (main.py)

**Files:**
- Modify: `briques/studio/main.py` (nouvelle section après les routes `/profils`, ~ligne 513)
- Test: `briques/studio/test_journal_endpoint.py`

**Interfaces:**
- Consumes: `S._load_journal(profil_id: str) -> list` (Task 1), `_profil_de(profil_id, cle) -> dict` (existant, main.py:96).
- Produces: route `GET /profils/{profil_id}/journal` → `{"evenements": [...]}`.

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_journal_endpoint.py
"""Tests — route GET /profils/{id}/journal (lecture du journal d'un profil)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_journal_vide_par_defaut():
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/profils/{pid}/journal")
    assert r.status_code == 200
    assert r.json() == {"evenements": []}


def test_profil_inexistant_404():
    r = client.get("/profils/inconnu-xyz/journal")
    assert r.status_code == 404


def test_profil_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    pid = client.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                       headers=entetes_claire).json()["id"]
    r = client.get(f"/profils/{pid}/journal", headers=entetes_marina)
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_journal_endpoint.py -v`
Expected: FAIL avec `404` inattendu sur la 1re requête (`Not Found` — la route n'existe pas)

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/main.py`, juste après `episode_adapte` (après la ligne 526) :

```python
# ── Journal d'écoute/choix (V1 saga familiale) ────────────────────
@app.get("/profils/{profil_id}/journal", tags=["journal"])
def journal_profil(profil_id: str, cle: str = Depends(cle_api)):
    _profil_de(profil_id, cle)  # 404 si absent ou pas à `cle` (même garde que /profils)
    return {"evenements": S._load_journal(profil_id)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_journal_endpoint.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_journal_endpoint.py
git commit -m "feat(studio): route de lecture du journal d'un profil"
```

---

## Task 3: Marquer un chapitre comme écouté

**Files:**
- Modify: `briques/studio/main.py` (nouvelle route + modèle, section journal)
- Test: `briques/studio/test_marquer_lu.py`

**Interfaces:**
- Consumes: `S._ajouter_evenement(profil_id, evenement) -> dict` (Task 1).
- Produces: route `POST /series/{serie_id}/episodes/{n}/marquer-lu` body `{"profil_id": str}`
  → l'événement créé. **Pas d'effet de bord sur `GET .../adapte`** (spec 2.2 : la
  prévisualisation parent ne doit jamais journaliser).

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_marquer_lu.py
"""Tests — route POST /series/{id}/episodes/{n}/marquer-lu (journal, chapitre écouté).

Vérifie aussi que la prévisualisation parent existante (GET .../adapte) ne journalise
JAMAIS — c'est le défaut de conception corrigé pendant l'auto-revue de la spec (2.2)."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_episode():
    sid = client.post("/series", json={"titre": "Adaptable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_brut": "Il était une fois un dragon."}]
    S._save(serie)
    return sid


def test_marquer_lu_journalise_un_evenement():
    sid = _serie_avec_episode()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/episodes/1/marquer-lu", json={"profil_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "chapitre_lu"
    assert body["serie_id"] == sid
    assert body["episode_n"] == 1
    assert S._load_journal(pid) == [body]


def test_episode_inexistant_404():
    sid = _serie_avec_episode()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/episodes/99/marquer-lu", json={"profil_id": pid})
    assert r.status_code == 404


def test_profil_inexistant_404():
    sid = _serie_avec_episode()
    r = client.post(f"/series/{sid}/episodes/1/marquer-lu", json={"profil_id": "inconnu-xyz"})
    assert r.status_code == 404


def test_preview_get_adapte_ne_journalise_rien(monkeypatch):
    async def fake_adapter(texte, cible, langue="fr"):
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)
    sid = _serie_avec_episode()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    client.get(f"/series/{sid}/episodes/1/adapte", params={"profil_id": pid})
    assert S._load_journal(pid) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_marquer_lu.py -v`
Expected: FAIL (`404 Not Found` sur la route absente)

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/main.py`, à la suite de `journal_profil` (Task 2) :

```python
class MarquerLu(BaseModel):
    profil_id: str


@app.post("/series/{serie_id}/episodes/{n}/marquer-lu", tags=["journal"])
def marquer_lu(serie_id: str, n: int, body: MarquerLu, cle: str = Depends(cle_api)):
    """Journalise qu'un profil a écouté/lu ce chapitre. Endpoint DÉDIÉ (pas d'effet de
    bord sur `episode_adapte`, qui sert aussi à la prévisualisation du parent — cf.
    spec 2.2, auto-revue)."""
    serie = charger(serie_id, cle)
    _profil_de(body.profil_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Chapitre {n} introuvable.")
    return S._ajouter_evenement(body.profil_id, {
        "type": "chapitre_lu", "serie_id": serie_id, "serie_titre": serie.get("titre"),
        "episode_n": n, "noeud_id": None, "choix": None,
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_marquer_lu.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_marquer_lu.py
git commit -m "feat(studio): marquer un chapitre comme écouté (journal)"
```

---

## Task 4: Valeurs — liste fixe + suggestion par le Script Doctor (studio.py)

**Files:**
- Modify: `briques/studio/studio.py` (nouvelle section, après `_adapter_cible`, ~ligne 440)
- Test: `briques/studio/test_valeurs.py`

**Interfaces:**
- Produces: `VALEURS: dict[str, str]` (16 entrées), `async def _suggerer_valeur(texte: str) -> Optional[str]`
  (jamais bloquant : `None` si le LLM échoue, répond hors-liste, ou si `texte` est vide).

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_valeurs.py
"""Tests — valeur suggérée par le Script Doctor sur un chapitre (V1 saga familiale).

Calqué sur `test_cible_lecture.py` : `_demander` est monkeypatché, jamais de vrai appel
réseau. Repli honnête (`None`) sur tout échec — ne doit jamais bloquer la création d'un
chapitre."""
import asyncio

import studio as A


def _run(coro):
    return asyncio.run(coro)


def test_valeurs_est_une_liste_fixe_de_16():
    assert len(A.VALEURS) == 16
    assert "courage" in A.VALEURS
    assert "empathie" in A.VALEURS


def test_suggerer_valeur_retourne_une_cle_valide(monkeypatch):
    async def fake_demander(ag, tache):
        return '{"valeur":"courage"}'
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("Un texte quelconque.")) == "courage"


def test_suggerer_valeur_repli_none_si_cle_hors_liste(monkeypatch):
    async def fake_demander(ag, tache):
        return '{"valeur":"inexistante"}'
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("Un texte.")) is None


def test_suggerer_valeur_repli_none_si_llm_echoue(monkeypatch):
    async def fake_demander(ag, tache):
        raise RuntimeError("gateway indisponible")
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("Un texte.")) is None


def test_suggerer_valeur_texte_vide_ne_sollicite_pas_le_llm(monkeypatch):
    appels = []

    async def fake_demander(ag, tache):
        appels.append(tache)
        return '{"valeur":"courage"}'
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("")) is None
    assert appels == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_valeurs.py -v`
Expected: FAIL avec `AttributeError: module 'studio' has no attribute 'VALEURS'`

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/studio.py`, juste après `_adapter_cible` (après la ligne 439) :

```python
# ── Valeurs humaines illustrées par un chapitre (V1 saga familiale) ──
# Liste fixe, choisie par le parent OU suggérée par le Script Doctor. Jamais d'analyse
# comportementale de l'enfant ici — uniquement « quelle valeur ce CHAPITRE illustre-t-il ».
VALEURS = {
    "courage": "Courage", "honnetete": "Honnêteté", "respect": "Respect",
    "empathie": "Empathie", "entraide": "Entraide", "patience": "Patience",
    "perseverance": "Persévérance", "generosite": "Générosité",
    "tolerance": "Tolérance", "curiosite": "Curiosité",
    "responsabilite": "Responsabilité", "confiance": "Confiance",
    "solidarite": "Solidarité", "justice": "Justice", "liberte": "Liberté",
    "gratitude": "Gratitude",
}


async def _suggerer_valeur(texte: str) -> Optional[str]:
    """Suggère UNE valeur humaine illustrée par ce chapitre (Script Doctor) — jamais
    bloquant (même politique que `_traduire`/`_adapter_cible`) : `None` si le LLM échoue,
    répond hors-liste, ou si `texte` est vide. N'écrit rien : l'appelant décide."""
    if not texte:
        return None
    cles = ", ".join(VALEURS.keys())
    try:
        doctor = agent("Script Doctor")
        brut = await _demander(
            doctor,
            "Quelle valeur humaine ce chapitre illustre-t-il le mieux (pas forcément "
            "explicitement — une situation qui la met en jeu suffit) ? Choisis EXACTEMENT "
            f"une clé parmi : {cles}. Réponds UNIQUEMENT en JSON : {{\"valeur\":\"...\"}}.\n\n"
            + texte[:3000])
    except Exception:  # noqa: BLE001
        return None
    data = _extraire_obj(brut) or {}
    valeur = data.get("valeur")
    return valeur if valeur in VALEURS else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_valeurs.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/test_valeurs.py
git commit -m "feat(studio): valeurs humaines fixes + suggestion par le Script Doctor"
```

---

## Task 5: Valeurs — brancher la suggestion sur les 3 points de création d'un chapitre

**Files:**
- Modify: `briques/studio/main.py` (`faire_episode` ~ligne 989, `episode_express` ~ligne 1180, `jouer_noeud` ~ligne 1249)
- Test: `briques/studio/test_valeur_suggeree_episode.py`

**Interfaces:**
- Consumes: `S.VALEURS`, `S._suggerer_valeur(texte) -> Optional[str]` (Task 4).
- Produces: routes existantes enrichies — chaque épisode nouvellement créé porte
  désormais `valeur_suggeree` et `valeur` ; nouvelle route `GET /valeurs` →
  `[{"cle": str, "label": str}, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_valeur_suggeree_episode.py
"""Tests — valeur suggérée sur les 3 chemins de création d'un chapitre (production
normale, express, matérialisation d'un nœud d'arbre). Toute la chaîne d'agents passe par
`agents._gateway_answer` — motif `test_audio_profil.py` : on mocke ce point unique plutôt
que chaque agent."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _mock_agents(monkeypatch, valeur='{"valeur":"courage"}'):
    async def fake_gw(url, model, systeme, tache):
        if "valeur humaine" in tache:
            return valeur
        return "Script généré."
    monkeypatch.setattr(main.agents, "_gateway_answer", fake_gw)


def test_faire_episode_suggere_une_valeur(monkeypatch):
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/episode", json={})
    assert r.status_code == 200
    assert r.json()["valeur_suggeree"] == "courage"
    assert r.json()["valeur"] == "courage"


def test_faire_episode_valeur_hors_liste_devient_none(monkeypatch):
    _mock_agents(monkeypatch, valeur='{"valeur":"inexistante"}')
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/episode", json={})
    assert r.json()["valeur_suggeree"] is None
    assert r.json()["valeur"] is None


def test_episode_express_suggere_une_valeur(monkeypatch):
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/express", json={})
    assert r.status_code == 200
    assert r.json()["episode"]["valeur_suggeree"] == "courage"


def test_jouer_noeud_suggere_une_valeur(monkeypatch):
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["arbre"] = {"id": "n1", "niveau": 1, "synopsis": "S", "choix": ["A", "B"], "enfants": []}
    S._save(serie)
    client.post(f"/series/{sid}/arbre/n1/jouer", json={})
    ep = S._load(sid)["episodes"][0]
    assert ep["valeur_suggeree"] == "courage"


def test_jouer_noeud_idempotent_ne_re_suggere_pas(monkeypatch):
    """Rejouer un nœud déjà matérialisé ne doit ni relancer d'appel LLM de suggestion, ni
    écraser une valeur déjà retenue par le parent."""
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["arbre"] = {"id": "n1", "niveau": 1, "synopsis": "S", "choix": ["A", "B"], "enfants": []}
    S._save(serie)
    client.post(f"/series/{sid}/arbre/n1/jouer", json={})

    serie = S._load(sid)
    serie["episodes"][0]["valeur"] = "empathie"  # le parent a changé la valeur retenue
    S._save(serie)

    client.post(f"/series/{sid}/arbre/n1/jouer", json={})  # relecture (déjà écrit)
    assert S._load(sid)["episodes"][0]["valeur"] == "empathie"


def test_get_valeurs_liste_les_16_cles():
    r = client.get("/valeurs")
    assert r.status_code == 200
    assert len(r.json()) == 16
    assert {"cle": "courage", "label": "Courage"} in r.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_valeur_suggeree_episode.py -v`
Expected: FAIL (`KeyError: 'valeur_suggeree'` sur la 1re assertion, `404` sur `/valeurs`)

- [ ] **Step 3: Write minimal implementation**

Dans `briques/studio/main.py`, modifier `faire_episode` (juste avant
`serie["episodes"].append(episode)`, ligne ~1020) :

```python
    episode = {
        "n": numero,
        "tome_id": serie.get("tome_actif"),
        "consigne": consigne,
        "script_brut": script,
        "script_balise": balise,
        "fin_episode": finale,
        "anglicismes": S._anglicismes(balise, serie),
        "le": datetime.now(timezone.utc).isoformat(),
    }
    episode["valeur_suggeree"] = await S._suggerer_valeur(script)
    episode["valeur"] = episode["valeur_suggeree"]
    serie["episodes"].append(episode)
```

Modifier `episode_express` de la même façon (juste avant
`serie["episodes"].append(episode)`, ligne ~1213) :

```python
    episode = {
        "n": numero, "tome_id": serie.get("tome_actif"), "consigne": consigne,
        "script_brut": script, "script_balise": balise, "express": True,
        "fin_episode": finale,
        "anglicismes": S._anglicismes(balise, serie),
        "le": datetime.now(timezone.utc).isoformat(),
    }
    episode["valeur_suggeree"] = await S._suggerer_valeur(script)
    episode["valeur"] = episode["valeur_suggeree"]
    serie["episodes"].append(episode)
```

Modifier `jouer_noeud` (remplacer les 2 dernières lignes avant le `return`, ligne
~1277-1278) :

```python
    episode_n = S._materialiser_chapitre(serie, noeud, chemin)
    ep = next(e for e in serie["episodes"] if e["n"] == episode_n)
    if "valeur_suggeree" not in ep:
        ep["valeur_suggeree"] = await S._suggerer_valeur(ep.get("script_brut", ""))
        ep["valeur"] = ep["valeur_suggeree"]
    S._save(serie)
```

Ajouter la route `GET /valeurs`, juste après `lister_cibles` (main.py:425-427) :

```python
@app.get("/valeurs", tags=["réglages"])
def lister_valeurs(_cle: str = Depends(cle_api)):
    return [{"cle": k, "label": v} for k, v in S.VALEURS.items()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_valeur_suggeree_episode.py -v`
Expected: PASS (6 tests)

Puis vérifier l'absence de régression sur les tests existants qui touchent ces 3 routes :

Run: `cd briques/studio && python3 -m pytest test_episodes.py test_continuite.py -v`
Expected: PASS (aucune régression)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_valeur_suggeree_episode.py
git commit -m "feat(studio): valeur suggérée sur chaque nouveau chapitre + GET /valeurs"
```

---

## Task 6: Valeurs — le parent retient ou change la valeur

**Files:**
- Modify: `briques/studio/main.py` (nouvelle route + modèle, section valeurs)
- Test: `briques/studio/test_valeur_endpoint.py`

**Interfaces:**
- Consumes: `S.VALEURS` (Task 4), champ `episode["valeur"]` (Task 5).
- Produces: route `PATCH /series/{serie_id}/episodes/{n}/valeur` body
  `{"valeur": Optional[str]}` → `{"valeur": ..., "valeur_suggeree": ...}`.

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_valeur_endpoint.py
"""Tests — route PATCH /series/{id}/episodes/{n}/valeur (le parent retient/change la
valeur d'un chapitre)."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_episode():
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_brut": "Texte.", "valeur_suggeree": "courage",
                          "valeur": "courage"}]
    S._save(serie)
    return sid


def test_parent_change_la_valeur():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/1/valeur", json={"valeur": "empathie"})
    assert r.status_code == 200
    assert r.json() == {"valeur": "empathie", "valeur_suggeree": "courage"}
    assert S._load(sid)["episodes"][0]["valeur"] == "empathie"


def test_parent_retire_la_valeur():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/1/valeur", json={"valeur": None})
    assert r.status_code == 200
    assert r.json()["valeur"] is None


def test_valeur_inconnue_400():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/1/valeur", json={"valeur": "pas-une-valeur"})
    assert r.status_code == 400


def test_chapitre_inexistant_404():
    sid = _serie_avec_episode()
    r = client.patch(f"/series/{sid}/episodes/99/valeur", json={"valeur": "courage"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_valeur_endpoint.py -v`
Expected: FAIL (`404 Not Found` — route absente)

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/main.py`, juste après la route `GET /valeurs` (Task 5) :

```python
class MajValeur(BaseModel):
    valeur: Optional[str] = None


@app.patch("/series/{serie_id}/episodes/{n}/valeur", tags=["réglages"])
def modifier_valeur_episode(serie_id: str, n: int, body: MajValeur, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Chapitre {n} introuvable.")
    if body.valeur is not None and body.valeur not in S.VALEURS:
        raise HTTPException(400, f"Valeur inconnue : {body.valeur}")
    ep["valeur"] = body.valeur
    S._save(serie)
    return {"valeur": ep["valeur"], "valeur_suggeree": ep.get("valeur_suggeree")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_valeur_endpoint.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_valeur_endpoint.py
git commit -m "feat(studio): le parent retient ou change la valeur d'un chapitre"
```

---

## Task 7: Nom de famille cosmétique (compte)

**Files:**
- Modify: `briques/studio/studio.py` (nouvelle section, après le bloc profils lecteurs)
- Modify: `briques/studio/main.py` (nouvelles routes)
- Test: `briques/studio/test_compte_famille.py`

**Interfaces:**
- Produces: `_compte_path(identite: str) -> str`, `_load_compte(identite: str) -> dict`,
  `_save_compte(identite: str, compte: dict) -> None` (studio.py) ; routes
  `GET /famille` → `{"nom_famille": Optional[str]}`, `PATCH /famille` body
  `{"nom_famille": Optional[str]}` → même forme (main.py).
- N'est **pas** l'entité `Famille` écartée par l'ADR : aucune donnée d'enfant dans ce
  fichier, uniquement une étiquette d'affichage au niveau du compte.

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_compte_famille.py
"""Tests — nom de famille cosmétique par compte (V1 saga familiale).

Ce n'est PAS l'entité `Famille` écartée par l'ADR 2026-08-18 (aucune donnée d'enfant
ici) — juste une étiquette d'affichage, scopée comme le reste par `cree_par`/`cle_api`."""
import os

import studio as A


def test_compte_path_hache_lidentite():
    p1 = A._compte_path("cle-secrete-abc")
    p2 = A._compte_path("cle-secrete-abc")
    assert p1 == p2
    assert "cle-secrete-abc" not in p1
    assert os.path.dirname(p1) == A.COMPTES_DIR


def test_load_compte_absent_renvoie_nom_famille_none():
    assert A._load_compte("compte-inexistant") == {"nom_famille": None}


def test_save_puis_load_roundtrip():
    A._save_compte("cle-x", {"nom_famille": "Famille Martin"})
    assert A._load_compte("cle-x") == {"nom_famille": "Famille Martin"}
```

```python
# (suite du même fichier) — endpoints
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_get_famille_par_defaut():
    r = client.get("/famille", headers={"X-API-Key": "test-famille-defaut"})
    assert r.status_code == 200
    assert r.json() == {"nom_famille": None}


def test_patch_puis_get_roundtrip():
    entetes = {"X-API-Key": "test-famille-roundtrip"}
    r = client.patch("/famille", json={"nom_famille": "Famille Martin"}, headers=entetes)
    assert r.status_code == 200
    assert r.json() == {"nom_famille": "Famille Martin"}
    assert client.get("/famille", headers=entetes).json() == {"nom_famille": "Famille Martin"}


def test_famille_isolee_par_identite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire-famille"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina-famille"}
    client.patch("/famille", json={"nom_famille": "Famille Claire"}, headers=entetes_claire)
    assert client.get("/famille", headers=entetes_marina).json() == {"nom_famille": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_compte_famille.py -v`
Expected: FAIL avec `AttributeError: module 'studio' has no attribute '_compte_path'`

- [ ] **Step 3: Write minimal implementation**

Dans `briques/studio/studio.py`, ajouter `import hashlib` en tête (à côté des autres
imports stdlib, ligne 14-17) puis, après le bloc journal (Task 1) :

```python
# ── Nom de famille cosmétique (V1 saga familiale) ─────────────────
# PAS l'entité `Famille` écartée par l'ADR 2026-08-18 : aucune donnée d'enfant ici,
# uniquement une étiquette d'affichage au niveau du compte (`cree_par`).
COMPTES_DIR = os.path.join(ATELIERS_DIR, "comptes")
os.makedirs(COMPTES_DIR, exist_ok=True)


def _compte_path(identite: str) -> str:
    """Fichier haché : `identite` peut être une clé API, jamais exposée en clair dans un
    nom de fichier listable."""
    h = hashlib.sha256(identite.encode("utf-8")).hexdigest()[:16]
    return os.path.join(COMPTES_DIR, f"{h}.json")


def _load_compte(identite: str) -> dict:
    p = _compte_path(identite)
    if not os.path.exists(p):
        return {"nom_famille": None}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_compte(identite: str, compte: dict) -> None:
    with open(_compte_path(identite), "w", encoding="utf-8") as f:
        json.dump(compte, f, ensure_ascii=False, indent=2)
```

Dans `briques/studio/main.py`, ajouter les routes après `PATCH /series/{serie_id}/episodes/{n}/valeur`
(Task 6) :

```python
class MajFamille(BaseModel):
    nom_famille: Optional[str] = None


@app.get("/famille", tags=["famille"])
def lire_famille(cle: str = Depends(cle_api)):
    return S._load_compte(cle)


@app.patch("/famille", tags=["famille"])
def modifier_famille(body: MajFamille, cle: str = Depends(cle_api)):
    nom = body.nom_famille.strip() if body.nom_famille else None
    S._save_compte(cle, {"nom_famille": nom or None})
    return S._load_compte(cle)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_compte_famille.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/studio.py briques/studio/main.py briques/studio/test_compte_famille.py
git commit -m "feat(studio): nom de famille cosmétique par compte"
```

---

## Task 8: Arbre — lecture d'un nœud pour un profil (mode enfant, lecture seule)

**Files:**
- Modify: `briques/studio/main.py` (nouvelle route, section arbre)
- Test: `briques/studio/test_arbre_lire.py`

**Interfaces:**
- Consumes: `S._trouver_noeud(arbre, noeud_id) -> tuple` (existant, studio.py:812),
  `S._adapter_cible(texte, cible, langue) -> tuple` (existant), `_profil_de` (existant).
- Produces: route `GET /series/{serie_id}/arbre/{noeud_id}/lire?profil_id=` →
  `{"noeud_id", "synopsis", "texte", "adapte", "audio_url", "choix": [{"texte","ecrit"}], "episode_n"}`.
  404 si le nœud n'existe pas ou n'est pas encore écrit (`noeud["script"]` absent).

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_arbre_lire.py
"""Tests — route GET /series/{id}/arbre/{noeud_id}/lire (mode enfant, lecture seule).

`_adapter_cible` est monkeypatché en spy (motif `test_episode_adapte.py`)."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_arbre():
    sid = client.post("/series", json={"titre": "Aventure"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [
        {"n": 1, "script_brut": "Le début de l'aventure.", "audios": {}},
        {"n": 2, "script_brut": "Dans la grotte.", "audios": {}},
    ]
    serie["arbre"] = {
        "id": "n1", "niveau": 1, "synopsis": "Ouverture", "choix": ["Grotte", "Village"],
        "episode_n": 1, "script": "Le début de l'aventure.",
        "enfants": [
            {"choix": "Grotte", "noeud": {"id": "n2", "niveau": 2, "synopsis": "Grotte",
                                          "choix": [], "enfants": [], "episode_n": 2,
                                          "script": "Dans la grotte."}},
            {"choix": "Village", "noeud": {"id": "n3", "niveau": 2, "synopsis": "Village",
                                           "choix": [], "enfants": []}},  # pas encore écrit
        ],
    }
    S._save(serie)
    return sid


def _mock_adapter(monkeypatch):
    async def fake_adapter(texte, cible, langue="fr"):
        return texte, True
    monkeypatch.setattr(main.S, "_adapter_cible", fake_adapter)


def test_lire_noeud_indique_quelles_branches_sont_ecrites(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n1/lire", params={"profil_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["texte"] == "Le début de l'aventure."
    assert body["episode_n"] == 1
    choix = {c["texte"]: c["ecrit"] for c in body["choix"]}
    assert choix == {"Grotte": True, "Village": False}


def test_lire_noeud_non_ecrit_404(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n3/lire", params={"profil_id": pid})
    assert r.status_code == 404


def test_lire_noeud_inexistant_404(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n-fantome/lire", params={"profil_id": pid})
    assert r.status_code == 404


def test_serie_sans_arbre_404(monkeypatch):
    _mock_adapter(monkeypatch)
    sid = client.post("/series", json={"titre": "Sans arbre"}).json()["id"]
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.get(f"/series/{sid}/arbre/n1/lire", params={"profil_id": pid})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_arbre_lire.py -v`
Expected: FAIL (`404 Not Found` sur la route absente, y compris pour le cas qui attend
un 200)

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/main.py`, juste avant la route `POST /series/{serie_id}/arbre`
(section `# ── Arbre des choix ─`, ligne ~1218) :

```python
@app.get("/series/{serie_id}/arbre/{noeud_id}/lire", tags=["arbre"])
async def lire_noeud(serie_id: str, noeud_id: str, profil_id: str, cle: str = Depends(cle_api)):
    """Lecture SEULE d'un nœud pour un profil (mode enfant) : texte adapté au registre,
    audio si déjà produit pour ce profil, et pour chaque choix s'il mène déjà à une
    branche écrite (le front désactive les autres). N'écrit rien, ne journalise rien."""
    serie = charger(serie_id, cle)
    profil = _profil_de(profil_id, cle)
    arbre = serie.get("arbre")
    if not arbre:
        raise HTTPException(404, "Aucun arbre pour cette série.")
    noeud, _chemin = S._trouver_noeud(arbre, noeud_id)
    if not noeud or not noeud.get("script"):
        raise HTTPException(404, "Ce chapitre n'est pas encore écrit.")
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == noeud.get("episode_n")), None)
    texte = (ep.get("script_brut") if ep else noeud["script"]) or ""
    adapte, ok = await S._adapter_cible(texte, profil["cible"], serie.get("langue"))
    audio = (ep.get("audios") or {}).get(profil_id) if ep else None
    choix_ecrits = {e["choix"]: bool(e["noeud"].get("script")) for e in noeud.get("enfants", [])}
    choix = [{"texte": c, "ecrit": choix_ecrits.get(c, False)} for c in noeud.get("choix", [])]
    return {
        "noeud_id": noeud_id, "synopsis": noeud.get("synopsis"), "texte": adapte,
        "adapte": ok, "audio_url": audio.get("url") if audio else None,
        "choix": choix, "episode_n": noeud.get("episode_n"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_arbre_lire.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_arbre_lire.py
git commit -m "feat(studio): lecture seule d'un nœud d'arbre pour un profil (mode enfant)"
```

---

## Task 9: Arbre — choisir une branche (journal + progression)

**Files:**
- Modify: `briques/studio/main.py` (nouvelle route + modèle, section arbre)
- Test: `briques/studio/test_arbre_choisir.py`

**Interfaces:**
- Consumes: `S._trouver_noeud` (existant), `S._ajouter_evenement` (Task 1).
- Produces: route `POST /series/{serie_id}/arbre/{noeud_id}/choisir` body
  `{"profil_id": str, "choix": str}` → `{"noeud_id": str}`. 404 si la branche choisie
  n'a pas encore de `script` — **aucune génération à la volée**.

- [ ] **Step 1: Write the failing test**

```python
# briques/studio/test_arbre_choisir.py
"""Tests — route POST /series/{id}/arbre/{noeud_id}/choisir (l'enfant choisit une
branche). Refuse toujours une branche non écrite (404) — jamais de génération en direct."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _serie_avec_arbre():
    sid = client.post("/series", json={"titre": "Aventure"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [
        {"n": 1, "script_brut": "Le début.", "audios": {}},
        {"n": 2, "script_brut": "Dans la grotte.", "audios": {}},
    ]
    serie["arbre"] = {
        "id": "n1", "niveau": 1, "synopsis": "Ouverture", "choix": ["Grotte", "Village"],
        "episode_n": 1, "script": "Le début.",
        "enfants": [
            {"choix": "Grotte", "noeud": {"id": "n2", "niveau": 2, "synopsis": "Grotte",
                                          "choix": [], "enfants": [], "episode_n": 2,
                                          "script": "Dans la grotte."}},
            {"choix": "Village", "noeud": {"id": "n3", "niveau": 2, "synopsis": "Village",
                                           "choix": [], "enfants": []}},  # pas encore écrit
        ],
    }
    S._save(serie)
    return sid


def test_choisir_branche_ecrite_journalise_et_avance():
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir", json={"profil_id": pid, "choix": "Grotte"})
    assert r.status_code == 200
    assert r.json() == {"noeud_id": "n2"}
    evenements = S._load_journal(pid)
    assert len(evenements) == 1
    assert evenements[0]["type"] == "arbre_choix"
    assert evenements[0]["noeud_id"] == "n2"
    assert evenements[0]["choix"] == "Grotte"
    assert evenements[0]["episode_n"] == 2


def test_choisir_branche_non_ecrite_404_et_ne_journalise_rien():
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir", json={"profil_id": pid, "choix": "Village"})
    assert r.status_code == 404
    assert S._load_journal(pid) == []


def test_choix_inconnu_404():
    sid = _serie_avec_arbre()
    pid = client.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir",
                    json={"profil_id": pid, "choix": "N'existe pas"})
    assert r.status_code == 404


def test_profil_dautrui_404(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_a = {"X-API-Key": "cle-coeur", "X-User-Id": "a-choisir"}
    entetes_b = {"X-API-Key": "cle-coeur", "X-User-Id": "b-choisir"}
    sid = client.post("/series", json={"titre": "T"}, headers=entetes_a).json()["id"]
    serie = S._load(sid)
    serie["arbre"] = {"id": "n1", "niveau": 1, "synopsis": "S", "choix": ["A"],
                      "script": "x", "enfants": [{"choix": "A",
                      "noeud": {"id": "n2", "niveau": 2, "synopsis": "S2", "choix": [],
                                "enfants": [], "script": "y"}}]}
    S._save(serie)
    pid = client.post("/profils", json={"nom": "DeB", "cible": "7-9"},
                      headers=entetes_b).json()["id"]
    r = client.post(f"/series/{sid}/arbre/n1/choisir", json={"profil_id": pid, "choix": "A"},
                    headers=entetes_a)
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/studio && python3 -m pytest test_arbre_choisir.py -v`
Expected: FAIL (`404 Not Found` générique — la route n'existe pas encore, y compris pour
le cas qui attend un 200)

- [ ] **Step 3: Write minimal implementation**

Ajouter dans `briques/studio/main.py`, juste après `lire_noeud` (Task 8) :

```python
class Choisir(BaseModel):
    profil_id: str
    choix: str


@app.post("/series/{serie_id}/arbre/{noeud_id}/choisir", tags=["arbre"])
def choisir_branche(serie_id: str, noeud_id: str, body: Choisir, cle: str = Depends(cle_api)):
    """Fait progresser un profil dans l'arbre : refuse (404) une branche pas encore
    écrite par le parent — jamais de génération à la volée pendant que l'enfant écoute."""
    serie = charger(serie_id, cle)
    _profil_de(body.profil_id, cle)
    arbre = serie.get("arbre")
    if not arbre:
        raise HTTPException(404, "Aucun arbre pour cette série.")
    noeud, _chemin = S._trouver_noeud(arbre, noeud_id)
    if not noeud:
        raise HTTPException(404, "Nœud introuvable.")
    enfant = next((e for e in noeud.get("enfants", []) if e["choix"] == body.choix), None)
    if not enfant or not enfant["noeud"].get("script"):
        raise HTTPException(404, "Cette suite n'est pas encore écrite.")
    S._ajouter_evenement(body.profil_id, {
        "type": "arbre_choix", "serie_id": serie_id, "serie_titre": serie.get("titre"),
        "episode_n": enfant["noeud"].get("episode_n"), "noeud_id": enfant["noeud"]["id"],
        "choix": body.choix,
    })
    return {"noeud_id": enfant["noeud"]["id"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/studio && python3 -m pytest test_arbre_choisir.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/studio/main.py briques/studio/test_arbre_choisir.py
git commit -m "feat(studio): choisir une branche d'arbre (journal, jamais de génération à la volée)"
```

---

## Task 10: Front parent — badge valeur éditable sur chaque chapitre

**Files:**
- Modify: `briques/studio/front.html`

**Interfaces:**
- Consumes: `GET /valeurs` (Task 5), `PATCH /series/{id}/episodes/{n}/valeur` (Task 6).

- [ ] **Step 1: Manual check avant modification**

Ouvrir `briques/studio/front.html`, repérer la ligne `let CIBLES=[], LANGUES=[], PROFILS=[], serieCourante=null;`
(ligne 184) et la fonction `renderEpisode(ep)` (ligne 547).

- [ ] **Step 2: Implémenter**

Ligne 184, ajouter `VALEURS` à la liste des variables globales :

```js
let CIBLES=[], LANGUES=[], PROFILS=[], VALEURS=[], serieCourante=null;
```

Dans `init()` (après le chargement de `LANGUES`, ligne ~206), ajouter :

```js
    VALEURS = await api('/valeurs');
```

Modifier `renderEpisode(ep)` (ligne 547-568) pour ajouter le badge valeur, juste après
la ligne `<div class="ep-head">...</div>` :

```js
function renderEpisode(ep){
  const langs = LANGUES.map(l=>`<option value="${l.code}">${esc(l.label)}</option>`).join('');
  const profilsOpts = '<option value="">— texte de référence —</option>' +
    PROFILS.map(p=>`<option value="${esc(p.id)}">${esc(p.nom)}</option>`).join('');
  const valeurOpts = '<option value="">— aucune valeur —</option>' +
    VALEURS.map(v=>`<option value="${esc(v.cle)}"${ep.valeur===v.cle?' selected':''}>${esc(v.label)}</option>`).join('');
  const suggeree = ep.valeur_suggeree && ep.valeur!==ep.valeur_suggeree
    ? `<span class="hint">suggérée : ${esc((VALEURS.find(v=>v.cle===ep.valeur_suggeree)||{}).label||ep.valeur_suggeree)}</span>` : '';
  return `<div class="card" id="ep-${ep.n}">
    <div class="ep-head"><h3>Chapitre ${ep.n} ${ep.fin_episode?'<span class="flag">fin d\'épisode</span>':''}</h3>
      <span class="muted">${esc(ep.consigne||'')}</span></div>
    <label>Valeur illustrée</label>
    <select onchange="changerValeurEpisode(${ep.n}, this.value)">${valeurOpts}</select> ${suggeree}
    <label>Lire pour…</label>
    <select id="lire-${ep.n}" onchange="lirePour(${ep.n}, this.value)">${profilsOpts}</select>
    <div class="recit" id="recit-${ep.n}">${md(ep.script_balise||ep.script_brut||'')}</div>
    <div class="row" style="margin-top:10px;align-items:end">
      <div style="flex:2"><label>Langue de l'audio</label><select id="lang-${ep.n}">${langs}</select></div>
      <div style="flex:2"><label>Pour qui</label><select id="aud-profil-${ep.n}">${profilsOpts}</select></div>
      <button class="sm" onclick="produireAudio(${ep.n})">🔊 Produire l'audio</button>
      <button class="sm ghost" onclick="couverture(${ep.n})">🖼️ Couverture</button>
      <button class="sm ghost" onclick="teaser(${ep.n})">🎬 Bande-annonce</button>
    </div>
    ${renderAudios(ep)}
    ${ep.cover_url?`<img src="${esc(ep.cover_url)}" style="max-width:200px;border-radius:10px;margin-top:8px;display:block">`:''}
    ${mediaVideo(ep.teaser_url)}
  </div>`;
}
```

Ajouter la fonction `changerValeurEpisode`, juste après `renderEpisode` :

```js
async function changerValeurEpisode(n, valeur){
  try{ await api(`/series/${S().id}/episodes/${n}/valeur`,'PATCH',{valeur: valeur||null}); await refresh(); vue('Chapitres'); }
  catch(e){ toast('⚠ '+e.message); }
}
```

- [ ] **Step 3: Vérification manuelle**

Lancer la brique localement (`cd briques/studio && python3 -m uvicorn main:app --reload
--port 6060` avec `STUDIO_DIR` pointé vers un dossier de test), ouvrir
`http://localhost:6060/atelier`, créer une série, produire un chapitre, vérifier que le
select « Valeur illustrée » liste les 16 valeurs et que le changement persiste après un
rechargement de la vue Chapitres.

- [ ] **Step 4: Commit**

```bash
git add briques/studio/front.html
git commit -m "feat(studio): badge valeur éditable sur chaque chapitre (front)"
```

---

## Task 11: Front parent — onglet Journal par profil

**Files:**
- Modify: `briques/studio/front.html`

**Interfaces:**
- Consumes: `GET /profils/{id}/journal` (Task 2).

- [ ] **Step 1: Implémenter**

Modifier `renderProfils()` (ligne 249-261) pour ajouter un bouton Journal + une zone
repliable :

```js
function renderProfils(){
  $('liste-profils').innerHTML = PROFILS.length ? PROFILS.map(p => `
    <div class="card" style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <b>${esc(p.nom)}</b>
        <select style="flex:1;min-width:150px" onchange="changerCibleProfil('${p.id}', this.value)">
          ${CIBLES.map(c=>`<option value="${esc(c.cle)}"${p.cible===c.cle?' selected':''}>${esc(c.label)}</option>`).join('')}
        </select>
        <div>
          <button class="sm ghost" onclick="basculerJournal('${p.id}')">📔</button>
          <button class="sm ghost" onclick="renommerProfil('${p.id}')">✎</button>
          <button class="sm ghost" onclick="supprimerProfil('${p.id}')">✕</button>
        </div>
      </div>
      <div id="journal-${p.id}" style="display:none"></div>
    </div>`).join('') : '<p class="muted">Aucun profil pour l\'instant.</p>';
}

async function basculerJournal(id){
  const zone = $('journal-'+id);
  if(zone.style.display==='block'){ zone.style.display='none'; return; }
  zone.style.display='block';
  zone.innerHTML = '<p class="muted">Chargement…</p>';
  try{
    const {evenements} = await api('/profils/'+id+'/journal');
    zone.innerHTML = evenements.length ? evenements.slice().reverse().map(ev=>`
      <div class="hint" style="padding:4px 0;border-top:1px solid var(--line)">
        ${esc(ev.serie_titre||'')} — chapitre ${ev.episode_n}
        ${ev.type==='arbre_choix' ? ' · a choisi « '+esc(ev.choix)+' »' : ' · écouté'}
        · ${new Date(ev.quand).toLocaleDateString('fr-FR')}
      </div>`).join('') : '<p class="muted">Rien écouté pour l\'instant.</p>';
  }catch(e){ zone.innerHTML = '<p class="err">⚠ '+esc(e.message)+'</p>'; }
}
```

- [ ] **Step 2: Vérification manuelle**

Sur la brique lancée localement (Task 10), créer un profil, appeler manuellement
`POST /series/{id}/episodes/1/marquer-lu` (via `curl` ou l'onglet réseau du navigateur)
avec ce `profil_id`, cliquer sur 📔 dans le panneau profils et vérifier que
l'événement apparaît.

- [ ] **Step 3: Commit**

```bash
git add briques/studio/front.html
git commit -m "feat(studio): onglet journal par profil (front)"
```

---

## Task 12: Front parent — nom de famille cosmétique

**Files:**
- Modify: `briques/studio/front.html`

**Interfaces:**
- Consumes: `GET /famille`, `PATCH /famille` (Task 7).

- [ ] **Step 1: Implémenter**

Dans le panneau « Profils lecteurs » (ligne 137-147), ajouter le champ juste après
`<h2>Profils lecteurs</h2>` :

```html
<h2>Profils lecteurs</h2>
<div class="row" style="margin-bottom:10px">
  <input id="famille-nom" placeholder="Nom de la famille (optionnel)" style="flex:1">
  <button class="sm ghost" onclick="enregistrerFamille()">💾</button>
</div>
```

Ajouter les fonctions JS, à la suite de `chargerProfils()` (ligne 243-247) :

```js
async function chargerFamille(){
  try{ const f = await api('/famille'); $('famille-nom').value = f.nom_famille || ''; }
  catch(e){}
}
async function enregistrerFamille(){
  try{ await api('/famille','PATCH',{nom_famille: $('famille-nom').value.trim() || null}); toast('Nom de famille enregistré'); }
  catch(e){ toast('⚠ '+e.message); }
}
```

Dans `init()` (ligne 194-210), ajouter l'appel juste après `await chargerProfils();` :

```js
  await chargerProfils();
  await chargerFamille();
  chargerListe();
```

- [ ] **Step 2: Vérification manuelle**

Recharger `http://localhost:6060/atelier`, saisir un nom de famille, cliquer 💾,
recharger la page, vérifier que le champ est pré-rempli.

- [ ] **Step 3: Commit**

```bash
git add briques/studio/front.html
git commit -m "feat(studio): nom de famille cosmétique sur le panneau profils (front)"
```

---

## Task 13: Front enfant — page de lecture interactive `lecture.html`

**Files:**
- Create: `briques/studio/lecture.html`
- Modify: `briques/studio/main.py` (route de service)

**Interfaces:**
- Consumes : `GET /series/{id}` (existant), `GET /profils/{id}/journal` (Task 2),
  `POST /series/{id}/episodes/{n}/marquer-lu` (Task 3), `GET /series/{id}/episodes/{n}/adapte`
  (existant), `GET /series/{id}/arbre/{noeud_id}/lire` (Task 8),
  `POST /series/{id}/arbre/{noeud_id}/choisir` (Task 9).
- Produces : page servie sur `GET /lecture?serie=<id>&profil=<id>`.

- [ ] **Step 1: Créer la page**

```html
<!-- briques/studio/lecture.html -->
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lecture</title>
<link rel="stylesheet" href="/workplace.css">
<style>
  body{max-width:640px;margin:0 auto;padding:16px}
  .recit{white-space:pre-wrap}
  .choix-btn{display:block;width:100%;margin-top:10px;padding:16px;font-size:1.05rem}
  .choix-btn[disabled]{opacity:.4;cursor:not-allowed}
</style>
</head>
<body>
<div class="panel">
  <h2 id="titre">…</h2>
  <div id="corps"><p class="muted">Chargement…</p></div>
  <div class="err" id="err"></div>
</div>
<script>
const $ = id => document.getElementById(id);
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const API_KEY = new URLSearchParams(location.search).get('api_key') || localStorage.getItem('studio_api_key') || '';
const HDR = {'Content-Type':'application/json', ...(API_KEY ? {'X-API-Key': API_KEY} : {})};
const API_BASE = window.STUDIO_API_BASE || '';
async function api(path, method='GET', body=null){
  const r = await fetch(API_BASE + path, {method, headers:HDR, body: body!=null?JSON.stringify(body):null});
  if(!r.ok){ const e = await r.json().catch(()=>({})); throw new Error(e.detail || ('HTTP '+r.status)); }
  return r.status===204 ? null : r.json();
}

const params = new URLSearchParams(location.search);
const SERIE_ID = params.get('serie');
const PROFIL_ID = params.get('profil');
let SERIE = null;

async function init(){
  if(!SERIE_ID || !PROFIL_ID){ $('err').textContent = '⚠ Lien de lecture incomplet (série ou profil manquant).'; return; }
  try{
    SERIE = await api(`/series/${SERIE_ID}`);
    $('titre').textContent = SERIE.titre;
    if(SERIE.arbre) await lireArbre();
    else await lireLineaire();
  }catch(e){ $('err').textContent = '⚠ '+e.message; }
}

// ── Séries avec arbre des choix ───────────────────────────────────
async function lireArbre(){
  const journal = (await api(`/profils/${PROFIL_ID}/journal`)).evenements;
  const dernierChoix = journal.slice().reverse().find(ev => ev.type==='arbre_choix' && ev.serie_id===SERIE_ID);
  const noeudId = dernierChoix ? dernierChoix.noeud_id : SERIE.arbre.id;
  await afficherNoeud(noeudId);
}

async function afficherNoeud(noeudId){
  $('corps').innerHTML = '<p class="muted">Chargement…</p>';
  let n;
  try{ n = await api(`/series/${SERIE_ID}/arbre/${noeudId}/lire?profil_id=${encodeURIComponent(PROFIL_ID)}`); }
  catch(e){ $('corps').innerHTML = '<p class="err">⚠ '+esc(e.message)+'</p>'; return; }

  const audio = n.audio_url ? `<audio controls style="width:100%;margin-top:10px" src="${esc(n.audio_url)}"></audio>` : '';
  const boutons = n.choix.map(c => `
    <button class="choix-btn" ${c.ecrit ? `onclick='choisir(${JSON.stringify(noeudId)}, ${JSON.stringify(c.texte)})'` : 'disabled'}>
      ${esc(c.texte)}${c.ecrit ? '' : ' · (pas encore prêt)'}
    </button>`).join('');
  $('corps').innerHTML = `<div class="recit">${esc(n.texte)}</div>${audio}${boutons}`;

  if(n.episode_n) await api(`/series/${SERIE_ID}/episodes/${n.episode_n}/marquer-lu`, 'POST', {profil_id: PROFIL_ID});
}

async function choisir(noeudId, choix){
  $('corps').innerHTML = '<p class="muted">…</p>';
  try{
    const res = await api(`/series/${SERIE_ID}/arbre/${noeudId}/choisir`, 'POST', {profil_id: PROFIL_ID, choix});
    await afficherNoeud(res.noeud_id);
  }catch(e){ $('corps').innerHTML = '<p class="err">⚠ '+esc(e.message)+'</p>'; }
}

// ── Séries linéaires (sans arbre) ──────────────────────────────────
async function lireLineaire(){
  const journal = (await api(`/profils/${PROFIL_ID}/journal`)).evenements;
  const dernier = journal.slice().reverse().find(ev => ev.type==='chapitre_lu' && ev.serie_id===SERIE_ID);
  const n = dernier ? dernier.episode_n : 1;
  await afficherChapitre(n);
}

async function afficherChapitre(n){
  const ep = (SERIE.episodes||[]).find(e => e.n===n);
  if(!ep){ $('corps').innerHTML = '<p class="muted">Rien à écouter pour l\'instant — reviens plus tard !</p>'; return; }
  $('corps').innerHTML = '<p class="muted">Chargement…</p>';
  let texte;
  try{ texte = (await api(`/series/${SERIE_ID}/episodes/${n}/adapte?profil_id=${encodeURIComponent(PROFIL_ID)}`)).texte; }
  catch(e){ $('corps').innerHTML = '<p class="err">⚠ '+esc(e.message)+'</p>'; return; }

  const audioUrl = (ep.audios||{})[PROFIL_ID] ? (ep.audios||{})[PROFIL_ID].url : null;
  const audio = audioUrl ? `<audio controls style="width:100%;margin-top:10px" src="${esc(audioUrl)}"></audio>` : '';
  const suite = (SERIE.episodes||[]).some(e => e.n===n+1)
    ? `<button class="choix-btn" onclick="afficherChapitre(${n+1})">Chapitre suivant</button>` : '';
  $('corps').innerHTML = `<div class="recit">${esc(texte)}</div>${audio}${suite}`;
  await api(`/series/${SERIE_ID}/episodes/${n}/marquer-lu`, 'POST', {profil_id: PROFIL_ID});
}

init();
</script>
</body>
</html>
```

- [ ] **Step 2: Servir la page**

Dans `briques/studio/main.py`, ajouter juste après `_FRONT = Path(__file__).parent / "front.html"`
(ligne 143) :

```python
_LECTURE = Path(__file__).parent / "lecture.html"
```

Ajouter la route juste après `front()` (après la ligne 153) :

```python
@app.get("/lecture", response_class=HTMLResponse, include_in_schema=False)
def lecture():
    """Mode enfant : lecture interactive d'une série (?serie=&profil=), séparée de
    l'atelier de co-création."""
    return _LECTURE.read_text(encoding="utf-8")
```

- [ ] **Step 3: Vérification manuelle**

Sur la brique lancée localement, produire une série avec au moins un chapitre et un
profil, ouvrir `http://localhost:6060/lecture?serie=<id>&profil=<id>` :
- Cas linéaire : le texte adapté s'affiche, `GET /profils/{id}/journal` montre un nouvel
  événement `chapitre_lu` après le chargement.
- Cas avec arbre : construire un arbre minimal en base (voir Task 8/9), vérifier que la
  branche écrite est cliquable, que la branche non écrite est visuellement désactivée
  avec la mention « pas encore prêt », et qu'un clic sur la branche écrite avance vers
  le nœud suivant tout en journalisant `arbre_choix`.

- [ ] **Step 4: Commit**

```bash
git add briques/studio/lecture.html briques/studio/main.py
git commit -m "feat(studio): page de lecture interactive pour l'enfant (mode arbre + linéaire)"
```

---

## Task 14: Manifest — exposer les nouvelles capacités à l'assistant

**Files:**
- Modify: `briques/studio/manifest.json`

**Interfaces:**
- Consumes: toutes les routes créées aux Tasks 2, 3, 5, 6, 7, 8, 9.
- Vérifié par `briques/studio/test_manifest_capacites.py` (existant, ne pas modifier) :
  chaque capacité doit pointer une route réelle, et toute capacité POST/PATCH/DELETE doit
  être `action: true`.

- [ ] **Step 1: Ajouter les capacités**

Dans `briques/studio/manifest.json`, ajouter ces 8 entrées à la fin du tableau
`"capacites"` (après `studio_episode_teaser`, avant le `]` fermant, en ajoutant une
virgule après l'accolade fermante de `studio_episode_teaser`) :

```json
    {
      "nom": "studio_profil_journal_lire",
      "description": "Liste ce qu'un profil lecteur a écouté/choisi (journal, V1 saga familiale) : chapitres écoutés, branches d'arbre choisies. Récupère profil_id via studio_profils_lister. Lecture seule.",
      "methode": "GET",
      "chemin": "/profils/{profil_id}/journal",
      "params": {
        "profil_id": {
          "type": "string",
          "description": "Identifiant du profil (via studio_profils_lister).",
          "requis": true
        }
      },
      "action": false
    },
    {
      "nom": "studio_episode_marquer_lu",
      "description": "Journalise qu'un profil a écouté/lu un chapitre. ACTION.",
      "methode": "POST",
      "chemin": "/series/{serie_id}/episodes/{n}/marquer-lu",
      "params": {
        "serie_id": {
          "type": "string",
          "description": "Id de la série (via studio_series_lister).",
          "requis": true
        },
        "n": {
          "type": "integer",
          "description": "Numéro du chapitre.",
          "requis": true
        },
        "profil_id": {
          "type": "string",
          "description": "Id du profil lecteur (via studio_profils_lister).",
          "requis": true
        }
      },
      "action": true
    },
    {
      "nom": "studio_valeurs_lister",
      "description": "Liste les 16 valeurs humaines pouvant être associées à un chapitre (courage, empathie, entraide…). Lecture seule.",
      "methode": "GET",
      "chemin": "/valeurs",
      "params": {},
      "action": false
    },
    {
      "nom": "studio_episode_valeur_definir",
      "description": "Retient ou change la valeur humaine illustrée par un chapitre (le Script Doctor en suggère une automatiquement à l'écriture ; cette route permet de la confirmer ou de la changer). ACTION.",
      "methode": "PATCH",
      "chemin": "/series/{serie_id}/episodes/{n}/valeur",
      "params": {
        "serie_id": {
          "type": "string",
          "description": "Id de la série (via studio_series_lister).",
          "requis": true
        },
        "n": {
          "type": "integer",
          "description": "Numéro du chapitre.",
          "requis": true
        },
        "valeur": {
          "type": "string",
          "description": "Clé de valeur (via studio_valeurs_lister), ou absente/null pour retirer."
        }
      },
      "action": true
    },
    {
      "nom": "studio_famille_lire",
      "description": "Lit le nom de famille cosmétique associé au compte (V1 saga familiale). Lecture seule.",
      "methode": "GET",
      "chemin": "/famille",
      "params": {},
      "action": false
    },
    {
      "nom": "studio_famille_nom_definir",
      "description": "Définit ou change le nom de famille cosmétique associé au compte (n'affecte aucune donnée d'enfant). ACTION.",
      "methode": "PATCH",
      "chemin": "/famille",
      "params": {
        "nom_famille": {
          "type": "string",
          "description": "Nouveau nom de famille (optionnel : absent/null pour retirer)."
        }
      },
      "action": true
    },
    {
      "nom": "studio_arbre_noeud_lire",
      "description": "Lecture SEULE d'un nœud d'arbre pour un profil (mode enfant) : texte adapté, audio si produit, et pour chaque choix s'il mène déjà à une branche écrite. Récupère serie_id via studio_series_lister et profil_id via studio_profils_lister.",
      "methode": "GET",
      "chemin": "/series/{serie_id}/arbre/{noeud_id}/lire",
      "params": {
        "serie_id": {
          "type": "string",
          "description": "Id de la série.",
          "requis": true
        },
        "noeud_id": {
          "type": "string",
          "description": "Id du nœud d'arbre.",
          "requis": true
        },
        "profil_id": {
          "type": "string",
          "description": "Id du profil lecteur (via studio_profils_lister).",
          "requis": true
        }
      },
      "action": false
    },
    {
      "nom": "studio_arbre_choisir",
      "description": "Fait choisir à un profil une branche déjà écrite de l'arbre (journalise le choix). Refuse (404) toute branche pas encore écrite — jamais de génération à la volée. ACTION.",
      "methode": "POST",
      "chemin": "/series/{serie_id}/arbre/{noeud_id}/choisir",
      "params": {
        "serie_id": {
          "type": "string",
          "description": "Id de la série.",
          "requis": true
        },
        "noeud_id": {
          "type": "string",
          "description": "Id du nœud d'arbre courant.",
          "requis": true
        },
        "profil_id": {
          "type": "string",
          "description": "Id du profil lecteur (via studio_profils_lister).",
          "requis": true
        },
        "choix": {
          "type": "string",
          "description": "Le texte du choix retenu (parmi ceux renvoyés par studio_arbre_noeud_lire).",
          "requis": true
        }
      },
      "action": true
    }
```

- [ ] **Step 2: Vérifier le contrat manifest↔routes**

Run: `cd briques/studio && python3 -m pytest test_manifest_capacites.py -v`
Expected: PASS (4 tests) — chaque nouvelle capacité pointe une route réelle, aucun nom en
double, toutes les écritures sont `action: true`.

- [ ] **Step 3: Suite complète (non-régression)**

Run: `cd briques/studio && python3 -m pytest -v`
Expected: PASS — tous les tests existants (y compris `test_front.py`, dont les assertions
sur `renderProfils`/`renderAudios` ne sont pas affectées par les Tasks 10-12) + les 9
nouveaux fichiers de tests de ce plan.

- [ ] **Step 4: Commit**

```bash
git add briques/studio/manifest.json
git commit -m "feat(studio): expose les 8 nouvelles capacités V1 saga familiale à l'assistant"
```
