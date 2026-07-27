# Veille-info — pause par thématique Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un bouton « pause » par thématique dans l'onglet Sources RSS de l'Atelier Veille : une thématique en pause n'est plus traitée par le pipeline quotidien (`digest.py`) — donc plus aucun appel LLM (coût) tant qu'elle reste en pause.

**Architecture:** La table `sources` a DÉJÀ une colonne `enabled` (posée à 1 par défaut, jamais exposée par aucune route actuellement) et `digest.py::_traiter_utilisateur` s'appuie DÉJÀ sur `stockage.thematiques_actives(user_id)`, qui ne renvoie que les thématiques ayant au moins une source `enabled = 1`. La pause par thématique se réduit donc à : mettre `enabled = 0` sur TOUTES les sources d'une thématique donnée (nouvelle fonction stockage + route), sans toucher au pipeline lui-même — le filtre existant s'en charge. C'est une extension minimale, pas une nouvelle table.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest, JS vanilla (front autoporté).

## Global Constraints

- Aucune migration de schéma nécessaire — la colonne `sources.enabled` existe déjà (`briques/veille-info/stockage.py:39`).
- Ne PAS modifier `digest.py` — `thematiques_actives()` filtre déjà `enabled = 1`, c'est le mécanisme de pause lui-même (un test de non-régression suffit pour le PROUVER, pas une modif).
- « En pause » pour une thématique = AUCUNE de ses sources n'a `enabled = 1` (si au moins une source est active, la thématique n'est PAS considérée en pause — cohérent avec `thematiques_actives()`, qui inclut la thématique dès qu'UNE source suffit).
- Suivre le style existant de `briques/veille-info/main.py`/`stockage.py` (fonctions `def xxx_route(...)`, `Depends(tenant_actuel)`, `HTTPException(404, ...)` sur cible introuvable) et de `briques/atelier-veille/main.py` (pass-through `_entetes_aval`).

---

## File Structure

- Modify: `briques/veille-info/stockage.py` — `lister_thematiques()` + `basculer_pause_thematique()`.
- Modify: `briques/veille-info/main.py` — routes `GET /thematiques` + `PATCH /thematiques/{thematique}/pause`.
- Modify: `briques/atelier-veille/main.py` — pass-through `GET /veille/thematiques` + `PATCH /veille/thematiques/{thematique}/pause`.
- Modify: `briques/atelier-veille/front.html` — onglet Sources RSS regroupé par thématique avec bouton pause, motif du regroupement déjà utilisé dans l'onglet Digests (`chargerDigests`).
- Test: `briques/veille-info/test_stockage.py`, `briques/veille-info/test_main.py`, `briques/veille-info/test_digest.py`, `briques/atelier-veille/test_composition.py`.

---

### Task 1: `stockage.py` — lister et basculer la pause par thématique

**Files:**
- Modify: `briques/veille-info/stockage.py`
- Test: `briques/veille-info/test_stockage.py`

**Interfaces:**
- Produces: `lister_thematiques(user_id: str) -> list[dict]` → `[{"thematique": str, "nb_sources": int, "en_pause": bool}]`. `basculer_pause_thematique(user_id: str, thematique: str, en_pause: bool) -> int` → nombre de sources affectées (0 si la thématique n'existe pas pour cet utilisateur).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `briques/veille-info/test_stockage.py` (à la suite des tests existants sur les sources/thématiques) :

```python
def test_lister_thematiques_regroupe_par_thematique():
    stockage.creer_source("pause-alice", "Flux A", "https://a.example/rss", thematique="Tech")
    stockage.creer_source("pause-alice", "Flux B", "https://b.example/rss", thematique="Tech")
    stockage.creer_source("pause-alice", "Flux C", "https://c.example/rss", thematique="Cuisine")
    resultat = stockage.lister_thematiques("pause-alice")
    par_nom = {r["thematique"]: r for r in resultat}
    assert par_nom["Tech"]["nb_sources"] == 2
    assert par_nom["Tech"]["en_pause"] is False
    assert par_nom["Cuisine"]["nb_sources"] == 1
    assert par_nom["Cuisine"]["en_pause"] is False


def test_basculer_pause_desactive_toutes_les_sources_de_la_thematique():
    stockage.creer_source("pause-bob", "Flux A", "https://a2.example/rss", thematique="Tech")
    stockage.creer_source("pause-bob", "Flux B", "https://b2.example/rss", thematique="Tech")
    stockage.creer_source("pause-bob", "Flux C", "https://c2.example/rss", thematique="Cuisine")

    n = stockage.basculer_pause_thematique("pause-bob", "Tech", en_pause=True)
    assert n == 2

    resultat = stockage.lister_thematiques("pause-bob")
    par_nom = {r["thematique"]: r for r in resultat}
    assert par_nom["Tech"]["en_pause"] is True
    assert par_nom["Cuisine"]["en_pause"] is False
    # thematiques_actives ne renvoie plus "Tech" : c'est CE filtre qui fait office de pause
    # côté pipeline (digest.py) — aucune modif de digest.py nécessaire.
    assert "Tech" not in stockage.thematiques_actives("pause-bob")
    assert "Cuisine" in stockage.thematiques_actives("pause-bob")


def test_basculer_pause_reprendre():
    stockage.creer_source("pause-carla", "Flux A", "https://a3.example/rss", thematique="Tech")
    stockage.basculer_pause_thematique("pause-carla", "Tech", en_pause=True)
    n = stockage.basculer_pause_thematique("pause-carla", "Tech", en_pause=False)
    assert n == 1
    assert "Tech" in stockage.thematiques_actives("pause-carla")


def test_basculer_pause_thematique_inexistante_renvoie_zero():
    n = stockage.basculer_pause_thematique("pause-dan", "Inexistante", en_pause=True)
    assert n == 0
```

- [ ] **Step 2: Run pour vérifier l'échec**

Run: `cd briques/veille-info && python -m pytest test_stockage.py -k "thematique" -v`
Expected: `AttributeError: module 'stockage' has no attribute 'lister_thematiques'`.

- [ ] **Step 3: Implémenter dans `briques/veille-info/stockage.py`**

Ajouter juste après `retagger_source` (ligne 198) :

```python
def lister_thematiques(user_id: str) -> list[dict]:
    """Regroupe les sources de `user_id` par thématique. `en_pause` vaut True quand AUCUNE
    source du groupe n'est active — cohérent avec `thematiques_actives()` (S199), qui
    inclut une thématique dès qu'UNE seule de ses sources est active."""
    with _conn() as c:
        rows = c.execute(
            "SELECT thematique, COUNT(*) AS nb_sources, SUM(enabled) AS nb_actives "
            "FROM sources WHERE user_id = ? GROUP BY thematique", (user_id,)).fetchall()
    return [{"thematique": r["thematique"], "nb_sources": r["nb_sources"],
            "en_pause": (r["nb_actives"] or 0) == 0} for r in rows]


def basculer_pause_thematique(user_id: str, thematique: str, en_pause: bool) -> int:
    """Met en pause (enabled=0) ou reprend (enabled=1) TOUTES les sources de cette
    thématique pour cet utilisateur. Renvoie le nombre de sources affectées (0 = thématique
    inconnue pour cet utilisateur)."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE sources SET enabled = ? WHERE user_id = ? AND thematique = ?",
            (0 if en_pause else 1, user_id, thematique))
    return cur.rowcount
```

- [ ] **Step 4: Run pour vérifier que les tests passent**

Run: `cd briques/veille-info && python -m pytest test_stockage.py -k "thematique" -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/stockage.py briques/veille-info/test_stockage.py
git commit -m "feat(veille-info): stockage.lister_thematiques/basculer_pause_thematique"
```

---

### Task 2: `veille-info/main.py` — routes HTTP pause par thématique

**Files:**
- Modify: `briques/veille-info/main.py`
- Test: `briques/veille-info/test_main.py`

**Interfaces:**
- Consumes: `stockage.lister_thematiques`, `stockage.basculer_pause_thematique` (Task 1).
- Produces: `GET /thematiques` → `list[dict]`. `PATCH /thematiques/{thematique}/pause` (body `{"en_pause": bool}`) → `{"ok": True, "nb_sources": int}` ou 404.

- [ ] **Step 1: Écrire les tests qui échouent**

`briques/veille-info/test_main.py` a un `client = TestClient(main.app)` module-level (pas de fixture) et un helper `_entetes(utilisateur) -> dict` (`{"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}`), à combiner avec `monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")`. Identifiants préfixés `main-` obligatoire (DB de test partagée entre TOUS les tests du fichier, cf. docstring en tête de fichier). Ajouter à la suite des tests existants sur `/sources` :

```python
def test_get_thematiques(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    client.post("/sources", headers=_entetes("main-pause-alice"),
               json={"nom": "Flux A", "url": "https://a4.example/rss", "thematique": "Tech"})
    r = client.get("/thematiques", headers=_entetes("main-pause-alice"))
    assert r.status_code == 200
    corps = r.json()
    assert any(t["thematique"] == "Tech" and t["nb_sources"] == 1 for t in corps)


def test_patch_pause_thematique(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    client.post("/sources", headers=_entetes("main-pause-bob"),
               json={"nom": "Flux B", "url": "https://b4.example/rss", "thematique": "Tech"})
    r = client.patch("/thematiques/Tech/pause", json={"en_pause": True},
                     headers=_entetes("main-pause-bob"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "nb_sources": 1}

    corps = client.get("/thematiques", headers=_entetes("main-pause-bob")).json()
    assert next(t for t in corps if t["thematique"] == "Tech")["en_pause"] is True


def test_patch_pause_thematique_inexistante_404(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.patch("/thematiques/Inexistante/pause", json={"en_pause": True},
                     headers=_entetes("main-pause-carla"))
    assert r.status_code == 404
```

- [ ] **Step 2: Run pour vérifier l'échec**

Run: `cd briques/veille-info && python -m pytest test_main.py -k "thematique" -v`
Expected: FAIL (404 sur route inexistante pour `GET /thematiques`/`PATCH .../pause`).

- [ ] **Step 3: Implémenter dans `briques/veille-info/main.py`**

Ajouter juste après la route `retagger_source_route` (après la ligne `return {"ok": True}` qui suit `class RetaggerSource`) :

```python
@app.get("/thematiques", tags=["sources"])
def lister_thematiques_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_thematiques(tenant)


class BasculerPauseThematique(BaseModel):
    en_pause: bool


@app.patch("/thematiques/{thematique}/pause", tags=["sources"])
def basculer_pause_thematique_route(thematique: str, body: BasculerPauseThematique,
                                    tenant: str = Depends(tenant_actuel)):
    n = stockage.basculer_pause_thematique(tenant, thematique, body.en_pause)
    if n == 0:
        raise HTTPException(404, "Thématique introuvable.")
    return {"ok": True, "nb_sources": n}
```

- [ ] **Step 4: Run pour vérifier que les tests passent**

Run: `cd briques/veille-info && python -m pytest test_main.py -k "thematique" -v`
Expected: 3 passed.

- [ ] **Step 5: Run toute la suite de la brique**

Run: `cd briques/veille-info && python -m pytest -v`
Expected: tous les tests passent.

- [ ] **Step 6: Commit**

```bash
git add briques/veille-info/main.py briques/veille-info/test_main.py
git commit -m "feat(veille-info): routes GET /thematiques + PATCH /thematiques/{t}/pause"
```

---

### Task 3: Preuve que le pipeline saute une thématique en pause (aucune modif de `digest.py`)

**Files:**
- Test: `briques/veille-info/test_digest.py`

**Interfaces:**
- Consumes: `stockage.basculer_pause_thematique` (Task 1), `digest.executer_digest_quotidien` (existant, inchangé).

- [ ] **Step 1: Écrire le test qui PROUVE le comportement (doit déjà passer, aucun code à changer)**

Ajouter dans `briques/veille-info/test_digest.py` (motif exact de `test_pipeline_complet_cree_un_digest`, ligne 21) :

```python
def test_thematique_en_pause_aucun_digest_ni_appel_llm(monkeypatch):
    """Preuve du mécanisme de pause (S199+) : une thématique dont toutes les sources sont
    enabled=0 est absente de thematiques_actives() → _traiter_utilisateur ne l'itère jamais
    → aucun appel LLM, aucun coût. Aucune modification de digest.py n'est nécessaire, le
    filtre existant suffit — ce test le prouve plutôt que de l'affirmer."""
    stockage.creer_source("digest-pause-alice", "Flux Tech", "https://pause-a.example/rss",
                          thematique="Tech")
    stockage.basculer_pause_thematique("digest-pause-alice", "Tech", en_pause=True)

    appels_llm = []
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article 1", "url": "https://pause-a.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete",
                        lambda prompt, system="": appels_llm.append(1) or "Résumé.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-pause-alice"])

    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 0}
    assert appels_llm == []
```

- [ ] **Step 2: Run pour confirmer que ça passe SANS modifier `digest.py`**

Run: `cd briques/veille-info && python -m pytest test_digest.py -k pause -v`
Expected: 1 passed (aucun code de `digest.py` n'a été touché — c'est `thematiques_actives()`, déjà en place, qui porte tout le mécanisme).

- [ ] **Step 3: Commit**

```bash
git add briques/veille-info/test_digest.py
git commit -m "test(veille-info): prouve qu'une thématique en pause coûte 0 appel LLM"
```

---

### Task 4: Pass-through `atelier-veille` vers les nouvelles routes

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Test: `briques/atelier-veille/test_composition.py`

**Interfaces:**
- Consumes: `GET /thematiques`, `PATCH /thematiques/{thematique}/pause` (Task 2, côté `veille-info`).
- Produces: `GET /veille/thematiques`, `PATCH /veille/thematiques/{thematique}/pause` (pass-through pur, motif `_entetes_aval` déjà utilisé par toutes les autres routes `/veille/*` de ce fichier).

- [ ] **Step 1: Écrire les tests qui échouent**

`briques/atelier-veille/test_composition.py` importe `main as M` et fournit déjà un helper `_client_json(rep_json, status=200, ...)` qui renvoie une classe `FauxClient` factice (posée via `monkeypatch.setattr(M.httpx, "AsyncClient", ...)`), utilisé par tous les tests `/veille/*` existants (ex. `test_lister_sources_proxifie_vers_veille_info`, `test_lister_sources_relaie_lidentite_recue`). Ajouter à la suite, en réutilisant ce MÊME helper :

```python
def test_lister_thematiques_proxifie_vers_veille_info(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json([{"thematique": "Tech", "nb_sources": 2, "en_pause": False}]))
    r = client.get("/veille/thematiques", headers={"X-User-Id": "toussaint"})
    assert r.status_code == 200
    assert r.json()[0]["thematique"] == "Tech"


def test_basculer_pause_thematique_proxifie_et_relaie_le_corps(monkeypatch):
    Faux = _client_json({"ok": True, "nb_sources": 2})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.patch("/veille/thematiques/Tech/pause", json={"en_pause": True},
                     headers={"X-User-Id": "toussaint"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "nb_sources": 2}
    _, url, headers, corps = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/thematiques/Tech/pause"
    assert headers == {"X-User-Id": "toussaint"}
    assert corps == {"en_pause": True}


def test_basculer_pause_thematique_inexistante_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Thématique introuvable."}, status=404))
    r = client.patch("/veille/thematiques/Inexistante/pause", json={"en_pause": True},
                     headers={"X-User-Id": "toussaint"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run pour vérifier l'échec**

Run: `cd briques/atelier-veille && python -m pytest test_composition.py -k thematique -v`
Expected: FAIL (404, route absente).

- [ ] **Step 3: Implémenter dans `briques/atelier-veille/main.py`**

Ajouter juste après la route `retagger_source` (après son `return corps`) :

```python
class BasculerPauseThematique(BaseModel):
    en_pause: bool


@app.get("/veille/thematiques", tags=["veille"])
async def lister_thematiques(x_user_id: Optional[str] = Header(None),
                             x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/thematiques", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.patch("/veille/thematiques/{thematique}/pause", tags=["veille"])
async def basculer_pause_thematique(thematique: str, body: BasculerPauseThematique,
                                    x_user_id: Optional[str] = Header(None),
                                    x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{VEILLE_INFO_URL}/thematiques/{thematique}/pause",
                              headers=entetes, json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps
```

- [ ] **Step 4: Run pour vérifier que les tests passent**

Run: `cd briques/atelier-veille && python -m pytest test_composition.py -k thematique -v`
Expected: 2 passed.

- [ ] **Step 5: Run toute la suite de la brique**

Run: `cd briques/atelier-veille && python -m pytest -v`
Expected: tous les tests passent.

- [ ] **Step 6: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/test_composition.py
git commit -m "feat(atelier-veille): proxy GET /veille/thematiques + PATCH pause"
```

---

### Task 5: Front — bouton pause par thématique dans l'onglet Sources RSS

**Files:**
- Modify: `briques/atelier-veille/front.html`

**Interfaces:**
- Consumes: `GET ${API_BASE}/veille/thematiques`, `PATCH ${API_BASE}/veille/thematiques/{thematique}/pause` (Task 4). (`API_BASE` existe déjà si le plan `2026-07-27-atelier-veille-isolation-multiuser.md` a été exécuté avant celui-ci ; sinon utiliser directement les chemins absolus `/veille/thematiques` — voir note ci-dessous.)

- [ ] **Step 1: Remplacer `chargerSources` pour regrouper par thématique avec bouton pause**

Dans `briques/atelier-veille/front.html`, remplacer la fonction `chargerSources` (ligne ~116-132) par :

```javascript
async function chargerSources() {
  const cible = document.getElementById('liste-sources');
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  try {
    const [rSources, rThematiques] = await Promise.all([
      fetch(`${API_BASE}/veille/sources`),
      fetch(`${API_BASE}/veille/thematiques`),
    ]);
    if (!rSources.ok) throw new Error((await rSources.json()).detail || 'Erreur');
    const sources = await rSources.json();
    const thematiques = rThematiques.ok ? await rThematiques.json() : [];
    const parThematique = {};
    thematiques.forEach(t => { parThematique[t.thematique] = t; });

    const groupes = {};
    sources.forEach(s => { const t = s.thematique || 'Général'; (groupes[t] = groupes[t] || []).push(s); });

    cible.innerHTML = Object.keys(groupes).length ? Object.keys(groupes).sort().map(t => {
      const info = parThematique[t === 'Général' ? '' : t];
      const enPause = info ? info.en_pause : false;
      return `
      <div style="margin-top:14px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <h4 style="margin:0;color:var(--accent)">${esc(t)} ${enPause ? '<span style="color:var(--mut);font-size:.75rem">· en pause</span>' : ''}</h4>
          <button onclick="basculerPauseThematique('${esc(t === 'Général' ? '' : t)}', ${!enPause})"
            style="border:1px solid var(--line);background:transparent;color:${enPause ? 'var(--ok)' : 'var(--mut)'};border-radius:8px;padding:4px 10px;font-size:.8rem;cursor:pointer">
            ${enPause ? 'Reprendre' : 'Mettre en pause'}
          </button>
        </div>
        ${groupes[t].map(s => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)">
            <div><b>${esc(s.nom)}</b><br><span style="color:var(--mut);font-size:.8rem">${esc(s.url)}</span></div>
            <button onclick="supprimerSource(${s.id})" style="border:1px solid var(--bad);background:transparent;color:var(--bad);border-radius:8px;padding:5px 10px;cursor:pointer">Retirer</button>
          </div>`).join('')}
      </div>`;
    }).join('') : '<p style="color:var(--mut)">Aucune source suivie pour l\'instant.</p>';
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function basculerPauseThematique(thematique, enPause) {
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  try {
    const r = await fetch(`${API_BASE}/veille/thematiques/${encodeURIComponent(thematique)}/pause`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({en_pause: enPause}),
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    await chargerSources();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}
```

**Note :** la thématique `'Général'` (affichage) correspond à la chaîne vide `''` côté API (motif déjà utilisé par `chargerDigests`, ligne 178 : `d.thematique || 'Général'`) — d'où la conversion `t === 'Général' ? '' : t` avant d'appeler l'API.

**Si le plan `2026-07-27-atelier-veille-isolation-multiuser.md` N'A PAS ENCORE été exécuté** (donc `API_BASE` n'existe pas dans le fichier), remplacer partout `${API_BASE}` par une chaîne vide dans le code ci-dessus (les chemins restent absolus, comportement autoporté historique inchangé) — vérifier avec `grep -n "const API_BASE" briques/atelier-veille/front.html` avant d'écrire cette étape.

- [ ] **Step 2: Vérification manuelle (pas de test automatisé sur du JS inline)**

Run: `python3 -m http.server 8842 --directory briques/atelier-veille &` puis ouvrir `http://localhost:8842/front.html` dans un navigateur (les appels `fetch` échoueront sans le backend — c'est attendu, vérifier seulement qu'il n'y a pas d'erreur de syntaxe JS via la console navigateur, `F12`). Arrêter le serveur ensuite (`kill %1`).

Alternative plus fiable : `node --check` n'existe pas pour du JS inline en HTML — à défaut, relire le diff ligne par ligne pour repérer un template-literal mal fermé (source d'erreur la plus fréquente ici, avec 3 niveaux de guillemets imbriqués).

- [ ] **Step 3: Commit**

```bash
git add briques/atelier-veille/front.html
git commit -m "feat(atelier-veille): bouton pause par thématique dans l'onglet Sources RSS"
```

---

## Déploiement (hors plan, à faire manuellement sur le HP après merge)

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
cd ~/workplace && git pull --ff-only
( cd briques/veille-info && docker compose up -d --build )
( cd briques/atelier-veille && docker compose up -d --build )
'
```

Vérifier ensuite dans l'onglet Sources RSS de l'Atelier Veille que chaque groupe (« Cosmétique », « IA ») a bien son bouton « Mettre en pause », et qu'après un clic la thématique passe en « en pause » sans erreur.
