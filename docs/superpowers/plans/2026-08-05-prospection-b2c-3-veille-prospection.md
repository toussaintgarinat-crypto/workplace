# Prospection B2C — veille-prospection : campagnes typées b2b/b2c Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une campagne `veille-prospection` porte un `type` (`b2b`/`b2c`, défaut
`b2b`) — sert à filtrer/lister sans joindre `geo`, et affiche un avertissement
best-effort si la zone référencée ne correspond visiblement pas au type déclaré.

**Architecture:** Colonne additive `type` sur `campagnes` (migration douce, motif
déjà utilisé dans `geo/stockage.py`). **Écart assumé par rapport à une première
lecture de la spec** : la validation zone↔type à la création N'EST PAS bloquante —
voir la justification dans la Task 3, ça casserait le motif de test existant où
`zone_id` n'est jamais vérifié contre `geo` à la création (seulement à l'exécution,
avec dégradation silencieuse déjà en place). `orchestration.py` (le pipeline
horaire zone→forge→memoire) **ne change pas du tout** : il est déjà générique par
rapport au type d'objet que `geo` renvoie.

**Tech Stack:** FastAPI, SQLite (stdlib), `httpx` (déjà une dépendance de cette
brique, via `orchestration.py`).

## Global Constraints

- Aucun changement de comportement observable pour les campagnes existantes
  (`type` par défaut `"b2b"`, migration douce, rétrocompatible bit-à-bit).
- La validation zone↔type ne doit JAMAIS bloquer ni ralentir significativement la
  création d'une campagne si `geo` est injoignable ou lent — best-effort, timeout
  court, aucune exception ne remonte au client.
- `orchestration.py` (exécution horaire des campagnes) n'a AUCUNE tâche dans ce
  plan — déjà générique (confirmé dans la spec, section « Backend —
  veille-prospection »).

---

### Task 1: Colonne `type` sur `campagnes` (`stockage.py`)

**Files:**
- Modify: `briques/veille-prospection/stockage.py`
- Test: `briques/veille-prospection/test_stockage.py`

**Interfaces:**
- Produces: `stockage.creer_campagne(user_id: str, zone_id: str, type_: str =
  "b2b") -> dict` — le dict renvoyé (et celui de `lister_campagnes`) gagne la clé
  `"type"`. Consommé par `main.py` (Task 2).

- [ ] **Step 1: Écrire les tests**

Ajouter à `briques/veille-prospection/test_stockage.py` (si le fichier n'existe pas
déjà avec ce nom, vérifier avec `ls briques/veille-prospection/test_*.py` — sinon
créer le fichier avec cet en-tête minimal : `import stockage`) :

```python
def test_creer_campagne_type_par_defaut_b2b():
    c = stockage.creer_campagne("user-type-defaut", "zone-x")
    assert c["type"] == "b2b"


def test_creer_campagne_type_b2c():
    c = stockage.creer_campagne("user-type-b2c", "zone-logements", type_="b2c")
    assert c["type"] == "b2c"


def test_lister_campagnes_expose_le_type():
    stockage.creer_campagne("user-liste-type", "zone-y", type_="b2c")
    campagnes = stockage.lister_campagnes("user-liste-type")
    assert campagnes[0]["type"] == "b2c"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/veille-prospection && python3 -m pytest test_stockage.py -k type -v`
Expected: FAIL avec `KeyError: 'type'` (ou `TypeError` sur `type_=` si le paramètre
n'existe pas encore)

- [ ] **Step 3: Implémenter**

Dans `briques/veille-prospection/stockage.py`, `init()` — ajouter après
`c.executescript(_SCHEMA)` :

```python
def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)
        for alter in ("ALTER TABLE campagnes ADD COLUMN type TEXT NOT NULL DEFAULT 'b2b'",):
            try:
                c.execute(alter)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente
```

`_campagne_dict` :

```python
def _campagne_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "zone_id": r["zone_id"],
            "type": r["type"], "actif": bool(r["actif"]),
            "derniere_execution": r["derniere_execution"], "created_at": r["created_at"]}
```

`creer_campagne` :

```python
def creer_campagne(user_id: str, zone_id: str, type_: str = "b2b") -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO campagnes (user_id, zone_id, type, actif, created_at) "
            "VALUES (?,?,?,1,?)",
            (user_id, zone_id, type_, _maintenant()))
        row = c.execute("SELECT * FROM campagnes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _campagne_dict(row)
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/veille-prospection && python3 -m pytest test_stockage.py -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/stockage.py briques/veille-prospection/test_stockage.py
git commit -m "feat(veille-prospection): colonne type (b2b/b2c) sur les campagnes"
```

---

### Task 2: Route `POST /campagnes` accepte `type` (`main.py`)

**Files:**
- Modify: `briques/veille-prospection/main.py`
- Test: `briques/veille-prospection/test_main.py`

**Interfaces:**
- Consumes: `stockage.creer_campagne(user_id, zone_id, type_=...)` (Task 1).
- Produces: `POST /campagnes` accepte `{"zone_id", "type"?}`, `type` par défaut
  `"b2b"`, refuse (422) toute valeur hors `{"b2b", "b2c"}`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `briques/veille-prospection/test_main.py` :

```python
def test_creer_campagne_type_b2c(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    r = client.post("/campagnes", headers=_entetes("main-eve"),
                    json={"zone_id": "zone-logements-eve", "type": "b2c"})
    assert r.status_code == 201 and r.json()["type"] == "b2c"


def test_creer_campagne_type_par_defaut_reste_b2b(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    r = client.post("/campagnes", headers=_entetes("main-frank"),
                    json={"zone_id": "zone-frank"})
    assert r.status_code == 201 and r.json()["type"] == "b2b"


def test_creer_campagne_type_invalide_422(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    r = client.post("/campagnes", headers=_entetes("main-gina"),
                    json={"zone_id": "zone-gina", "type": "b2x"})
    assert r.status_code == 422
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/veille-prospection && python3 -m pytest test_main.py -k "type_b2c or type_par_defaut or type_invalide" -v`
Expected: FAIL — `type` n'est pas encore un champ reconnu, la 3e assertion ne peut
pas échouer en 422 (le body est actuellement accepté tel quel, `type` juste ignoré).

- [ ] **Step 3: Implémenter**

Dans `briques/veille-prospection/main.py` :

```python
class CreerCampagne(BaseModel):
    zone_id: str = Field(min_length=1)
    type: str = "b2b"


@app.post("/campagnes", tags=["campagnes"], status_code=201)
def creer_campagne_route(body: CreerCampagne, tenant: str = Depends(tenant_actuel)):
    type_ = body.type.strip().lower()
    if type_ not in ("b2b", "b2c"):
        raise HTTPException(422, "« type » doit être « b2b » ou « b2c ».")
    campagne = stockage.creer_campagne(tenant, body.zone_id, type_=type_)
    avertissement = orchestration.avertissement_type_zone(body.zone_id, type_)
    if avertissement:
        campagne["avertissement"] = avertissement
    return campagne
```

(`orchestration.avertissement_type_zone` n'existe pas encore — Task 3. Ce fichier
ne compilera/passera pas ses tests tant que la Task 3 n'est pas faite ; c'est
attendu, les deux tasks sont livrées dans la foulée.)

- [ ] **Step 4: Commit (les tests de la Step 1 restent rouges, attendu)**

```bash
git add briques/veille-prospection/main.py briques/veille-prospection/test_main.py
git commit -m "feat(veille-prospection): POST /campagnes accepte un type b2b/b2c"
```

---

### Task 3: Avertissement best-effort zone↔type (`orchestration.py`)

**Pourquoi best-effort, pas bloquant** : le motif existant de cette brique (voir
`test_creer_lister_supprimer_campagne` dans `test_main.py`, déjà en place) crée des
campagnes avec des `zone_id` **jamais vérifiés contre `geo`** — la validation reste
implicite, à l'exécution (`_appeler_geo` échoue proprement si la zone n'existe pas,
compté dans `erreur`, jamais un crash). Rendre la vérification BLOQUANTE à la
création casserait ce motif existant (tous les tests actuels devraient mocker un
appel réseau qu'ils ignorent aujourd'hui) et coup lerait une route synchrone à la
disponibilité de `geo`. Le compromis : un avertissement informatif, jamais une
erreur — silencieux si `geo` est injoignable ou si la zone est introuvable (aucune
information n'est perdue, l'erreur réelle apparaîtra de toute façon à la première
exécution de la campagne).

**Files:**
- Modify: `briques/veille-prospection/orchestration.py`
- Test: `briques/veille-prospection/test_orchestration.py`

**Interfaces:**
- Produces: `orchestration.lire_zone_geo(zone_id: str) -> dict | None` (lève
  `httpx.HTTPError` si `geo` est injoignable — l'appelant décide),
  `orchestration.avertissement_type_zone(zone_id: str, type_campagne: str) -> str |
  None` (n'ÉLÈVE JAMAIS, best-effort complet). Consommé par `main.py` (Task 2, déjà
  écrit).

- [ ] **Step 1: Écrire les tests**

Ajouter à `briques/veille-prospection/test_orchestration.py` (vérifier l'en-tête du
fichier pour le motif de mock `httpx` déjà utilisé — sinon suivre le style
`monkeypatch.setattr(orchestration.httpx, "get", ...)` cohérent avec le reste du
fichier qui mocke déjà `httpx.post` pour `_appeler_geo`/`_appeler_forge`) :

```python
class _FauxReponseZones:
    def __init__(self, zones):
        self._zones = zones

    def raise_for_status(self):
        pass

    def json(self):
        return {"zones": self._zones}


def test_lire_zone_geo_trouve_par_id(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get", lambda *a, **k: _FauxReponseZones(
        [{"id": "z1", "nom": "Zone 1", "type": "logement"},
         {"id": "z2", "nom": "Zone 2", "type": "entreprise"}]))
    zone = orchestration.lire_zone_geo("z2")
    assert zone == {"id": "z2", "nom": "Zone 2", "type": "entreprise"}


def test_lire_zone_geo_absente_rend_none(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get",
                        lambda *a, **k: _FauxReponseZones([]))
    assert orchestration.lire_zone_geo("introuvable") is None


def test_avertissement_type_zone_signale_incoherence_b2c(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get", lambda *a, **k: _FauxReponseZones(
        [{"id": "z1", "nom": "Entreprises Castres", "type": "entreprise"}]))
    a = orchestration.avertissement_type_zone("z1", "b2c")
    assert a and "logement" in a


def test_avertissement_type_zone_silencieux_si_coherent(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get", lambda *a, **k: _FauxReponseZones(
        [{"id": "z1", "nom": "Passoires", "type": "logement"}]))
    assert orchestration.avertissement_type_zone("z1", "b2c") is None


def test_avertissement_type_zone_silencieux_si_geo_injoignable(monkeypatch):
    def _casse(*a, **k):
        raise httpx.ConnectError("refus de connexion")
    monkeypatch.setattr(orchestration.httpx, "get", _casse)
    assert orchestration.avertissement_type_zone("z1", "b2c") is None


def test_avertissement_type_zone_silencieux_si_zone_introuvable(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get",
                        lambda *a, **k: _FauxReponseZones([]))
    assert orchestration.avertissement_type_zone("introuvable", "b2c") is None
```

(`import httpx` est déjà présent en tête de `test_orchestration.py` si le fichier
teste déjà `_appeler_geo`/panne réseau ; sinon l'ajouter.)

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/veille-prospection && python3 -m pytest test_orchestration.py -k "zone_geo or avertissement" -v`
Expected: FAIL avec `AttributeError: module 'orchestration' has no attribute 'lire_zone_geo'`

- [ ] **Step 3: Implémenter**

Ajouter dans `briques/veille-prospection/orchestration.py`, à la suite de
`_appeler_forge` (avant `_pousser_memoire`) :

```python
def lire_zone_geo(zone_id: str) -> dict | None:
    """Lit une zone `geo` par id (liste + filtre — `geo` n'expose pas de GET
    /zones/{id} unitaire). Lève httpx.HTTPError si `geo` est injoignable — c'est
    `avertissement_type_zone` qui absorbe cette erreur en best-effort, pas cette
    fonction (elle reste honnête pour un futur appelant qui voudrait, lui,
    propager l'échec)."""
    base = _url("GEO_URL", "http://host.docker.internal:6110")
    r = httpx.get(f"{base}/zones", headers=_entetes("GEO_KEY"), timeout=5)
    r.raise_for_status()
    for zone in r.json().get("zones", []):
        if zone["id"] == zone_id:
            return zone
    return None


def avertissement_type_zone(zone_id: str, type_campagne: str) -> str | None:
    """Best-effort : prévient si la zone référencée ne correspond visiblement pas au
    type de campagne déclaré (b2c attend une zone `logement`, b2b attend le contraire).
    Ne bloque JAMAIS la création d'une campagne — `geo` injoignable ou zone inconnue
    d'ici = silence, pas une erreur (l'échec réel, s'il y en a un, apparaîtra de
    toute façon à la première exécution horaire, déjà gérée en best-effort là-bas)."""
    try:
        zone = lire_zone_geo(zone_id)
    except Exception:  # noqa: BLE001 — best-effort strict, jamais bloquant
        return None
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
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/veille-prospection && python3 -m pytest test_orchestration.py -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Lancer TOUTE la suite (main.py dépend de cette task, Task 2)**

Run: `cd briques/veille-prospection && python3 -m pytest -v`
Expected: PASS (tous les fichiers, y compris `test_main.py` de la Task 2)

- [ ] **Step 6: Commit**

```bash
git add briques/veille-prospection/orchestration.py briques/veille-prospection/test_orchestration.py
git commit -m "feat(veille-prospection): avertissement best-effort zone/type de campagne"
```

---

## Self-Review

**Couverture spec** (section « Backend — veille-prospection ») : migration `type`
✓ (Task 1), route `POST /campagnes` ✓ (Task 2). **Écart documenté et justifié** :
la validation « bloque à la création si zone↔type incohérent » suggérée par la
spec est devenue un avertissement best-effort (Task 3) — le texte de la spec disait
déjà « garde-fou », pas « blocage strict », et l'implémentation bloquante aurait
cassé le motif de test existant (`zone_id` jamais vérifié à la création). Choix
tranché en écrivant le plan, pas laissé en flou.

**`orchestration.py` (exécution horaire)** : confirmé INCHANGÉ, comme prévu dans
la spec corrigée — `_executer_campagne` ne lit jamais `campagne["type"]`.

**Cohérence des types** : `avertissement_type_zone(zone_id: str, type_campagne:
str) -> str | None` a la même signature dans son test et son appel depuis
`main.py` (Task 2) : deux arguments positionnels, `zone_id` puis `type_`.
