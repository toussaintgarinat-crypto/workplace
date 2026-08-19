# Onglet Prospection dans atelier-veille — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un 4ᵉ onglet « Prospection » dans `atelier-veille` (port 6130) qui permet de piloter manuellement `veille-prospection` (S193, port 6140, aujourd'hui sans UI) : créer/lancer une campagne sur une zone `geo` existante, voir les prospects poussés au CRM Forge, préparer des brouillons de démarchage email.

**Architecture:** `atelier-veille` reste un backend de composition pur (proxy HTTP serveur→serveur, pass-through de l'identité, motif déjà en place pour `veille-info`). Deux petits ajouts côté `veille-prospection` (route d'exécution manuelle scopée tenant, tag du nom de zone dans les notes CRM) permettent au proxy de filtrer les prospects par campagne sans toucher au schéma de Forge.

**Tech Stack:** FastAPI + httpx (async) côté proxy, SQLite côté `veille-prospection`, vanilla JS côté front (motif déjà utilisé par les 3 autres onglets de `atelier-veille`).

## Global Constraints

- Aucune modification du schéma CRM de Forge (`briques/forge/forge/core/`) — filtrage par campagne via le texte des `notes`, jamais une colonne dédiée.
- Aucun envoi automatique d'email — `mail POST /demarchage/preparer` reste un point d'arrêt humain (brouillons uniquement), inchangé.
- Tous les tests sont offline (mocks `httpx`/`monkeypatch`, jamais de vrai réseau) — motif déjà en place dans les deux briques touchées.
- Toute nouvelle route de composition suit exactement le motif d'erreur des routes `/veille/*` existantes de `briques/atelier-veille/main.py` : `try/except Exception` autour de l'appel réseau → 502 avec le nom du service et l'URL ; `if r.status_code >= 400` → relai du code + `detail` upstream si présent.
- Français partout (noms de fonctions, messages d'erreur, commentaires), cohérent avec le reste du dépôt.

## File Structure

**`briques/veille-prospection/`** (existant, modifié) :
- `stockage.py` — colonne `zone_nom`, fonction `lire_campagne`
- `orchestration.py` — `avertissement_type_zone` accepte une zone pré-résolue, `_appeler_forge` tague les notes, `_executer_campagne` renommée `executer_campagne_unique` (publique)
- `main.py` — résolution de `zone_nom` à la création, routes `POST /campagnes/{id}/executer` et `GET /campagnes/{id}/executions`
- `test_stockage.py`, `test_orchestration.py`, `test_main.py` — étendus

**`briques/atelier-veille/`** (existant, modifié) :
- `main.py` — 4 nouvelles URLs de service, 7 nouvelles routes `/prospection/*`
- `front.html` — 4ᵉ onglet, sections campagnes/prospects/démarchage
- `docker-compose.yml` — 4 nouvelles variables d'environnement
- `test_front.py` — étendu
- **`test_prospection.py` (NOUVEAU)** — regroupe tous les tests des routes `/prospection/*` (composition veille-prospection/geo/forge/mail). Fichier séparé plutôt que d'alourdir `test_composition.py` (déjà 450+ lignes, dédié à la composition `veille-info`) : cette fonctionnalité forme un tout cohérent, plus simple à relire groupée.

---

### Task 1: `veille-prospection` — stockage : colonne `zone_nom` + `lire_campagne`

**Files:**
- Modify: `briques/veille-prospection/stockage.py`
- Test: `briques/veille-prospection/test_stockage.py`

**Interfaces:**
- Produces: `creer_campagne(user_id: str, zone_id: str, type_: str = "b2b", zone_nom: str | None = None) -> dict` (le dict retourné inclut désormais `"zone_nom"`) ; `lire_campagne(user_id: str, campagne_id: int) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `briques/veille-prospection/test_stockage.py` :

```python
def test_creer_campagne_stocke_zone_nom():
    c = stockage.creer_campagne("zn-alice", "zone-1", zone_nom="Restos Castres")
    assert c["zone_nom"] == "Restos Castres"
    relue = stockage.lister_campagnes("zn-alice")[0]
    assert relue["zone_nom"] == "Restos Castres"


def test_creer_campagne_zone_nom_optionnel():
    c = stockage.creer_campagne("zn-bob", "zone-2")
    assert c["zone_nom"] is None


def test_lire_campagne_isole_par_user_id():
    c = stockage.creer_campagne("zn-carol", "zone-3")
    assert stockage.lire_campagne("zn-carol", c["id"]) == c
    assert stockage.lire_campagne("zn-mallory", c["id"]) is None


def test_lire_campagne_introuvable_rend_none():
    assert stockage.lire_campagne("zn-dave", 999999) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/veille-prospection && python -m pytest test_stockage.py -k "zone_nom or lire_campagne" -v`
Expected: FAIL — `TypeError: creer_campagne() got an unexpected keyword argument 'zone_nom'` (et `AttributeError: module 'stockage' has no attribute 'lire_campagne'`)

- [ ] **Step 3: Implement**

Dans `briques/veille-prospection/stockage.py` :

Dans `_SCHEMA` `init()`, ajouter une migration additive à côté de celle de `type` :

```python
def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)
        for alter in ("ALTER TABLE campagnes ADD COLUMN type TEXT NOT NULL DEFAULT 'b2b'",
                      "ALTER TABLE campagnes ADD COLUMN zone_nom TEXT"):
            try:
                c.execute(alter)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente
```

Modifier `_campagne_dict` :

```python
def _campagne_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "zone_id": r["zone_id"],
            "type": r["type"], "zone_nom": r["zone_nom"], "actif": bool(r["actif"]),
            "derniere_execution": r["derniere_execution"], "created_at": r["created_at"]}
```

Modifier `creer_campagne` :

```python
def creer_campagne(user_id: str, zone_id: str, type_: str = "b2b",
                   zone_nom: str | None = None) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO campagnes (user_id, zone_id, type, zone_nom, actif, created_at) "
            "VALUES (?,?,?,?,1,?)",
            (user_id, zone_id, type_, zone_nom, _maintenant()))
        row = c.execute("SELECT * FROM campagnes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _campagne_dict(row)
```

Ajouter, après `supprimer_campagne` :

```python
def lire_campagne(user_id: str, campagne_id: int) -> dict | None:
    """Une campagne précise, scopée au tenant — active ou non (contrairement à
    `lister_campagnes(actives_seulement=True)`, utile pour un 404 honnête plutôt qu'un
    faux « introuvable » sur une campagne juste désactivée)."""
    with _conn() as c:
        row = c.execute("SELECT * FROM campagnes WHERE id = ? AND user_id = ?",
                        (campagne_id, user_id)).fetchone()
    return _campagne_dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/veille-prospection && python -m pytest test_stockage.py -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/stockage.py briques/veille-prospection/test_stockage.py
git commit -m "$(cat <<'EOF'
feat(veille-prospection): stocke le nom de zone sur chaque campagne

Colonne zone_nom (migration additive) + lire_campagne(user_id, id) —
prépare le tag des prospects CRM par campagne et la route d'exécution
manuelle scopée tenant (tâches suivantes).
EOF
)"
```

---

### Task 2: `veille-prospection` — orchestration : zone pré-résolue + tag des notes CRM

**Files:**
- Modify: `briques/veille-prospection/orchestration.py`
- Test: `briques/veille-prospection/test_orchestration.py`

**Interfaces:**
- Consumes: rien de nouveau (Task 1 non requise pour ce fichier isolément, mais le renommage `executer_campagne_unique` sera consommé par `main.py` en Task 4)
- Produces: `avertissement_type_zone(zone_id: str, type_campagne: str, zone: dict | None = None) -> str | None` (signature étendue, rétrocompatible) ; `_appeler_forge(prospects: list[dict], zone_nom: str | None = None) -> dict` ; `executer_campagne_unique(campagne: dict) -> dict` (renommage public de `_executer_campagne`, même comportement)

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `briques/veille-prospection/test_orchestration.py` :

```python
def test_avertissement_type_zone_accepte_zone_prefetchee(monkeypatch):
    """Si `zone` est fournie, la fonction ne doit PAS rappeler `geo` — évite un 2e appel
    réseau quand l'appelant (main.py) a déjà résolu la zone une fois."""
    def _casse(*a, **k):
        raise AssertionError("httpx.get ne doit pas être appelé quand zone= est fournie")
    monkeypatch.setattr(orchestration.httpx, "get", _casse)
    zone = {"id": "z1", "nom": "Entreprises Castres", "type": "entreprise"}
    a = orchestration.avertissement_type_zone("z1", "b2c", zone=zone)
    assert a and "logement" in a


def test_appeler_forge_tague_zone_dans_notes(monkeypatch):
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/crm/import-lot")
        captes["json"] = json
        return _Rep(200, {"crees": 1})

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration._appeler_forge([{"nom": "Chez Paul"}], zone_nom="Restos Castres")
    assert captes["json"]["prospects"][0]["notes"] == "Zone : Restos Castres"


def test_appeler_forge_conserve_notes_existantes_du_prospect(monkeypatch):
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        captes["json"] = json
        return _Rep(200, {"crees": 1})

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration._appeler_forge([{"nom": "Chez Paul", "notes": "Dirigeant : P. Martin"}],
                                 zone_nom="Restos Castres")
    assert captes["json"]["prospects"][0]["notes"] == \
        "Dirigeant : P. Martin · Zone : Restos Castres"


def test_appeler_forge_sans_zone_nom_ninjecte_rien(monkeypatch):
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        captes["json"] = json
        return _Rep(200, {"crees": 1})

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration._appeler_forge([{"nom": "Chez Paul"}])
    assert "notes" not in captes["json"]["prospects"][0]


def test_executer_campagne_unique_existe_et_retourne_le_decompte(monkeypatch):
    """Renommage public de l'ancienne `_executer_campagne` — même comportement, exposé
    pour la route d'exécution manuelle (main.py, tâche suivante)."""
    c = stockage.creer_campagne("orch-hugo", "zone-hugo")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagne_unique(c)
    assert resultat == {"trouves": 1, "deja_connus": 0, "nouveaux_crm": 1, "erreur": None}


def test_zone_nom_de_la_campagne_est_propage_aux_notes_crm(monkeypatch):
    """Bout en bout : une campagne créée AVEC zone_nom tague bien les prospects envoyés
    à forge lors de l'exécution (pas seulement `_appeler_forge` testée isolément)."""
    c = stockage.creer_campagne("orch-iris", "zone-iris", zone_nom="Restos Castres")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "Chez Paul"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            captes["json"] = json
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration.executer_campagnes(user_ids=["orch-iris"])
    assert captes["json"]["prospects"][0]["notes"] == "Zone : Restos Castres"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/veille-prospection && python -m pytest test_orchestration.py -k "zone_nom or prefetchee or executer_campagne_unique or tague" -v`
Expected: FAIL — `AttributeError: module 'orchestration' has no attribute 'executer_campagne_unique'`, `TypeError: avertissement_type_zone() got an unexpected keyword argument 'zone'`, notes absentes du JSON capté.

- [ ] **Step 3: Implement**

Dans `briques/veille-prospection/orchestration.py`, remplacer `avertissement_type_zone` :

```python
def avertissement_type_zone(zone_id: str, type_campagne: str, zone: dict | None = None) -> str | None:
    """Best-effort : prévient si la zone référencée ne correspond visiblement pas au
    type de campagne déclaré (b2c attend une zone `logement`, b2b attend le contraire).
    Ne bloque JAMAIS la création d'une campagne — `geo` injoignable ou zone inconnue
    d'ici = silence, pas une erreur.

    `zone`, si fournie, évite un second appel réseau : l'appelant (main.py) a déjà
    résolu la zone pour calculer `zone_nom` — inutile de la relire ici."""
    try:
        if zone is None:
            zone = lire_zone_geo(zone_id)
        if zone is None:
            return None
        est_logement = zone.get("type") == "logement"
        if type_campagne == "b2c" and not est_logement:
            return (f"La zone « {zone['nom']} » est de type « {zone.get('type')} », pas "
                    "« logement » — cette campagne b2c risque de ne rien trouver.")
        if type_campagne == "b2b" and est_logement:
            return (f"La zone « {zone['nom']} » est de type « logement » — cette "
                    "campagne b2b risque de ne rien trouver.")
        return None
    except Exception:  # noqa: BLE001 — best-effort strict, jamais bloquant
        return None
```

Remplacer `_appeler_forge` :

```python
def _appeler_forge(prospects: list[dict], zone_nom: str | None = None) -> dict:
    """`zone_nom`, si fourni, tague chaque prospect (`notes`) avec `f"Zone : {zone_nom}"`
    — seule façon de retrouver « les prospects de CETTE campagne » côté CRM plus tard
    (Forge n'a pas de colonne zone_id/campagne_id, cf. spec 2026-08-19). Les notes déjà
    présentes sur le prospect (aucune source actuelle n'en pose, mais robuste si un jour
    `geo` en ajoute) sont conservées, pas écrasées."""
    if zone_nom:
        tag = f"Zone : {zone_nom}"
        for p in prospects:
            existantes = (p.get("notes") or "").strip()
            p["notes"] = f"{existantes} · {tag}" if existantes else tag
    base = _url("FORGE_URL", "http://host.docker.internal:5700")
    r = httpx.post(f"{base}/crm/import-lot", json={"prospects": prospects},
                   headers=_entetes("FORGE_KEY"), timeout=60)
    r.raise_for_status()
    return r.json()
```

Renommer `_executer_campagne` en `executer_campagne_unique` (retirer le préfixe `_`, garder le corps identique) et changer son appel interne à `_appeler_forge` :

```python
def executer_campagne_unique(campagne: dict) -> dict:
    """Exécute UNE campagne. Ne lève jamais : les erreurs sont journalisées dans le
    décompte renvoyé, jamais propagées à l'appelant. Publique (pas de `_`) : utilisée par
    le passage horloge (`_executer_campagne_sans_planter`) ET par la route d'exécution
    manuelle scopée tenant (`main.py`, POST /campagnes/{id}/executer)."""
    try:
        rapport_geo = _appeler_geo(campagne["zone_id"])
    except httpx.HTTPError as e:
        return {"trouves": 0, "deja_connus": 0, "nouveaux_crm": 0, "erreur": str(e)}

    prospects = rapport_geo.get("prospects", [])
    deja_connus = rapport_geo.get("compte", {}).get("deja_enrichi", 0)
    nouveaux_crm, erreur = 0, None
    if prospects:
        try:
            rapport_forge = _appeler_forge(prospects, campagne.get("zone_nom"))
            nouveaux_crm = rapport_forge.get("crees", 0)
        except httpx.HTTPError as e:
            erreur = str(e)
        _pousser_memoire(
            campagne["user_id"],
            f"Campagne de prospection : {len(prospects)} prospect(s) trouvé(s), "
            f"{nouveaux_crm} nouveau(x) au CRM ({deja_connus} déjà connu(s)).")

    return {"trouves": len(prospects), "deja_connus": deja_connus,
            "nouveaux_crm": nouveaux_crm, "erreur": erreur}
```

Mettre à jour son unique appelant, `_executer_campagne_sans_planter` :

```python
def _executer_campagne_sans_planter(campagne: dict) -> bool:
    try:
        resultat = executer_campagne_unique(campagne)
        stockage.inserer_execution(campagne["id"], **resultat)
        stockage.maj_derniere_execution(campagne["id"])
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Veille-prospection échec inattendu (campagne_id=%s, user_id=%s) : %s",
                       campagne["id"], campagne.get("user_id"), e)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/veille-prospection && python -m pytest test_orchestration.py -v`
Expected: PASS (tous les tests, anciens et nouveaux — en particulier tous les
`test_avertissement_type_zone_*` existants, appelés avec 2 arguments positionnels
seulement, doivent rester verts inchangés)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/orchestration.py briques/veille-prospection/test_orchestration.py
git commit -m "$(cat <<'EOF'
feat(veille-prospection): tague les prospects CRM avec le nom de la zone

_appeler_forge ajoute "Zone : <nom>" aux notes de chaque prospect quand
la campagne porte un zone_nom — seul moyen de retrouver "les prospects
de cette campagne" côté Forge sans toucher à son schéma. Renomme aussi
_executer_campagne en executer_campagne_unique (publique), réutilisée
par la future route d'exécution manuelle.
EOF
)"
```

---

### Task 3: `veille-prospection` — route de création résout `zone_nom`

**Files:**
- Modify: `briques/veille-prospection/main.py`
- Test: `briques/veille-prospection/test_main.py`

**Interfaces:**
- Consumes: `stockage.creer_campagne(..., zone_nom=...)` (Task 1), `orchestration.avertissement_type_zone(zone_id, type_, zone=...)` (Task 2), `orchestration.lire_zone_geo(zone_id)` (existant)
- Produces: `creer_campagne_route` renvoie désormais `zone_nom` dans son JSON (déjà exposé par `_campagne_dict`, Task 1 — cette tâche le PEUPLE réellement)

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `briques/veille-prospection/test_main.py` :

```python
def test_creer_campagne_resout_zone_nom_via_geo(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo",
                        lambda zone_id: {"id": zone_id, "nom": "Restos Castres", "type": "entreprise"})
    r = client.post("/campagnes", headers=_entetes("main-henri"),
                    json={"zone_id": "zone-castres"})
    assert r.status_code == 201
    assert r.json()["zone_nom"] == "Restos Castres"


def test_creer_campagne_zone_nom_none_si_geo_injoignable(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    def _casse(zone_id):
        raise Exception("geo down")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", _casse)
    r = client.post("/campagnes", headers=_entetes("main-ines"),
                    json={"zone_id": "zone-hs"})
    assert r.status_code == 201
    assert r.json()["zone_nom"] is None


def test_creer_campagne_resout_zone_nom_une_seule_fois(monkeypatch):
    """`lire_zone_geo` ne doit être appelée qu'UNE fois par création — le résultat est
    réutilisé pour l'avertissement de cohérence type/zone (pas de 2e appel réseau)."""
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    appels = {"n": 0}
    def _compte(zone_id):
        appels["n"] += 1
        return {"id": zone_id, "nom": "Logements Castres", "type": "logement"}
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", _compte)
    r = client.post("/campagnes", headers=_entetes("main-jules"),
                    json={"zone_id": "zone-logements", "type": "b2b"})
    assert r.status_code == 201
    assert appels["n"] == 1
    assert "avertissement" in r.json()  # b2b sur zone logement → incohérence signalée
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/veille-prospection && python -m pytest test_main.py -k "zone_nom" -v`
Expected: FAIL — `r.json()["zone_nom"]` vaut toujours `None` (jamais peuplé), le test du
« une seule fois » échoue avec `appels["n"] == 2`.

- [ ] **Step 3: Implement**

Dans `briques/veille-prospection/main.py`, ajouter avant `creer_campagne_route` :

```python
def _resoudre_zone_best_effort(zone_id: str) -> dict | None:
    """Résout la zone `geo` une seule fois pour la création d'une campagne — best-effort
    strict (jamais d'erreur remontée à l'appelant), le résultat est réutilisé à la fois
    pour `zone_nom` et pour `avertissement_type_zone` (évite un 2e appel réseau)."""
    try:
        return orchestration.lire_zone_geo(zone_id)
    except Exception:  # noqa: BLE001
        return None
```

Remplacer `creer_campagne_route` :

```python
@app.post("/campagnes", tags=["campagnes"], status_code=201)
def creer_campagne_route(body: CreerCampagne, tenant: str = Depends(tenant_actuel)):
    type_ = body.type.strip().lower()
    if type_ not in ("b2b", "b2c"):
        raise HTTPException(422, "« type » doit être « b2b » ou « b2c ».")
    zone = _resoudre_zone_best_effort(body.zone_id)
    zone_nom = zone.get("nom") if zone else None
    campagne = stockage.creer_campagne(tenant, body.zone_id, type_=type_, zone_nom=zone_nom)
    avertissement = orchestration.avertissement_type_zone(body.zone_id, type_, zone=zone)
    if avertissement:
        campagne["avertissement"] = avertissement
    return campagne
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/veille-prospection && python -m pytest test_main.py -v`
Expected: PASS (tous les tests, y compris les tests existants `test_creer_campagne_type_b2c`
etc. qui monkeypatchent `main.orchestration.httpx.get` pour lever une exception — cette
exception remonte maintenant depuis `_resoudre_zone_best_effort` ET potentiellement depuis
`avertissement_type_zone` si `zone` est resté `None`, les deux best-effort, toujours 201)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/main.py briques/veille-prospection/test_main.py
git commit -m "$(cat <<'EOF'
feat(veille-prospection): peuple zone_nom à la création d'une campagne

Un seul appel à geo (lire_zone_geo), réutilisé pour zone_nom ET pour
l'avertissement de cohérence type/zone déjà existant. Best-effort :
geo injoignable ou zone introuvable → zone_nom=None, jamais d'erreur.
EOF
)"
```

---

### Task 4: `veille-prospection` — exécution manuelle d'une campagne + historique

**Files:**
- Modify: `briques/veille-prospection/main.py`
- Test: `briques/veille-prospection/test_main.py`

**Interfaces:**
- Consumes: `stockage.lire_campagne` (Task 1), `orchestration.executer_campagne_unique` (Task 2), `stockage.inserer_execution`/`maj_derniere_execution`/`lister_executions` (existants)
- Produces: `POST /campagnes/{campagne_id}/executer` → `{trouves, deja_connus, nouveaux_crm, erreur}` ; `GET /campagnes/{campagne_id}/executions` → `list[dict]`

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `briques/veille-prospection/test_main.py` :

```python
def test_executer_campagne_id_404_si_autre_tenant(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-karim"),
                    json={"zone_id": "zone-karim"})
    campagne_id = r.json()["id"]
    r = client.post(f"/campagnes/{campagne_id}/executer", headers=_entetes("main-laura"))
    assert r.status_code == 404


def test_executer_campagne_id_404_si_inactive(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-mona"),
                    json={"zone_id": "zone-mona"})
    campagne_id = r.json()["id"]
    client.delete(f"/campagnes/{campagne_id}", headers=_entetes("main-mona"))
    r = client.post(f"/campagnes/{campagne_id}/executer", headers=_entetes("main-mona"))
    assert r.status_code == 404


def test_executer_campagne_id_retourne_le_resultat_et_persiste(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-nadia"),
                    json={"zone_id": "zone-nadia"})
    campagne_id = r.json()["id"]

    appele_avec = {}
    def _faux_executer(campagne):
        appele_avec["id"] = campagne["id"]
        return {"trouves": 5, "deja_connus": 2, "nouveaux_crm": 3, "erreur": None}
    monkeypatch.setattr(main.orchestration, "executer_campagne_unique", _faux_executer)

    r = client.post(f"/campagnes/{campagne_id}/executer", headers=_entetes("main-nadia"))
    assert r.status_code == 200
    assert r.json() == {"trouves": 5, "deja_connus": 2, "nouveaux_crm": 3, "erreur": None}
    assert appele_avec["id"] == campagne_id

    r = client.get(f"/campagnes/{campagne_id}/executions", headers=_entetes("main-nadia"))
    assert len(r.json()) == 1
    assert r.json()[0]["trouves"] == 5

    r = client.get("/campagnes", headers=_entetes("main-nadia"))
    assert r.json()[0]["derniere_execution"] is not None


def test_lister_executions_404_si_autre_tenant(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-oscar"),
                    json={"zone_id": "zone-oscar"})
    campagne_id = r.json()["id"]
    r = client.get(f"/campagnes/{campagne_id}/executions", headers=_entetes("main-paula"))
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/veille-prospection && python -m pytest test_main.py -k "executer_campagne_id or lister_executions" -v`
Expected: FAIL — 404 Not Found sur `/campagnes/{id}/executer` et `/campagnes/{id}/executions` (routes inexistantes)

- [ ] **Step 3: Implement**

Dans `briques/veille-prospection/main.py`, ajouter après `supprimer_campagne_route` :

```python
@app.post("/campagnes/{campagne_id}/executer", tags=["campagnes"])
def executer_campagne_id_route(campagne_id: int, tenant: str = Depends(tenant_actuel)):
    """Lance UNE campagne, tout de suite, scopée au tenant appelant — contrairement à
    POST /campagnes/executer (jeton horloge, traite tout le monde). Synchrone : peut
    prendre jusqu'à ~180 s (timeout de l'appel `geo` sous-jacent, lectures web réelles)."""
    campagne = stockage.lire_campagne(tenant, campagne_id)
    if not campagne or not campagne["actif"]:
        raise HTTPException(404, "Campagne introuvable ou inactive.")
    resultat = orchestration.executer_campagne_unique(campagne)
    stockage.inserer_execution(campagne_id, **resultat)
    stockage.maj_derniere_execution(campagne_id)
    return resultat


@app.get("/campagnes/{campagne_id}/executions", tags=["campagnes"])
def lister_executions_route(campagne_id: int, tenant: str = Depends(tenant_actuel)):
    campagne = stockage.lire_campagne(tenant, campagne_id)
    if not campagne:
        raise HTTPException(404, "Campagne introuvable.")
    return stockage.lister_executions(campagne_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/veille-prospection && python -m pytest test_main.py test_stockage.py test_orchestration.py -v`
Expected: PASS (suite complète de la brique, aucune régression)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/main.py briques/veille-prospection/test_main.py
git commit -m "$(cat <<'EOF'
feat(veille-prospection): route d'exécution manuelle scopée tenant

POST /campagnes/{id}/executer lance UNE campagne tout de suite (pas le
jeton horloge global) ; GET /campagnes/{id}/executions expose enfin
l'historique déjà journalisé. Les deux 404 proprement sur une campagne
d'un autre tenant.
EOF
)"
```

---

### Task 5: `atelier-veille` — proxy campagnes (CRUD + exécution) et zones geo

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Modify: `briques/atelier-veille/docker-compose.yml`
- Test: `briques/atelier-veille/test_prospection.py` (NOUVEAU)

**Interfaces:**
- Produces: `GET/POST /prospection/campagnes`, `DELETE /prospection/campagnes/{id}`,
  `POST /prospection/campagnes/{id}/executer`, `GET /prospection/zones` — tous proxy
  purs, motif identique aux routes `/veille/*` existantes.

- [ ] **Step 1: Write the failing tests**

Créer `briques/atelier-veille/test_prospection.py` :

```python
"""Tests — composition de veille-prospection/geo/forge/mail par l'atelier-veille (onglet
Prospection, S193). Fichier séparé de test_composition.py (dédié à veille-info) : cette
fonctionnalité forme un tout cohérent, plus simple à relire groupée — motif déjà appliqué
par test_front.py/test_main.py/test_composition.py qui se partagent le fichier par rôle."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False):
    """Motif identique à test_composition.py::_client_json — un seul endpoint mocké."""
    class FauxRep:
        status_code = status
        def json(self):
            return rep_json

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("GET", url, headers)
            return FauxRep()
        async def post(self, url, headers=None, json=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("POST", url, headers, json)
            return FauxRep()
        async def delete(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("DELETE", url, headers)
            return FauxRep()
    return FauxClient


def test_lister_campagnes_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(
        [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]))
    r = client.get("/prospection/campagnes")
    assert r.status_code == 200
    assert r.json()[0]["zone_nom"] == "Restos Castres"


def test_lister_campagnes_prospection_relaie_lidentite(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/prospection/campagnes", headers={"X-User-Id": "claire", "X-API-Key": "k"})
    _, url, headers = Faux.dernier_appel
    assert url == f"{M.VEILLE_PROSPECTION_URL}/campagnes"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "k"}


def test_creer_campagne_prospection_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 2, "zone_id": "z2", "type": "b2b", "zone_nom": None}, status=201)
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/campagnes", json={"zone_id": "z2"})
    assert r.status_code == 201
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"zone_id": "z2", "type": "b2b"}


def test_supprimer_campagne_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({"ok": True}))
    r = client.delete("/prospection/campagnes/2")
    assert r.status_code == 200


def test_supprimer_campagne_prospection_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Campagne introuvable ou inactive."}, status=404))
    r = client.delete("/prospection/campagnes/999")
    assert r.status_code == 404


def test_executer_campagne_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(
        {"trouves": 3, "deja_connus": 1, "nouveaux_crm": 2, "erreur": None}))
    r = client.post("/prospection/campagnes/1/executer")
    assert r.status_code == 200
    assert r.json()["trouves"] == 3


def test_executer_campagne_prospection_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Campagne introuvable ou inactive."}, status=404))
    r = client.post("/prospection/campagnes/999/executer")
    assert r.status_code == 404


def test_executer_campagne_prospection_injoignable_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.post("/prospection/campagnes/1/executer")
    assert r.status_code == 502
    assert "veille-prospection" in r.json()["detail"]


def test_lister_zones_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(
        {"zones": [{"id": "z1", "nom": "Restos Castres", "type": "entreprise"}]}))
    r = client.get("/prospection/zones")
    assert r.status_code == 200
    assert r.json()["zones"][0]["nom"] == "Restos Castres"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/atelier-veille && python -m pytest test_prospection.py -v`
Expected: FAIL — 404 Not Found sur toutes les routes `/prospection/*` (inexistantes),
`AttributeError: module 'main' has no attribute 'VEILLE_PROSPECTION_URL'`

- [ ] **Step 3: Implement**

Dans `briques/atelier-veille/main.py`, ajouter après `VEILLE_INFO_URL` :

```python
VEILLE_PROSPECTION_URL = os.getenv("VEILLE_PROSPECTION_URL", "http://host.docker.internal:6140")
GEO_URL = os.getenv("GEO_URL", "http://host.docker.internal:6110")
```

Ajouter, après `class GenererAudioGlobal` (avant les routes `/veille/*`) :

```python
class CreerCampagneProspection(BaseModel):
    zone_id: str = Field(min_length=1)
    type: str = "b2b"
```

Ajouter les routes, après `executer_digest` (fin du fichier) :

```python
@app.get("/prospection/campagnes", tags=["prospection"])
async def lister_campagnes_prospection(x_user_id: Optional[str] = Header(None),
                                       x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_PROSPECTION_URL}/campagnes", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return corps


@app.post("/prospection/campagnes", tags=["prospection"], status_code=201)
async def creer_campagne_prospection(body: CreerCampagneProspection,
                                     x_user_id: Optional[str] = Header(None),
                                     x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{VEILLE_PROSPECTION_URL}/campagnes", headers=entetes,
                             json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return JSONResponse(content=corps, status_code=r.status_code)


@app.delete("/prospection/campagnes/{campagne_id}", tags=["prospection"])
async def supprimer_campagne_prospection(campagne_id: int,
                                         x_user_id: Optional[str] = Header(None),
                                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{VEILLE_PROSPECTION_URL}/campagnes/{campagne_id}", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Campagne introuvable.")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return corps


@app.post("/prospection/campagnes/{campagne_id}/executer", tags=["prospection"])
async def executer_campagne_prospection(campagne_id: int,
                                        x_user_id: Optional[str] = Header(None),
                                        x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        # 200s (pas 30) : l'appel geo sous-jacent (enrichir-lot) peut prendre jusqu'à 180s.
        async with httpx.AsyncClient(timeout=200) as c:
            r = await c.post(f"{VEILLE_PROSPECTION_URL}/campagnes/{campagne_id}/executer",
                             headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Campagne introuvable ou inactive.")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return corps


@app.get("/prospection/zones", tags=["prospection"])
async def lister_zones_prospection(x_user_id: Optional[str] = Header(None),
                                   x_api_key: Optional[str] = Header(None)):
    """Peuple le sélecteur de zone du formulaire de création de campagne — proxy vers
    `geo GET /zones` (jamais dupliqué, geo reste la seule source de vérité des zones)."""
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{GEO_URL}/zones", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"geo injoignable ({GEO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"geo a refusé la requête ({r.status_code}).")
    return corps
```

Dans `briques/atelier-veille/docker-compose.yml`, dans le bloc `environment:`, ajouter après la
ligne `VEILLE_INFO_URL` :

```yaml
      - VEILLE_INFO_URL=http://host.docker.internal:6120
      - VEILLE_PROSPECTION_URL=http://host.docker.internal:6140
      - GEO_URL=http://host.docker.internal:6110
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/atelier-veille && python -m pytest test_prospection.py -v`
Expected: PASS (tous les tests)

Run: `cd briques/atelier-veille && python -m pytest -v`
Expected: PASS (suite complète, aucune régression sur les onglets existants)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/docker-compose.yml \
       briques/atelier-veille/test_prospection.py
git commit -m "$(cat <<'EOF'
feat(atelier-veille): proxy campagnes de prospection + zones geo

Routes /prospection/campagnes (GET/POST/DELETE), /prospection/campagnes/
{id}/executer et /prospection/zones — motif proxy identique aux routes
/veille/* existantes (pass-through identité, 502 propre si injoignable).
EOF
)"
```

---

### Task 6: `atelier-veille` — liste des prospects filtrée par campagne

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Test: `briques/atelier-veille/test_prospection.py`

**Interfaces:**
- Consumes: `VEILLE_PROSPECTION_URL` (Task 5)
- Produces: `FORGE_URL` (nouvelle constante), `GET /prospection/prospects?campagne_id=<int>` →
  `{"campagne_id": int, "zone_nom": str | None, "prospects": list[dict]}`

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/atelier-veille/test_prospection.py`, après le helper `_client_json` :

```python
def _client_multi(reponses, boom_pour=None):
    """reponses : {suffixe_url: (status, json)}. boom_pour : liste de suffixes qui lèvent
    une exception réseau au lieu de répondre — sert à PROUVER qu'une route n'a pas été
    appelée (si elle l'était, le test échouerait avec un 502, pas silencieusement)."""
    class FauxRep:
        def __init__(self, status, corps):
            self.status_code, self._corps = status, corps
        def json(self):
            return self._corps

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k):
            for suffixe in (boom_pour or []):
                if url.endswith(suffixe):
                    raise RuntimeError("connection refused")
            for suffixe, (status, corps) in reponses.items():
                if url.endswith(suffixe):
                    return FauxRep(status, corps)
            raise AssertionError(f"URL non mockée : {url}")
        async def post(self, url, headers=None, json=None, **k):
            for suffixe in (boom_pour or []):
                if url.endswith(suffixe):
                    raise RuntimeError("connection refused")
            for suffixe, (status, corps) in reponses.items():
                if url.endswith(suffixe):
                    FauxClient.dernier_appel = ("POST", url, headers, json)
                    return FauxRep(status, corps)
            raise AssertionError(f"URL non mockée : {url}")
    return FauxClient


def test_prospects_campagne_filtre_par_zone_nom(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr",
             "notes": "NAF : 56.10A · Commune : Castres · Zone : Restos Castres"},
            {"id": "b", "nom": "Salon B", "email": "x@b.fr", "notes": "Zone : Coiffeurs Castres"},
        ]}),
    }))
    r = client.get("/prospection/prospects?campagne_id=1")
    assert r.status_code == 200
    data = r.json()
    assert data["zone_nom"] == "Restos Castres"
    assert [p["id"] for p in data["prospects"]] == ["a"]


def test_prospects_campagne_introuvable_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_multi({"/campagnes": (200, [])}))
    r = client.get("/prospection/prospects?campagne_id=999")
    assert r.status_code == 404


def test_prospects_campagne_sans_zone_nom_rend_liste_vide_sans_appeler_forge(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 2, "zone_id": "z2", "zone_nom": None, "type": "b2b"}]),
    }, boom_pour=["/crm"])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/prospection/prospects?campagne_id=2")
    assert r.status_code == 200
    assert r.json() == {"campagne_id": 2, "zone_nom": None, "prospects": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/atelier-veille && python -m pytest test_prospection.py -k prospects_campagne -v`
Expected: FAIL — 404 Not Found sur `/prospection/prospects` (route inexistante)

- [ ] **Step 3: Implement**

Dans `briques/atelier-veille/main.py`, ajouter après `GEO_URL` :

```python
FORGE_URL = os.getenv("FORGE_URL", "http://host.docker.internal:5700")
```

Ajouter, après la route `lister_zones_prospection` :

```python
async def _get_json_ou_erreur(url: str, service: str) -> dict | list:
    """Petit helper local aux routes `/prospection/*` qui chaînent 2 appels amont — les
    routes `/veille/*` existantes n'en ont pas besoin (un seul appel chacune)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{service} injoignable ({url}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"{service} a refusé la requête ({r.status_code}).")
    return corps


@app.get("/prospection/prospects", tags=["prospection"])
async def prospects_campagne(campagne_id: int):
    """Prospects CRM rattachables à cette campagne — filtrés par le tag `"Zone : <nom>"`
    posé dans les notes à l'export (cf. veille-prospection orchestration.py, Task 2).
    Limite ASSUMÉE (spec 2026-08-19) : un filtrage texte, pas une vraie clé étrangère —
    si `zone_nom` est `None` (jamais résolu à la création), on renvoie une liste VIDE
    plutôt que tout le CRM (mieux vaut rien qu'une vue trompeuse)."""
    campagnes = await _get_json_ou_erreur(f"{VEILLE_PROSPECTION_URL}/campagnes",
                                          "veille-prospection")
    campagne = next((c for c in campagnes if c["id"] == campagne_id), None)
    if campagne is None:
        raise HTTPException(404, "Campagne introuvable.")
    zone_nom = campagne.get("zone_nom")
    if not zone_nom:
        return {"campagne_id": campagne_id, "zone_nom": None, "prospects": []}
    crm = await _get_json_ou_erreur(f"{FORGE_URL}/crm", "forge")
    tag = f"Zone : {zone_nom}"
    prospects = [p for p in crm.get("prospects", []) if tag in (p.get("notes") or "")]
    return {"campagne_id": campagne_id, "zone_nom": zone_nom, "prospects": prospects}
```

Dans `briques/atelier-veille/docker-compose.yml`, ajouter après `GEO_URL` :

```yaml
      - FORGE_URL=http://host.docker.internal:5700
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/atelier-veille && python -m pytest test_prospection.py -v`
Expected: PASS (tous les tests, y compris ceux de la Task 5)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/docker-compose.yml \
       briques/atelier-veille/test_prospection.py
git commit -m "$(cat <<'EOF'
feat(atelier-veille): liste des prospects filtrée par campagne

GET /prospection/prospects?campagne_id= croise veille-prospection (nom
de zone) et forge (CRM), filtre par le tag posé dans les notes. Zone
non résolue → liste vide plutôt que tout le CRM (pas de vue trompeuse).
EOF
)"
```

---

### Task 7: `atelier-veille` — préparation du démarchage depuis la sélection

**Files:**
- Modify: `briques/atelier-veille/main.py`
- Test: `briques/atelier-veille/test_prospection.py`

**Interfaces:**
- Consumes: `_get_json_ou_erreur`, `VEILLE_PROSPECTION_URL`, `FORGE_URL` (Task 6)
- Produces: `MAIL_URL` (nouvelle constante), `POST /prospection/demarchage` →
  proxy vers `mail POST /demarchage/preparer`

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/atelier-veille/test_prospection.py` :

```python
def test_preparer_demarchage_extrait_ville_et_filtre_par_campagne(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "entreprise": "Chez Paul SARL", "email": "p@a.fr",
             "notes": "NAF : 56.10A · Commune : Castres · Zone : Restos Castres"},
        ]}),
        "/demarchage/preparer": (201, {"ok": True, "prepares": 1, "ignores": {},
                                       "message": "1 brouillon(s) préparé(s)."}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "Studio Web — 06 00 00 00 00",
        "sujet": "Bonjour {nom}", "message": "On a vu {entreprise} à {ville}."
    })
    assert r.status_code == 201
    _, _, _, corps_aval = Faux.dernier_appel
    assert corps_aval["prospects"] == [{"nom": "Chez Paul", "entreprise": "Chez Paul SARL",
                                        "email": "p@a.fr", "ville": "Castres"}]
    assert corps_aval["sujet"] == "Bonjour {nom}"
    assert corps_aval["expediteur"] == "Studio Web — 06 00 00 00 00"


def test_preparer_demarchage_ville_vide_si_absente_des_notes(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
        "/demarchage/preparer": (201, {"ok": True, "prepares": 1, "ignores": {}}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "X", "sujet": "S", "message": "M"})
    _, _, _, corps_aval = Faux.dernier_appel
    assert corps_aval["prospects"][0]["ville"] == ""


def test_preparer_demarchage_prospect_id_hors_campagne_est_ignore_422(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["id-inconnu"], "expediteur": "X",
        "sujet": "S", "message": "M"})
    assert r.status_code == 422


def test_preparer_demarchage_relaie_une_erreur_de_mail(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
        "/demarchage/preparer": (404, {"detail": "Boîte « x@y.fr » non connectée."}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "Studio Web",
        "sujet": "S", "message": "M", "compte": "x@y.fr"})
    assert r.status_code == 404
    assert "non connectée" in r.json()["detail"]


def test_preparer_demarchage_expediteur_vide_422_sans_appeler_mail(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
    }, boom_pour=["/demarchage/preparer"])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "", "sujet": "S", "message": "M"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/atelier-veille && python -m pytest test_prospection.py -k demarchage -v`
Expected: FAIL — 404 Not Found sur `/prospection/demarchage` (route inexistante)

- [ ] **Step 3: Implement**

Dans `briques/atelier-veille/main.py`, ajouter après `FORGE_URL` :

```python
MAIL_URL = os.getenv("MAIL_URL", "http://host.docker.internal:6030")
```

Ajouter en haut du fichier, avec les autres imports :

```python
import re
```

Ajouter, avec les autres modèles Pydantic :

```python
class PreparerDemarchage(BaseModel):
    campagne_id: int
    prospect_ids: list[str] = Field(min_length=1)
    expediteur: str = Field(min_length=1)
    sujet: str = Field(min_length=1)
    message: str = Field(min_length=1)
    compte: str = ""


_RE_COMMUNE = re.compile(r"Commune\s*:\s*([^·]+)")


def _ville_depuis_notes(notes: str | None) -> str:
    """Best-effort : extrait la commune du format `notes` posé par
    `briques/forge/main.py::_prospect_vers_lead` (« NAF : … · Commune : X · … »). Un
    format qui change côté Forge casse cette extraction SILENCIEUSEMENT (regex, pas un
    contrat) — acceptable : {ville} reste juste vide, jamais une erreur (cf. spec
    2026-08-19)."""
    if not notes:
        return ""
    m = _RE_COMMUNE.search(notes)
    return m.group(1).strip() if m else ""
```

Ajouter la route, après `prospects_campagne` :

```python
@app.post("/prospection/demarchage", tags=["prospection"], status_code=201)
async def preparer_demarchage(body: PreparerDemarchage):
    """Prépare des brouillons de démarchage (mail, jamais envoyés) pour la sélection de
    prospects d'UNE campagne. Les infos (nom/entreprise/email/ville) sont re-dérivées ICI
    depuis le CRM — jamais celles envoyées par le navigateur — pour que la campagne et le
    tag de zone restent la source de vérité, pas une saisie cliente."""
    campagnes = await _get_json_ou_erreur(f"{VEILLE_PROSPECTION_URL}/campagnes",
                                          "veille-prospection")
    campagne = next((c for c in campagnes if c["id"] == body.campagne_id), None)
    if campagne is None:
        raise HTTPException(404, "Campagne introuvable.")
    zone_nom = campagne.get("zone_nom")
    leads_par_id: dict = {}
    if zone_nom:
        crm = await _get_json_ou_erreur(f"{FORGE_URL}/crm", "forge")
        tag = f"Zone : {zone_nom}"
        leads_par_id = {p["id"]: p for p in crm.get("prospects", [])
                        if tag in (p.get("notes") or "")}
    prospects = [
        {"nom": leads_par_id[pid].get("nom"), "entreprise": leads_par_id[pid].get("entreprise"),
         "email": leads_par_id[pid].get("email"),
         "ville": _ville_depuis_notes(leads_par_id[pid].get("notes"))}
        for pid in body.prospect_ids if pid in leads_par_id
    ]
    if not prospects:
        raise HTTPException(422, "Aucun des prospects sélectionnés n'appartient à cette campagne.")
    corps_aval = {"prospects": prospects, "sujet": body.sujet, "message": body.message,
                 "expediteur": body.expediteur, "compte": body.compte}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{MAIL_URL}/demarchage/preparer", json=corps_aval)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"mail injoignable ({MAIL_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"mail a refusé la requête ({r.status_code}).")
    return JSONResponse(content=corps, status_code=r.status_code)
```

Dans `briques/atelier-veille/docker-compose.yml`, ajouter après `FORGE_URL` :

```yaml
      - MAIL_URL=http://host.docker.internal:6030
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/atelier-veille && python -m pytest -v`
Expected: PASS (suite complète, aucune régression)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/docker-compose.yml \
       briques/atelier-veille/test_prospection.py
git commit -m "$(cat <<'EOF'
feat(atelier-veille): préparation du démarchage depuis la sélection

POST /prospection/demarchage re-dérive nom/entreprise/email/ville
depuis le CRM (jamais depuis le navigateur) pour la sélection de
prospects d'une campagne, puis proxifie vers mail /demarchage/preparer
(brouillons uniquement, jamais d'envoi automatique).
EOF
)"
```

---

### Task 8: `atelier-veille` — front : onglet Prospection, campagnes

**Files:**
- Modify: `briques/atelier-veille/front.html`
- Test: `briques/atelier-veille/test_front.py`

**Interfaces:**
- Consumes: `GET /prospection/zones`, `GET/POST/DELETE /prospection/campagnes`,
  `POST /prospection/campagnes/{id}/executer` (Task 5)

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/atelier-veille/test_front.py` :

```python
def test_front_couvre_la_gestion_des_campagnes_prospection():
    html = client.get("/").text
    for marqueur in ("btn-prospection", "chargerCampagnesProspection", "chargerZonesProspection",
                     "creerCampagneProspection", "lancerCampagne", "desactiverCampagne",
                     "/prospection/campagnes", "/prospection/zones"):
        assert marqueur in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/atelier-veille && python -m pytest test_front.py -k prospection -v`
Expected: FAIL — aucun de ces marqueurs n'existe encore dans `front.html`

- [ ] **Step 3: Implement**

Dans `briques/atelier-veille/front.html`, ajouter le 4ᵉ bouton d'onglet après `btn-audioglobal` :

```html
    <button id="btn-audioglobal" onclick="ouvrirOnglet('audioglobal')">Audio global</button>
    <button id="btn-prospection" onclick="ouvrirOnglet('prospection')">Prospection</button>
```

Ajouter la vue, avant la fermeture de `<div class="wrap">` (après `</div>` de `vue-audioglobal`) :

```html
  <div id="vue-prospection" class="vue panel">
    <h3>Campagnes de prospection</h3>
    <p style="color:var(--mut);font-size:.82rem">Une campagne enrichit une zone existante (onglet Carte) et pousse les prospects trouvés au CRM. Rien n'est envoyé automatiquement.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <select id="select-zone-prospection" style="flex:2;min-width:200px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)"></select>
      <select id="select-type-prospection" style="padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
        <option value="b2b">Entreprises (b2b)</option>
        <option value="b2c">Logements (b2c)</option>
      </select>
      <button onclick="creerCampagneProspection()" style="padding:8px 16px;border-radius:8px;border:none;background:var(--accent);color:#0b1622;font-weight:600;cursor:pointer">Créer la campagne</button>
    </div>
    <div id="liste-campagnes-prospection" style="margin-top:16px"></div>
    <div id="erreur-prospection" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>
  </div>
```

Dans la fonction `ouvrirOnglet`, ajouter `'prospection'` à la liste et le chargement associé :

```js
function ouvrirOnglet(nom) {
  for (const n of ['carte', 'sources', 'digests', 'audioglobal', 'prospection']) {
    document.getElementById('vue-' + n).classList.toggle('actif', n === nom);
    document.getElementById('btn-' + n).classList.toggle('actif', n === nom);
  }
  if (nom === 'sources') chargerSources();
  if (nom === 'digests') { chargerDigests(); chargerThematiquesDigest(); }
  if (nom === 'audioglobal') { chargerChoixDigests(); chargerHistoriqueAudioGlobal(); }
  if (nom === 'prospection') { chargerZonesProspection(); chargerCampagnesProspection(); }
}
```

Ajouter les fonctions JS, avant la balise `</script>` finale (après `chargerHistoriqueAudioGlobal`) :

```js
async function chargerZonesProspection() {
  const select = document.getElementById('select-zone-prospection');
  try {
    const r = await fetch(`${API_BASE}/prospection/zones`);
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const zones = (await r.json()).zones || [];
    if (!zones.length) {
      select.innerHTML = '<option value="" disabled selected>Aucune zone geo — crée-en une dans l\'onglet Carte</option>';
      select.disabled = true;
      return;
    }
    select.disabled = false;
    select.innerHTML = zones.map(z => `<option value="${esc(z.id)}">${esc(z.nom)} (${esc(z.type)})</option>`).join('');
  } catch (e) {
    select.innerHTML = '<option value="" disabled selected>Erreur de chargement</option>';
    select.disabled = true;
  }
}

async function chargerCampagnesProspection() {
  const cible = document.getElementById('liste-campagnes-prospection');
  const erreur = document.getElementById('erreur-prospection');
  erreur.textContent = '';
  try {
    const r = await fetch(`${API_BASE}/prospection/campagnes`);
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const campagnes = await r.json();
    if (!campagnes.length) {
      cible.innerHTML = '<p style="color:var(--mut)">Aucune campagne de prospection active.</p>';
      return;
    }
    cible.innerHTML = campagnes.map(c => `
      <div style="padding:12px 0;border-bottom:1px solid var(--line)">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <div>
            <b>${esc(c.zone_nom || c.zone_id)}</b>
            <span style="color:var(--mut);font-size:.8rem"> · ${esc(c.type)} · ${c.derniere_execution ? 'dernière exécution : ' + esc(c.derniere_execution.slice(0, 16).replace('T', ' ')) : 'jamais exécutée'}</span>
          </div>
          <div style="display:flex;gap:6px">
            <button id="btn-lancer-${c.id}" onclick="lancerCampagne(${c.id})" style="border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:8px;padding:5px 10px;cursor:pointer">Lancer maintenant</button>
            <button onclick="desactiverCampagne(${c.id})" style="border:1px solid var(--bad);background:transparent;color:var(--bad);border-radius:8px;padding:5px 10px;cursor:pointer">Désactiver</button>
          </div>
        </div>
        ${c.avertissement ? `<p style="color:var(--bad);font-size:.8rem;margin:6px 0 0">${esc(c.avertissement)}</p>` : ''}
        <div id="resultat-lancement-${c.id}" style="font-size:.85rem;margin-top:6px"></div>
      </div>`).join('');
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function creerCampagneProspection() {
  const zoneId = document.getElementById('select-zone-prospection').value;
  const type = document.getElementById('select-type-prospection').value;
  const erreur = document.getElementById('erreur-prospection');
  erreur.textContent = '';
  if (!zoneId) { erreur.textContent = 'Choisis une zone.'; return; }
  try {
    const r = await fetch(`${API_BASE}/prospection/campagnes`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({zone_id: zoneId, type})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    await chargerCampagnesProspection();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function desactiverCampagne(id) {
  const erreur = document.getElementById('erreur-prospection');
  erreur.textContent = '';
  try {
    const r = await fetch(`${API_BASE}/prospection/campagnes/${id}`, {method: 'DELETE'});
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    await chargerCampagnesProspection();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

async function lancerCampagne(id) {
  const bouton = document.getElementById(`btn-lancer-${id}`);
  const resultat = document.getElementById(`resultat-lancement-${id}`);
  bouton.disabled = true;
  resultat.textContent = 'Lancement en cours (peut prendre jusqu\'à 3 minutes)…';
  try {
    const r = await fetch(`${API_BASE}/prospection/campagnes/${id}/executer`, {method: 'POST'});
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const res = await r.json();
    resultat.textContent = res.erreur
      ? `Erreur : ${res.erreur}`
      : `${res.trouves} trouvé(s), ${res.deja_connus} déjà connu(s), ${res.nouveaux_crm} nouveau(x) au CRM.`;
    await chargerCampagnesProspection();
  } catch (e) {
    resultat.textContent = String(e.message || e);
  } finally {
    bouton.disabled = false;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/atelier-veille && python -m pytest -v`
Expected: PASS (suite complète, aucune régression sur les 3 onglets existants)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/front.html briques/atelier-veille/test_front.py
git commit -m "$(cat <<'EOF'
feat(atelier-veille): 4e onglet Prospection — campagnes

Créer une campagne sur une zone existante, voir les campagnes actives
avec leur dernière exécution, les lancer manuellement ou les désactiver.
EOF
)"
```

---

### Task 9: `atelier-veille` — front : prospects + démarchage

**Files:**
- Modify: `briques/atelier-veille/front.html`
- Test: `briques/atelier-veille/test_front.py`

**Interfaces:**
- Consumes: `GET /prospection/prospects` (Task 6), `POST /prospection/demarchage` (Task 7)

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/atelier-veille/test_front.py` :

```python
def test_front_couvre_les_prospects_et_le_demarchage():
    html = client.get("/").text
    for marqueur in ("voirProspects", "/prospection/prospects", "preparerDemarchage",
                     "/prospection/demarchage", "toggleProspectChoisi",
                     "panneau-prospects"):
        assert marqueur in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/atelier-veille && python -m pytest test_front.py -k prospects_et_le_demarchage -v`
Expected: FAIL — aucun de ces marqueurs n'existe encore dans `front.html`

- [ ] **Step 3: Implement**

Dans `briques/atelier-veille/front.html`, dans `chargerCampagnesProspection` (Task 8), ajouter
un bouton « Voir les prospects » à côté de « Lancer maintenant » :

```html
            <button id="btn-lancer-${c.id}" onclick="lancerCampagne(${c.id})" style="border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:8px;padding:5px 10px;cursor:pointer">Lancer maintenant</button>
            <button onclick="voirProspects(${c.id})" style="border:1px solid var(--line);background:transparent;color:var(--mut);border-radius:8px;padding:5px 10px;cursor:pointer">Voir les prospects</button>
            <button onclick="desactiverCampagne(${c.id})" style="border:1px solid var(--bad);background:transparent;color:var(--bad);border-radius:8px;padding:5px 10px;cursor:pointer">Désactiver</button>
```

Dans `lancerCampagne` (Task 8), rafraîchir le panneau prospects s'il est déjà ouvert sur cette
campagne — remplacer la ligne `await chargerCampagnesProspection();` par :

```js
    await chargerCampagnesProspection();
    if (document.getElementById('panneau-prospects').dataset.campagneId == id) await voirProspects(id);
```

Ajouter le panneau, juste après `</div>` de fermeture de `vue-prospection` — non, DANS
`vue-prospection`, à la fin (avant sa fermeture), ajouter :

```html
    <div id="panneau-prospects" style="margin-top:24px" data-campagne-id="">
      <h3>Prospects</h3>
      <div id="liste-prospects"></div>
      <div id="erreur-prospects" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>

      <div id="zone-demarchage" style="display:none;margin-top:16px;padding-top:16px;border-top:1px solid var(--line)">
        <h4 style="margin:0 0 4px">Préparer le démarchage</h4>
        <p id="compte-selection-demarchage" style="color:var(--mut);font-size:.85rem;margin:0 0 10px"></p>
        <input id="demarchage-expediteur" placeholder="Identité de l'expéditeur (obligatoire — mention légale)" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink);margin-bottom:8px">
        <input id="demarchage-sujet" placeholder="Sujet — variables : {nom} {entreprise} {ville}" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink);margin-bottom:8px">
        <textarea id="demarchage-message" placeholder="Message — variables : {nom} {entreprise} {ville}" rows="5" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)"></textarea>
        <button onclick="preparerDemarchage()" style="margin-top:8px;padding:8px 16px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:600;cursor:pointer">Préparer les brouillons</button>
        <div id="resultat-demarchage" style="margin-top:8px;font-size:.85rem"></div>
      </div>
    </div>
```

Ajouter les fonctions JS, à la fin du `<script>` (après les fonctions de la Task 8) :

```js
let PROSPECTS_SELECTIONNES = new Set();

async function voirProspects(campagneId) {
  const cible = document.getElementById('liste-prospects');
  const erreur = document.getElementById('erreur-prospects');
  erreur.textContent = '';
  cible.innerHTML = 'Chargement…';
  PROSPECTS_SELECTIONNES = new Set();
  document.getElementById('panneau-prospects').dataset.campagneId = campagneId;
  try {
    const r = await fetch(`${API_BASE}/prospection/prospects?campagne_id=${campagneId}`);
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const data = await r.json();
    if (!data.prospects.length) {
      cible.innerHTML = '<p style="color:var(--mut)">Aucun prospect trouvé pour cette campagne (encore).</p>';
      majFormulaireDemarchage();
      return;
    }
    cible.innerHTML = data.prospects.map(p => `
      <label style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--line);${p.email ? '' : 'opacity:.55'}">
        <input type="checkbox" ${p.email ? '' : 'disabled'} onchange="toggleProspectChoisi('${esc(p.id)}', this.checked)">
        <span><b>${esc(p.nom || p.entreprise || '(sans nom)')}</b> — ${esc(p.email || 'pas d\'email trouvé')}${p.statut ? ` <span style="color:var(--mut);font-size:.8rem">· ${esc(p.statut)}</span>` : ''}</span>
      </label>`).join('');
    majFormulaireDemarchage();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}

function toggleProspectChoisi(id, coche) {
  if (coche) PROSPECTS_SELECTIONNES.add(id); else PROSPECTS_SELECTIONNES.delete(id);
  majFormulaireDemarchage();
}

function majFormulaireDemarchage() {
  document.getElementById('zone-demarchage').style.display = PROSPECTS_SELECTIONNES.size ? 'block' : 'none';
  document.getElementById('compte-selection-demarchage').textContent =
    `${PROSPECTS_SELECTIONNES.size} prospect(s) sélectionné(s)`;
}

async function preparerDemarchage() {
  const expediteur = document.getElementById('demarchage-expediteur').value.trim();
  const sujet = document.getElementById('demarchage-sujet').value.trim();
  const message = document.getElementById('demarchage-message').value.trim();
  const resultat = document.getElementById('resultat-demarchage');
  resultat.textContent = '';
  if (!expediteur || !sujet || !message) { resultat.textContent = 'Expéditeur, sujet et message sont requis.'; return; }
  if (!PROSPECTS_SELECTIONNES.size) { resultat.textContent = 'Sélectionne au moins un prospect.'; return; }
  const campagneId = Number(document.getElementById('panneau-prospects').dataset.campagneId);
  try {
    const r = await fetch(`${API_BASE}/prospection/demarchage`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({campagne_id: campagneId, prospect_ids: Array.from(PROSPECTS_SELECTIONNES),
                            expediteur, sujet, message})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const res = await r.json();
    resultat.textContent = res.message || `${res.prepares} brouillon(s) préparé(s).`;
  } catch (e) {
    resultat.textContent = String(e.message || e);
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/atelier-veille && python -m pytest -v`
Expected: PASS (suite complète — les 4 onglets, aucune régression)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/front.html briques/atelier-veille/test_front.py
git commit -m "$(cat <<'EOF'
feat(atelier-veille): prospects + démarchage dans l'onglet Prospection

Liste des prospects trouvés par campagne (cases à cocher, emails
manquants grisés plutôt que cachés), formulaire de préparation des
brouillons de démarchage — jamais d'envoi automatique.
EOF
)"
```

---

## Verification finale (après la Task 9)

- [ ] `cd briques/veille-prospection && python -m pytest -v` → toute la suite verte
- [ ] `cd briques/atelier-veille && python -m pytest -v` → toute la suite verte
- [ ] Relire `docs/superpowers/specs/2026-08-19-atelier-veille-prospection-onglet-design.md`
  section par section, vérifier que chaque route/comportement listé a bien une tâche
  correspondante ci-dessus (déjà vérifié à l'écriture de ce plan, cf. auto-revue ci-dessous).
