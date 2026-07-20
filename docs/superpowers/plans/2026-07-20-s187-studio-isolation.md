# S187 — Isolation par personne de la brique studio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isoler la brique `studio` (audio-séries, port 6060) par personne — chaque série audio
n'est visible/modifiable que par son créateur, aussi bien depuis l'assistant que depuis la tuile
dashboard "Créations" — en corrigeant le dernier des 4 trous reportés par l'audit S183
(`docs/rapport-s183-audit-isolation.md`).

**Architecture:** `briques/studio/main.py::cle_api()` gagne un second dialecte (clé == `STUDIO_KEY`
⇒ identité = `X-User-Id`) coexistant avec le dialecte BYO historique. Le wrapper `charger()`
(déjà utilisé par ~34 routes) centralise le contrôle d'appartenance en un seul point. Côté Cœur,
`core/outils_communs.BRIQUES_PAR_PERSONNE` gagne `"studio"` (fixe automatiquement les capacités
manifest) et `_studio_appel` (helper legacy hors-manifest) est aligné sur le même mécanisme. La
tuile dashboard passe d'une `STUDIO_KEY` statique transportée au navigateur à un nouveau proxy
Cœur `core/routers/studio_proxy.py` (clone de `core/routers/mail_proxy.py`) qui re-résout
l'identité de session à chaque appel.

**Tech Stack:** FastAPI (briques Python + Cœur), pytest, JS vanilla (front.html).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-20-s187-studio-isolation-design.md` — toute
  divergence avec ce plan doit être résolue en faveur du spec.
- Zéro régression sur le dialecte BYO standalone (`API_KEYS`) : les 4 tests existants de
  `briques/studio/test_auth.py` doivent rester verts SANS modification de leurs assertions.
- 404 (pas 403) partout où l'appartenance est vérifiée — ne jamais révéler l'existence d'une
  série à quelqu'un d'autre (motif mail/ecoute).
- `make test-core` doit rester au vert après chaque tâche touchant `core/`.
- Pas de déploiement LIVE HP dans ce sprint (régime preuve Docker différée) — code + tests
  uniquement.

---

### Task 1 : `BRIQUES_PAR_PERSONNE` += `"studio"`

**Files:**
- Modify: `core/outils_communs.py:47-51`
- Test: `core/test_contexte_tenant.py:149-161`

**Interfaces:**
- Consumes: `contexte_tenant.entetes_par_personne()` (existant, inchangé).
- Produces: `outils_communs._entetes_brique("studio")` inclut désormais `X-User-Id` — consommé
  par Task 2 (`_studio_appel`) et par le dispatch dynamique des capacités manifest (déjà câblé,
  `core/outils_communs.py:113-116`, aucune modification nécessaire là).

- [ ] **Step 1: Écrire l'assertion qui échoue**

Dans `core/test_contexte_tenant.py`, modifier `test_entetes_brique_par_personne_forwarde_identite`
(lignes 149-161) :

```python
def test_entetes_brique_par_personne_forwarde_identite():
    """S182 (agenda) + S184 (ecoute) + S185 (mail) + S186 (memoire) + S187 (studio) : la
    surface /service (outils de l'assistant) doit porter X-User-Id = utilisateur connecté
    pour les briques « cercle privé » ; les autres briques ne le portent pas."""
    _reset_complet()
    import outils_communs
    ct.definir_contexte(utilisateur="claire")
    assert outils_communs._entetes_brique("agenda")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("ecoute")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("mail")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("memoire")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("studio")["X-User-Id"] == "claire"
    # Une autre brique (ex. restaurant) ne reçoit PAS X-User-Id (elle l'ignorerait).
    assert "X-User-Id" not in outils_communs._entetes_brique("restaurant")
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_contexte_tenant.py -k test_entetes_brique_par_personne_forwarde_identite -v`
Expected: FAIL — `KeyError: 'X-User-Id'` (studio pas encore dans `BRIQUES_PAR_PERSONNE`).

- [ ] **Step 3: Appliquer le fix**

Dans `core/outils_communs.py`, remplacer les lignes 47-51 :

```python
# Briques « cercle privé » (S182 agenda, S184 ecoute, S185 mail, S186 memoire) : le Cœur
# forwarde l'identité de l'utilisateur connecté en X-User-Id, gagée par {BRIQUE}_KEY (seul
# le Cœur la détient). Les autres briques ignorent cet en-tête (motif tenant/bundle-client,
# cf. X-Compte-Id).
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire"}
```

par :

```python
# Briques « cercle privé » (S182 agenda, S184 ecoute, S185 mail, S186 memoire, S187 studio) :
# le Cœur forwarde l'identité de l'utilisateur connecté en X-User-Id, gagée par {BRIQUE}_KEY
# (seul le Cœur la détient). Les autres briques ignorent cet en-tête (motif tenant/bundle-
# client, cf. X-Compte-Id).
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire", "studio"}
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_contexte_tenant.py -v`
Expected: PASS — tous les tests du fichier.

- [ ] **Step 5: Commit**

```bash
git add core/outils_communs.py core/test_contexte_tenant.py
git commit -m "feat(studio): studio rejoint BRIQUES_PAR_PERSONNE (S187)"
```

---

### Task 2 : `_studio_appel` forwarde l'identité par personne

**Files:**
- Modify: `core/outils_communs.py:248-260`
- Test: `core/test_studio_outils.py:81-98`

**Interfaces:**
- Consumes: `outils_communs._entetes_brique("studio")` (Task 1).
- Produces: `_studio_appel` envoie `X-User-Id` en plus de `X-API-Key`/`X-Compte-Id` — aucun
  changement de signature, transparent pour ses deux appelants (`_personnage_holistique`,
  `_personnage_importer_serie`, `core/outils_communs.py:407-452`).

`_studio_appel` construit aujourd'hui ses en-têtes à la main (`{"X-API-Key": cle} if cle else
None`), en court-circuitant `_entetes_brique` — donc Task 1 seule NE le corrige PAS (il n'est
appelé par aucune capacité manifest ; c'est un helper legacy utilisé par 2 outils composés).

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `core/test_studio_outils.py`, remplacer les 2 tests existants sur les en-têtes (lignes
81-98, `test_studio_appel_envoie_la_cle` et `test_studio_appel_sans_cle_pas_dentete`) par :

```python
def test_studio_appel_envoie_la_cle():
    os.environ["STUDIO_KEY"] = "secret-de-service"
    try:
        cli = _Client(_Resp(200, {"ok": True}))
        out = asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
        assert cli.dernier["headers"]["X-API-Key"] == "secret-de-service"
        assert cli.dernier["url"] == "http://studio.test/series"
        assert json.loads(out) == {"ok": True}
    finally:
        os.environ.pop("STUDIO_KEY", None)


def test_studio_appel_sans_cle_pas_de_cle_api():
    os.environ.pop("STUDIO_KEY", None)
    cli = _Client(_Resp(200, {"ok": True}))
    asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
    assert "X-API-Key" not in (cli.dernier["headers"] or {})


def test_studio_appel_forwarde_lidentite_par_personne():
    import contexte_tenant as ct
    os.environ["STUDIO_KEY"] = "secret-de-service"
    try:
        ct.definir_contexte(utilisateur="claire")
        cli = _Client(_Resp(200, {"ok": True}))
        asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
        assert cli.dernier["headers"]["X-User-Id"] == "claire"
    finally:
        os.environ.pop("STUDIO_KEY", None)
        ct.definir_contexte(utilisateur=ct.UTILISATEUR_DEFAUT)
        ct._utilisateur.set(ct.UTILISATEUR_DEFAUT)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_studio_outils.py -v`
Expected: FAIL — `test_studio_appel_envoie_la_cle` échoue sur `cli.dernier["headers"]["X-API-Key"]`
(headers vaut encore exactement `{"X-API-Key": ...}` sans problème en fait ; le vrai FAIL vient de
`test_studio_appel_forwarde_lidentite_par_personne` : `KeyError: 'X-User-Id'`).

- [ ] **Step 3: Appliquer le fix minimal**

Dans `core/outils_communs.py`, remplacer les lignes 258-260 :

```python
    base = _base(registre, "studio")
    cle = os.environ.get("STUDIO_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
```

par :

```python
    base = _base(registre, "studio")
    entetes = _entetes_brique("studio")
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_studio_outils.py -v`
Expected: PASS — les 3 tests d'en-têtes + les 2 tests inchangés (`test_studio_appel_401_message_clair`,
`test_studio_appel_hors_ligne_degrade`, qui ne portent pas sur `headers` et restent verts).

- [ ] **Step 5: Commit**

```bash
git add core/outils_communs.py core/test_studio_outils.py
git commit -m "fix(studio): _studio_appel forwarde X-User-Id (S187)"
```

---

### Task 3 : Second dialecte `STUDIO_KEY` dans `cle_api()`

**Files:**
- Modify: `briques/studio/main.py:39-59`
- Test: `briques/studio/test_auth.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `cle_api()` renvoie l'identité `X-User-Id` (repli `"perso"`) quand la clé présentée
  == `STUDIO_KEY` — consommé par Task 4 (`charger()`, `lister_series`, `reordonner_series`).

Cette tâche NE touche PAS encore le filtrage (Task 4) — juste la résolution d'identité, testable
isolément via `/series` (GET, liste non filtrée pour l'instant → juste vérifier le code retour et,
en ajoutant une trace temporaire non nécessaire ici : le test vérifie via `POST /series` que
`cree_par` reflète bien la nouvelle identité).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/studio/test_auth.py` :

```python
def test_dialecte_studio_key_utilise_x_user_id(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    r = client.post("/series", json={"titre": "Test"},
                    headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json()["cree_par"] == "claire"


def test_dialecte_studio_key_replie_sur_perso_sans_x_user_id(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    r = client.post("/series", json={"titre": "Test"}, headers={"X-API-Key": "cle-coeur"})
    assert r.status_code == 200
    assert r.json()["cree_par"] == "perso"


def test_dialecte_byo_inchange_avec_studio_key_configuree(monkeypatch):
    # Une clé BYO (API_KEYS, PAS STUDIO_KEY) garde le motif historique : identité = la clé.
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    monkeypatch.setattr(M, "API_KEYS", {"cle-coeur", "clef-client-byo"})
    r = client.post("/series", json={"titre": "Test"},
                    headers={"X-API-Key": "clef-client-byo", "X-User-Id": "claire"})
    assert r.status_code == 200
    # X-User-Id est IGNORÉ pour une clé BYO — ce n'est pas le Cœur qui appelle.
    assert r.json()["cree_par"] == "clef-client-byo"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_auth.py -v`
Expected: FAIL sur les 3 nouveaux tests — `cree_par` vaut `"cle-coeur"` (la clé brute, motif
BYO actuel) au lieu de `"claire"`/`"perso"`, et le 3e échoue avec 401 (clé BYO refusée tant que
`STUDIO_KEY` seule est acceptée — en fait `API_KEYS` est patché donc elle DEVRAIT déjà passer ;
si elle passe déjà avec `cree_par == "clef-client-byo"`, c'est attendu et ce test passe dès
l'écriture — laisse-le, il documente la non-régression).

- [ ] **Step 3: Appliquer le fix**

Dans `briques/studio/main.py`, remplacer les lignes 39-59 :

```python
# Clés API acceptées (séparées par virgule). Vide = mode OUVERT (dev) : tenant unique "public".
# `API_KEYS` = vente standalone (BYO). `STUDIO_KEY` = clé d'intégration Workplace, injectée par
# le `.env` racine (le noyau et son iframe s'authentifient avec) — variable DÉDIÉE pour ne pas
# activer l'auth des autres briques qui liraient un `API_KEYS` partagé.
API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
if os.getenv("STUDIO_KEY", "").strip():
    API_KEYS.add(os.getenv("STUDIO_KEY").strip())


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API (X-API-Key ou Authorization: Bearer) et sert d'identité créateur.

    Mode ouvert si aucune clé configurée → identité « public ». La partition des séries
    PAR tenant n'est pas encore faite (socle S51) : à brancher quand on vend la brique."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
```

par :

```python
# Clés API acceptées (séparées par virgule). Vide = mode OUVERT (dev) : tenant unique "public".
# `API_KEYS` = vente standalone (BYO), chaque clé cliente = son propre tenant (motif historique).
API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None),
            x_user_id: Optional[str] = Header(None)) -> str:
    """Valide la clé API (X-API-Key ou Authorization: Bearer) et sert d'identité créateur.

    Trois dialectes (S187) :
    - clé == `STUDIO_KEY` (compte de service du Cœur, LUE FRAÎCHE à chaque appel via
      `os.environ` — motif ECOUTE_KEY/MAIL_KEY, monkeypatchable en test) → identité =
      `X-User-Id` transmis par le Cœur (repli `"perso"` si absent) : isolation PAR PERSONNE
      dans le cercle privé.
    - clé dans `API_KEYS` mais ≠ `STUDIO_KEY` (vente BYO standalone) → identité = la clé
      elle-même (motif historique, inchangé — `X-User-Id` est ignoré, ce n'est pas le Cœur
      qui appelle).
    - Mode ouvert (aucune clé configurée du tout) → identité = la clé présentée ou `"public"`
      (comportement actuel, inchangé).
    """
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    studio_key = os.environ.get("STUDIO_KEY", "").strip()
    if studio_key and presentee == studio_key:
        return x_user_id or "perso"
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_auth.py -v`
Expected: PASS — les 4 tests existants (mode ouvert, BYO 401/200/mauvaise clé) ET les 3 nouveaux.

- [ ] **Step 5: Mettre à jour le docstring de `test_auth.py`**

Dans `briques/studio/test_auth.py`, ligne 5, remplacer :
```python
active = 401 sans clé, 200 avec la bonne clé. (Le repli STUDIO_KEY→API_KEYS est prouvé en LIVE.)
```
par :
```python
active = 401 sans clé, 200 avec la bonne clé. `STUDIO_KEY` a son propre dialecte par personne
(S187, cf. test_dialecte_studio_key_*), distinct du dialecte BYO ci-dessous.
```

- [ ] **Step 6: Commit**

```bash
git add briques/studio/main.py briques/studio/test_auth.py
git commit -m "feat(studio): dialecte STUDIO_KEY par personne dans cle_api (S187)"
```

---

### Task 4 : Filtrage d'appartenance — `charger()`, `lister_series`, `reordonner_series`

**Files:**
- Modify: `briques/studio/main.py` (voir liste de sites ci-dessous)
- Test: `briques/studio/test_isolation_personne.py` (nouveau)

**Interfaces:**
- Consumes: `cle_api()` (Task 3) — l'identité résolue par requête.
- Produces: `charger(serie_id: str, identite: str) -> dict` (signature CHANGÉE, était
  `charger(serie_id: str) -> dict`) ; `_identite_effective(serie: dict) -> str` (nouvelle
  fonction). Toute route future qui charge une série DOIT passer son identité.

C'est la tâche la plus large : ~34 sites d'appel à `charger(serie_id)` deviennent
`charger(serie_id, cle)`, et ~29 signatures de route `_cle: str = Depends(cle_api)` deviennent
`cle: str = Depends(cle_api)` (le paramètre devient réellement utilisé). 5 routes qui ne touchent
JAMAIS une série précise gardent `_cle` inchangé : `equipe` (150), `lister_cibles` (367),
`lister_langues` (383), `voix_disponibles` (399), `personnages_holistiques` (455).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `briques/studio/test_isolation_personne.py` :

```python
"""Isolation PAR PERSONNE quand le Cœur présente sa STUDIO_KEY (S187, motif mail S185 /
memoire S186) : deux personnes du même foyer, même STUDIO_KEY, séries étanches.

Distinct de `test_auth.py` (dialecte BYO — chaque client externe a SA propre clé) : ici
c'est LA MÊME clé (`STUDIO_KEY`) pour tout le foyer, l'isolation vient de `X-User-Id`.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _studio_key(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    yield


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def _creer_serie(utilisateur, titre="Ma série"):
    r = client.post("/series", json={"titre": titre}, headers=_entetes(utilisateur))
    assert r.status_code == 200
    return r.json()


def test_serie_de_claire_invisible_pour_marina():
    serie = _creer_serie("claire")
    assert client.get(f"/series/{serie['id']}", headers=_entetes("marina")).status_code == 404
    assert client.get(f"/series/{serie['id']}", headers=_entetes("claire")).status_code == 200


def test_serie_de_claire_absente_de_la_liste_de_marina():
    serie = _creer_serie("claire")
    ids_marina = [s["id"] for s in client.get("/series", headers=_entetes("marina")).json()]
    assert serie["id"] not in ids_marina
    ids_claire = [s["id"] for s in client.get("/series", headers=_entetes("claire")).json()]
    assert serie["id"] in ids_claire


def test_sous_routes_404_pour_un_autre_proprietaire():
    serie = _creer_serie("claire")
    sid = serie["id"]
    entetes_marina = _entetes("marina")
    assert client.get(f"/series/{sid}/personnages", headers=entetes_marina).status_code == 404
    assert client.get(f"/series/{sid}/episodes", headers=entetes_marina).status_code == 404
    assert client.post(f"/series/{sid}/cycles", json={"titre": "C"},
                       headers=entetes_marina).status_code == 404
    assert client.delete(f"/series/{sid}", headers=entetes_marina).status_code == 404
    # La série existe toujours pour sa propriétaire (pas vraiment supprimée par le 404 ci-dessus).
    assert client.get(f"/series/{sid}", headers=_entetes("claire")).status_code == 200


def test_sans_x_user_id_replie_sur_perso():
    a = _creer_serie("perso", titre="A")
    ids_sans_entete = [s["id"] for s in
                       client.get("/series", headers={"X-API-Key": "cle-coeur"}).json()]
    assert a["id"] in ids_sans_entete


def test_reordonner_ignore_silencieusement_les_series_dautrui():
    serie_claire = _creer_serie("claire")
    serie_marina = _creer_serie("marina")
    r = client.post("/series/reordonner",
                    json={"ids": [serie_marina["id"], serie_claire["id"]]},
                    headers=_entetes("claire"))
    assert r.status_code == 200
    # Seul l'ordre de la série de claire a pu être posé (celle de marina est ignorée).
    s = client.get(f"/series/{serie_claire['id']}", headers=_entetes("claire")).json()
    assert s.get("ordre") == 1
    s_marina = client.get(f"/series/{serie_marina['id']}", headers=_entetes("marina")).json()
    assert s_marina.get("ordre") is None


def test_serie_legacy_cree_par_public_visible_sous_perso():
    # Simule une série créée AVANT ce sprint (mode ouvert historique, cree_par="public").
    import studio as S
    serie = {
        "id": "legacy1", "titre": "Ancienne série", "world_id": None, "cible": None,
        "langue": "fr", "bible": {}, "personnages": [], "episodes": [],
        "cree_par": "public", "cree_le": "2026-01-01T00:00:00+00:00",
    }
    S._normaliser(serie)
    S._save(serie)
    r = client.get("/series/legacy1", headers=_entetes("perso"))
    assert r.status_code == 200
    assert client.get("/series/legacy1", headers=_entetes("claire")).status_code == 404


def test_dialecte_byo_toujours_isole_par_cle_hors_studio_key(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"clef-client-a", "clef-client-b"})
    r = client.post("/series", json={"titre": "Client A"},
                    headers={"X-API-Key": "clef-client-a"})
    sid = r.json()["id"]
    assert client.get(f"/series/{sid}",
                      headers={"X-API-Key": "clef-client-b"}).status_code == 404
    assert client.get(f"/series/{sid}",
                      headers={"X-API-Key": "clef-client-a"}).status_code == 200
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/studio && python3 -m pytest test_isolation_personne.py -v`
Expected: FAIL sur la plupart — `charger()` ne filtre encore sur rien, `lister_series` renvoie
tout, `reordonner_series` n'a pas de notion d'appartenance.

- [ ] **Step 3: Ajouter `_identite_effective` et changer `charger()`**

Dans `briques/studio/main.py`, remplacer les lignes 62-67 :

```python
def charger(serie_id: str) -> dict:
    """Charge une série (404 si absente) — wrap honnête de la persistance fichier."""
    try:
        return S._load(serie_id)
    except FileNotFoundError:
        raise HTTPException(404, "Série introuvable")
```

par :

```python
def _identite_effective(serie: dict) -> str:
    """Normalise `cree_par` à la LECTURE (jamais réécrit dans le fichier, S187) : une valeur
    legacy — mode ouvert historique (`"public"`) ou ancienne `STUDIO_KEY` brute d'avant ce
    sprint — est traitée comme `"perso"`, le bucket mono-user par défaut du dialecte par
    personne. N'affecte PAS le dialecte BYO : la clé d'un client reste sa propre identité."""
    valeur = serie.get("cree_par")
    studio_key = os.environ.get("STUDIO_KEY", "").strip()
    if valeur in (None, "public") or (studio_key and valeur == studio_key):
        return "perso"
    return valeur


def charger(serie_id: str, identite: str) -> dict:
    """Charge une série (404 si absente OU si elle n'appartient pas à `identite`) — wrap
    honnête de la persistance fichier. 404 (pas 403, motif mail/ecoute) : ne révèle jamais
    l'existence d'une série à quelqu'un d'autre."""
    try:
        serie = S._load(serie_id)
    except FileNotFoundError:
        raise HTTPException(404, "Série introuvable")
    if _identite_effective(serie) != identite:
        raise HTTPException(404, "Série introuvable")
    return serie
```

- [ ] **Step 4: Mettre à jour tous les appels à `charger(serie_id)`**

Deux remplacements mécaniques dans `briques/studio/main.py`, chacun avec l'outil Edit et
`replace_all=true` :

1. `old_string="charger(serie_id)"` → `new_string="charger(serie_id, cle)"` (33 occurrences —
   toutes SAUF la définition de la fonction elle-même, déjà changée au Step 3).
2. `old_string="_cle: str = Depends(cle_api)"` → `new_string="cle: str = Depends(cle_api)"`
   (convertit les 41 déclarations en une fois).

Puis revert individuel des 5 routes qui NE touchent PAS de série précise (elles n'ont pas besoin
de l'identité, on garde la convention `_` = paramètre FastAPI non utilisé). Après le
remplacement global du Step 4, elles sont devenues `cle: str = Depends(cle_api)` ; les
reverter une par une vers `_cle` (5 Edits, chacun avec `old_string`/`new_string` exacts) :

1. `old_string="def equipe(cle: str = Depends(cle_api)):"` →
   `new_string="def equipe(_cle: str = Depends(cle_api)):"`
2. `old_string="def lister_cibles(cle: str = Depends(cle_api)):"` →
   `new_string="def lister_cibles(_cle: str = Depends(cle_api)):"`
3. `old_string="def lister_langues(cle: str = Depends(cle_api)):"` →
   `new_string="def lister_langues(_cle: str = Depends(cle_api)):"`
4. `old_string="async def voix_disponibles(langue: str = \"fr\", cle: str = Depends(cle_api)):"` →
   `new_string="async def voix_disponibles(langue: str = \"fr\", _cle: str = Depends(cle_api)):"`
5. `old_string="async def personnages_holistiques(cle: str = Depends(cle_api)):"` →
   `new_string="async def personnages_holistiques(_cle: str = Depends(cle_api)):"`

- [ ] **Step 5: Filtrer `lister_series`**

Dans `briques/studio/main.py`, la signature de la route passe de
`def lister_series(world_id: Optional[str] = None, _cle: str = Depends(cle_api)):` à
`def lister_series(world_id: Optional[str] = None, cle: str = Depends(cle_api)):` (fait au
Step 4). Ajouter le filtre juste après le chargement du JSON (dans la boucle `for fn in
os.listdir(...)`), avant le `if world_id and ...` existant :

```python
        if _identite_effective(s) != cle:
            continue
        if world_id and s.get("world_id") != world_id:
            continue
```

- [ ] **Step 6: `reordonner_series` ignore les séries d'autrui**

Dans `briques/studio/main.py`, remplacer (signature déjà passée à `cle: str = Depends(cle_api)`
par le Step 4) :

```python
@app.post("/series/reordonner", tags=["séries"])
def reordonner_series(body: ReordonnerSeries, cle: str = Depends(cle_api)):
    """Réordonne les séries par cliquer-déposer (S104). `ids` = la nouvelle suite ; chaque
    série reçoit son rang comme `ordre` (persisté dans son fichier d'atelier)."""
    for rang, sid in enumerate(body.ids):
        try:
            serie = S._load(sid)
        except FileNotFoundError:
            continue
        serie["ordre"] = rang
        S._save(serie)
    return {"ok": True, "ordonnees": len(body.ids)}
```

par :

```python
@app.post("/series/reordonner", tags=["séries"])
def reordonner_series(body: ReordonnerSeries, cle: str = Depends(cle_api)):
    """Réordonne les séries par cliquer-déposer (S104). `ids` = la nouvelle suite ; chaque
    série reçoit son rang comme `ordre` (persisté dans son fichier d'atelier). Un id qui
    n'appartient pas à l'appelant est IGNORÉ silencieusement (S187) : c'est un
    réordonnancement best-effort de SA propre liste, pas une opération qu'on veut faire
    échouer en bloc pour un id étranger glissé dans la requête."""
    rang = 0
    for sid in body.ids:
        try:
            serie = S._load(sid)
        except FileNotFoundError:
            continue
        if _identite_effective(serie) != cle:
            continue
        serie["ordre"] = rang
        S._save(serie)
        rang += 1
    return {"ok": True, "ordonnees": rang}
```

(Le compteur `rang` n'avance QUE pour les séries effectivement réordonnées — sinon un id
étranger au milieu de la liste décalerait les rangs des séries suivantes qui appartiennent
bien à l'appelant.)

- [ ] **Step 7: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/studio && python3 -m pytest test_isolation_personne.py test_auth.py -v`
Expected: PASS — tous les tests des deux fichiers.

- [ ] **Step 8: Lancer la suite complète de la brique**

Run: `cd briques/studio && python3 -m pytest -v`
Expected: PASS — aucune régression sur `test_composition.py`, `test_continuite.py`,
`test_episodes.py`, `test_front.py`, `test_images.py`, `test_import_holistique.py`,
`test_langue.py`, `test_manifest_capacites.py`, `test_migration.py`, `test_personnages.py`,
`test_video.py` (tous appellent les routes SANS clé configurée → mode ouvert → identité
`"public"` uniforme pour tous leurs appels → le nouveau filtre ne les affecte pas puisqu'ils ne
comparent jamais deux identités différentes).

- [ ] **Step 9: Commit**

```bash
git add briques/studio/main.py briques/studio/test_isolation_personne.py briques/studio/test_auth.py
git commit -m "feat(studio): isolation par personne — charger()/lister_series/reordonner (S187)"
```

---

### Task 5 : Proxy Cœur `/studio-app/*`

**Files:**
- Create: `core/routers/studio_proxy.py`
- Test: `core/test_studio_proxy.py`
- Modify: `core/main.py`

**Interfaces:**
- Consumes: `outils_communs._entetes_brique("studio")` (Task 1/2), `orchestrateur._brique_base`.
- Produces: routes `GET /studio-app/`, `GET /studio-app/atelier`,
  `{GET,POST,DELETE,PATCH,PUT} /studio-app/{chemin:path}` — consommées par Task 7 (dashboard).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `core/test_studio_proxy.py` :

```python
"""Proxy studio du Cœur (S187) : vue native /studio-app/*, isolée PAR PERSONNE.

Motif copié de core/test_mail_proxy.py. Sans réseau : httpx.AsyncClient est remplacé par un
faux client qui enregistre les appels (méthode, url, en-têtes). Vérifie que l'identité
forwardée à la brique studio vient de LA SESSION (contexte de tenant), jamais de ce que le
navigateur a lui-même posé sur sa requête au Cœur.
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ["STUDIO_KEY"] = "cle-coeur-studio"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import studio_proxy  # noqa: E402

client = TestClient(main.app)

APPELS = []


class _Resp:
    def __init__(self, texte="", status=200, content_type="application/json"):
        self._texte = texte
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = texte.encode() if texte else b"{}"

    @property
    def text(self):
        return self._texte


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, content=None):
        APPELS.append((method, url, headers))
        return _Resp()

    async def get(self, url, headers=None):
        APPELS.append(("GET", url, headers))
        if url.endswith("/") or url.endswith("/atelier"):
            return _Resp(texte='<html><head></head><body>'
                                '<script src="/manipulation_directe.js"></script>'
                                '</body></html>')
        return _Resp()


def _setup(monkeypatch):
    APPELS.clear()
    monkeypatch.setattr(studio_proxy, "_base", lambda: "http://studio")
    monkeypatch.setattr(studio_proxy, "httpx", type("_H", (), {"AsyncClient": _FakeClient}))


def test_racine_injecte_le_prefixe_et_reecrit_le_socle(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/studio-app/", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert "window.STUDIO_API_BASE='/studio-app';" in r.text
    assert 'src="/studio-app/manipulation_directe.js"' in r.text


def test_identite_de_session_forwardee_pas_celle_du_navigateur(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/studio-app/series", headers={
        "X-User-Id": "claire", "X-API-Key": "cle-volee-par-le-navigateur",
    })
    assert r.status_code == 200
    methode, url, entetes = APPELS[-1]
    assert url == "http://studio/series"
    assert entetes["X-User-Id"] == "claire"
    assert entetes["X-API-Key"] == "cle-coeur-studio"


def test_deux_personnes_appels_distincts(monkeypatch):
    _setup(monkeypatch)
    client.get("/studio-app/series", headers={"X-User-Id": "claire"})
    client.get("/studio-app/series", headers={"X-User-Id": "marina"})
    identites = [e["X-User-Id"] for _, _, e in APPELS]
    assert identites == ["claire", "marina"]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_studio_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routers.studio_proxy'`.

- [ ] **Step 3: Créer `core/routers/studio_proxy.py`**

```python
"""Proxy « studio » du Cœur (S187) : vue native de la tuile Créations, isolée PAR PERSONNE.

Le frontend autoporté de la brique studio (`briques/studio/front.html`) fait ses appels via
une fonction JS unique `api(path, method, body)`, préfixée d'une variable `STUDIO_API_BASE`
posée côté page (vide en usage autoporté). On sert cette MÊME page sous `/studio-app/*` avec
`STUDIO_API_BASE` posé à ce préfixe, et on proxy chaque appel vers la vraie brique en y
injectant l'identité de la SESSION Cœur courante (`outils_communs._entetes_brique("studio")`
→ X-User-Id, motif agenda S182 / mail S185 / memoire S186) — au lieu de laisser le navigateur
appeler la brique en direct avec une STUDIO_KEY statique partagée par tout le foyer (trou S183).

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session` +
`lire_contexte_tenant` posés sur ce router dans `main.py`) compte, pour qu'un onglet ne
puisse pas usurper un autre utilisateur en trafiquant sa requête.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/studio-app"
_TIMEOUT = 60.0


def _base() -> str:
    return orchestrateur._brique_base(registre, "studio")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("studio"))
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


async def _page(chemin_brique: str, request: Request) -> HTMLResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}{chemin_brique}", headers=_entetes(request))
    page = (r.text
            .replace('src="/manipulation_directe.js"', f'src="{_PREFIXE}/manipulation_directe.js"')
            .replace("</head>", f"<script>window.STUDIO_API_BASE='{_PREFIXE}';</script></head>"))
    return HTMLResponse(page, status_code=r.status_code)


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def studio_app_racine(request: Request):
    return await _page("/", request)


@router.get(_PREFIXE + "/atelier", response_class=HTMLResponse)
async def studio_app_atelier(request: Request):
    return await _page("/atelier", request)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def studio_app_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes studio (API + `/manipulation_directe.js` +
    `/workplace.css`)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))
```

- [ ] **Step 4: Enregistrer le router dans `core/main.py`**

Dans `core/main.py`, la ligne d'import des routers (ligne 24) :

```python
from routers import agenda, assistant, dashboard, mail_proxy, profil, systeme
```

devient :

```python
from routers import agenda, assistant, dashboard, mail_proxy, profil, studio_proxy, systeme
```

Et juste après la ligne 90 (`app.include_router(mail_proxy.router, ...)`), ajouter :

```python
# Studio (S187) : même motif que mail — session obligatoire + contexte de tenant, pour que
# la tuile Créations soit isolée par personne, cf. core/routers/studio_proxy.py.
app.include_router(studio_proxy.router, dependencies=[Depends(exiger_session)] + _tenant)
```

(Vérifier que le nom du router importé exact est `studio_proxy` pour matcher `core/main.py:24`
et `core/test_studio_proxy.py`'s `from routers import studio_proxy`.)

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest test_studio_proxy.py -v`
Expected: PASS — les 3 tests.

- [ ] **Step 6: `make test-core` complet**

Run: `make test-core` (depuis la racine du monorepo)
Expected: PASS — aucune régression sur les ~464 tests existants + les nouveaux.

- [ ] **Step 7: Commit**

```bash
git add core/routers/studio_proxy.py core/test_studio_proxy.py core/main.py
git commit -m "feat(studio): proxy Cœur /studio-app/* isolé par personne (S187)"
```

---

### Task 6 : `front.html` consomme `STUDIO_API_BASE`

**Files:**
- Modify: `briques/studio/front.html:159-163`
- Test: `briques/studio/test_front.py` (vérifier qu'il reste vert, pas de nouveau test dédié —
  ce changement est un no-op en usage autoporté, motif mail S185)

**Interfaces:**
- Consumes: `window.STUDIO_API_BASE` (posé par Task 5, `studio_app_racine`/`studio_app_atelier`).
- Produces: tous les appels `api(...)` du front (37 sites) passent par le préfixe — AUCUN site
  d'appel à modifier individuellement, un seul changement dans la fonction `api()`.

- [ ] **Step 1: Vérifier le comportement actuel de `test_front.py`**

Run: `cd briques/studio && python3 -m pytest test_front.py -v`
Expected: PASS (avant modification — sert de filet de non-régression).

- [ ] **Step 2: Modifier `api()` dans `front.html`**

Dans `briques/studio/front.html`, remplacer les lignes 155-157 :

```javascript
// Clé API facultative (vente brique seule). Vide = mode ouvert. Lue ?api_key= ou localStorage.
const API_KEY = new URLSearchParams(location.search).get('api_key') || localStorage.getItem('studio_api_key') || '';
const HDR = {'Content-Type':'application/json', ...(API_KEY ? {'X-API-Key': API_KEY} : {})};

async function api(path, method='GET', body=null){
  const r = await fetch(path, {method, headers:HDR, body: body!=null?JSON.stringify(body):null});
```

par :

```javascript
// Clé API facultative (vente brique seule). Vide = mode ouvert. Lue ?api_key= ou localStorage.
const API_KEY = new URLSearchParams(location.search).get('api_key') || localStorage.getItem('studio_api_key') || '';
const HDR = {'Content-Type':'application/json', ...(API_KEY ? {'X-API-Key': API_KEY} : {})};
// Préfixe posé par le proxy Cœur /studio-app/* (S187) : vide en usage autoporté (démo/BYO),
// donc ce changement est un NO-OP hors du proxy — mêmes chemins relatifs qu'avant.
const API_BASE = window.STUDIO_API_BASE || '';

async function api(path, method='GET', body=null){
  const r = await fetch(API_BASE + path, {method, headers:HDR, body: body!=null?JSON.stringify(body):null});
```

- [ ] **Step 3: Vérifier que `test_front.py` reste vert**

Run: `cd briques/studio && python3 -m pytest test_front.py -v`
Expected: PASS — aucune régression (le test sert `front.html` et vérifie sa structure, pas le
comportement runtime JS).

- [ ] **Step 4: Commit**

```bash
git add briques/studio/front.html
git commit -m "feat(studio): front.html consomme STUDIO_API_BASE (S187)"
```

---

### Task 7 : Tuile dashboard pointée sur `/studio-app/`

**Files:**
- Modify: `core/routers/dashboard.py:10,3395-3401,3425`

**Interfaces:**
- Consumes: `/studio-app/` (Task 5).
- Produces: rien de nouveau consommé ailleurs.

- [ ] **Step 1: Retirer l'import inutilisé `STUDIO_KEY`**

Dans `core/routers/dashboard.py`, ligne 10, remplacer :

```python
from urls_ui import GENERATEUR_URL_PUBLIQUE, GEO_KEY, PERSONNAGES_KEY, STUDIO_KEY, url_brique
```

par :

```python
from urls_ui import GENERATEUR_URL_PUBLIQUE, GEO_KEY, PERSONNAGES_KEY, url_brique
```

- [ ] **Step 2: Remplacer le calcul de `studio_ui`**

Dans `core/routers/dashboard.py`, remplacer les lignes 3395-3401 :

```python
    # Si un « compte Studio » (STUDIO_KEY) est configuré, on transporte la clé dans l'URL de
    # l'iframe (?api_key=) pour que le front Studio s'authentifie. Cockpit mono-opérateur :
    # la clé EST l'identité du propriétaire (même frontière de confiance que /dashboard).
    studio_ui = u("STUDIO")
    if STUDIO_KEY:
        sep = "&" if "?" in studio_ui else "?"
        studio_ui = f"{studio_ui}{sep}api_key={STUDIO_KEY}"
```

par :

```python
    # Studio (S187) : vue native via le proxy /studio-app/* du Cœur (même origine, session
    # déjà posée), PAR PERSONNE — PAS l'URL brute + STUDIO_KEY statique (qui retombait sur le
    # même tenant partagé par tout le foyer, trou S183). Motif mail S185.
    studio_ui = "/studio-app/"
```

- [ ] **Step 3: Vérifier que le remplacement de gabarit reste correct**

La ligne 3425 (`.replace("__STUDIO_UI_URL__", studio_ui)`) n'a pas besoin de changer — elle
référence toujours la variable `studio_ui`, dont la valeur est maintenant `/studio-app/`.
Vérifier avec :

Run: `grep -n "studio_ui\|STUDIO_UI_URL" core/routers/dashboard.py`
Expected : 3 lignes — la définition (nouvelle, 1 ligne), et le `.replace(...)` — plus l'usage
dans le HTML (`onclick="ouvrirCreation('__STUDIO_UI_URL__', ...)"`, inchangé).

- [ ] **Step 4: Test manuel du rendu HTML (sans navigateur)**

Run: `cd core && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -c "
import os
os.environ.setdefault('VAULT_SECRET', 'test-secret-0123456789')
os.environ.setdefault('GATEWAY_KEY', 'test')
import sys; sys.path.insert(0, '.')
from routers import dashboard
assert '/studio-app/' in dashboard.DASHBOARD_HTML or True  # gabarit brut, substitution au runtime
print('import ok')
"`
Expected: `import ok` (le fichier s'importe sans erreur de syntaxe).

- [ ] **Step 5: `make test-core` complet**

Run: `make test-core`
Expected: PASS — en particulier tout test qui importe `core/routers/dashboard.py` (aucun test
dédié n'exerce `dashboard()` en détail aujourd'hui au-delà de l'import, donc pas de régression
attendue sur des assertions précises).

- [ ] **Step 6: Commit**

```bash
git add core/routers/dashboard.py
git commit -m "feat(studio): tuile dashboard pointée sur le proxy /studio-app/ (S187)"
```

---

### Task 8 : Vérification finale + mémoire projet

**Files:**
- Modify: `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/sprint-s184-s187-isolation-briques-restantes.md`
- Modify: `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/MEMORY.md`

**Interfaces:**
- Consumes: résultats de toutes les tâches précédentes.
- Produces: rien consommé par du code — mémoire de conversation future uniquement.

- [ ] **Step 1: Suite complète du Cœur**

Run: `make test-core`
Expected: PASS intégral.

- [ ] **Step 2: Suite complète de la brique studio**

Run: `cd briques/studio && python3 -m pytest -v`
Expected: PASS intégral (tous les fichiers `test_*.py` de la brique).

- [ ] **Step 3: Ajouter la section S187 dans le fichier mémoire existant**

Ajouter à la fin de `sprint-s184-s187-isolation-briques-restantes.md` (après la section S186) :

```markdown
## ✅ S187 — studio — CODE + COMMITÉ (2026-07-20)

Dernier des 4 trous de l'audit S183. Spec `docs/superpowers/specs/2026-07-20-s187-studio-isolation-design.md`,
plan `docs/superpowers/plans/2026-07-20-s187-studio-isolation.md`.

**Décisions kickoff** : isolation **par personne** (motif agenda/ecoute/mail/memoire), pas
d'espace partagé par défaut (contrairement à memoire) — une série audio est un projet
personnel. **Périmètre complet** : assistant (outils LLM) + tuile dashboard.

**Ce qui a été fait** :
- `briques/studio/main.py::cle_api()` gagne un 2e dialecte : clé == `STUDIO_KEY` (lue fraîche,
  monkeypatchable) ⇒ identité = `X-User-Id` (repli `perso`). Toute autre clé (`API_KEYS`, vente
  BYO standalone) garde le motif historique — identité = la clé elle-même, inchangé.
- `charger()` (utilisé par ~34 routes — cycles/tomes/personnages/épisodes/arbre/bible/audio)
  centralise le contrôle d'appartenance : 404 (pas 403) si `cree_par` ≠ l'appelant.
  `_identite_effective()` normalise à la LECTURE (jamais réécrit) les valeurs legacy
  (`"public"` ou ancienne `STUDIO_KEY` brute) vers `"perso"` — zéro migration de fichier.
  `lister_series` filtre ; `reordonner_series` ignore silencieusement les id d'autrui.
- `core/outils_communs.BRIQUES_PAR_PERSONNE` += `"studio"` (fixe les capacités manifest
  automatiquement) + `_studio_appel` (helper legacy hors-manifest, utilisé par les outils
  composés personnage→studio) aligné sur `_entetes_brique("studio")`.
- **Nouveau** `core/routers/studio_proxy.py`, proxy `/studio-app/*` (motif mail S185) — studio
  avait un AVANTAGE sur mail : un point d'entrée JS unique (`api()`), donc une seule ligne
  changée dans `front.html` (`API_BASE = window.STUDIO_API_BASE`) au lieu de 13 sites préfixés
  un par un. Tuile dashboard : `/studio-app/` remplace `?api_key=STUDIO_KEY` statique.
- **Tests** : `briques/studio/test_isolation_personne.py` (7, dont legacy et BYO
  non-régression) + `briques/studio/test_auth.py` étendu (3) + `core/test_studio_proxy.py` (3,
  motif `test_mail_proxy.py`) + `core/test_studio_outils.py` étendu (`_studio_appel` forwarde
  X-User-Id) + `core/test_contexte_tenant.py` étendu.
- Pas de déploiement LIVE HP (brique `statut: a_tester`, régime
  [[regime-preuve-docker-differe]]).

**S184→S187 : les 4 trous de l'audit S183 sont maintenant tous CODE+COMMITÉS.**
```

- [ ] **Step 4: Mettre à jour la ligne d'index `MEMORY.md`**

Dans `MEMORY.md`, remplacer la ligne S184-S187 existante par :

```
- [S184→S187 Isolation des briques restantes](sprint-s184-s187-isolation-briques-restantes.md) — suite priorisée de l'audit S183, LES 4 TROUS TRAITÉS. **S184 (ecoute) CODE+MERGÉ main 2026-07-19** ; **S185 (mail) CODE+COMMIT main 2026-07-19 `0d0898e`** (+fix `7fd0419`) ; **S186 (memoire) CODE+COMMIT main 2026-07-19 `846f386`** (+fix `3a012bf`, preuve LIVE faite) ; **S187 (studio) CODE+COMMIT main 2026-07-20** : dialecte STUDIO_KEY par personne + proxy /studio-app/*.
```

- [ ] **Step 5: Vérifier la cohérence**

Run: `grep -n "S187" "/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/MEMORY.md"`
Expected: une ligne trouvée, mentionnant S187 et studio.

(Pas de commit git pour la mémoire — elle vit hors du repo Workplace, dans `~/.claude/projects/...`.)

- [ ] **Step 6: Commit final du sprint (si des fichiers restent non commités)**

Run: `git status`
Expected: `working tree clean` — chaque tâche a déjà commité ses propres fichiers (Tasks 1-7).
Si des fichiers restent (peu probable), les committer avec :

```bash
git add -A
git commit -m "docs(s187): clôture du sprint isolation studio"
```
