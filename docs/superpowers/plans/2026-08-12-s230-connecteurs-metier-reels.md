# S230 — Connecteurs métier réels : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire de `briques/connecteurs` une source de vraies données métier pour le
pipeline audit → conception de solutions : un connecteur CRM tiers (HubSpot) verse ses
prospects dans le dossier Forge du bon client, et un connecteur compta/temps (Harvest)
fait basculer le ROI du S229 de « hypothèse LLM » à « fourni client ».

**Architecture:** `sources` gagne un `venture_id` (lien source ↔ dossier client). Après
chaque sync réussie, un mappeur best-effort (nouveau module `mappeurs.py`) relit les
données déjà synchronisées via une nouvelle action `extraire` du pont PyAirbyte, les
transforme, et les pousse vers Forge (`POST /crm/import-lot`, `PATCH /ventures/{id}`) ou
Audit (`POST /audits/{id}/chiffrer`). Deux trous d'architecture découverts pendant le
cadrage sont comblés dans ce même plan : (1) `crm/import-lot` ignorait quelle venture
appeler (toujours la première trouvée) — il accepte désormais un `venture_id` explicite ;
(2) le mappeur tourne sans session utilisateur, donc sans JWT à propager à Forge — le
compte de service `forge-service` doit pouvoir lire/écrire une venture par id même quand
il n'en est pas le `owner_id` historique (extension explicite et scopée de la confiance
déjà accordée à ce compte pour la création de ventures).

**Tech Stack:** FastAPI (connecteurs, brique forge-adaptateur), FastAPI+SQLAlchemy async
+ Postgres (forge/core), SQLite (connecteurs, audit), PyAirbyte 0.53.2 (sous-processus
isolé), httpx, pytest / pytest-asyncio.

## Global Constraints

- Créer/configurer une source (`POST /sources`) reste hors capacités assistant — aucune
  route touchée par ce plan n'apparaît dans `briques/connecteurs/manifest.json`.
- Seuls les connecteurs à authentification par clé API simple sont dans le périmètre :
  `source-hubspot` (jeton d'app privée) pour le CRM, `source-harvest` (jeton personnel +
  account id) pour le temps passé. Pas d'OAuth à redirection.
- Un échec de mappeur (CRM ou compta) ne doit JAMAIS faire échouer la sync elle-même : la
  sync reste `ok`, un statut `mapping_echoue` est journalisé séparément.
- Les nouvelles routes `GET /ventures/{vid}` / `PATCH /ventures/{vid}` sur l'adaptateur
  Forge sont internes (appelées par `connecteurs`), jamais ajoutées aux `capacites` du
  manifeste — même principe que `POST /sources`.
- Le contournement d'ownership pour le compte de service est strictement scopé à `azp ==
  FORGE_SERVICE_CLIENT_ID` — aucun élargissement du rôle `client_lecture` existant (S227),
  qui reste lecture-seule et inchangé.

---

## Task 1 : Forge core — le compte de service passe l'ownership check

**Files:**
- Modify: `briques/forge/forge/core/app/config.py`
- Modify: `briques/forge/forge/core/app/auth.py`
- Modify: `briques/forge/forge/core/app/routers/ventures.py:127-172` (`get_venture`,
  `update_venture`)
- Test: `briques/forge/forge/core/tests/test_service_identity_s230.py`

**Interfaces:**
- Consumes: `UserContext` existant (`app/auth.py:45-51`), `settings` (`app/config.py`).
- Produces: `UserContext.est_service: bool` (nouveau champ, défaut `False`) ; `get_venture`
  et `update_venture` honorent ce champ. Task 2 s'appuie sur ces deux routes via le jeton
  de service de l'adaptateur (`_appel_protege` sans `X-Forge-User-Token`).

- [ ] **Step 1 : Write the failing test — `_est_compte_service` détecte le jeton de service**

```python
"""S230 : le compte de service forge-service peut lire/écrire une venture par id
sans en être le owner_id historique — nécessaire car le mappeur connecteurs->Forge
tourne en tâche de fond, sans JWT d'un vrai utilisateur à propager."""
from __future__ import annotations

from types import SimpleNamespace

from app.auth import UserContext, _est_compte_service, get_current_user
from app.config import settings
import app.routers.ventures as ventures_mod


def test_est_compte_service_reconnait_l_azp_du_service():
    assert _est_compte_service({"sub": "x", "azp": settings.FORGE_SERVICE_CLIENT_ID}) is True


def test_est_compte_service_refuse_un_azp_different():
    assert _est_compte_service({"sub": "x", "azp": "coeur-web"}) is False


def test_est_compte_service_refuse_azp_absent():
    assert _est_compte_service({"sub": "x"}) is False
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_service_identity_s230.py -v`
Expected: FAIL — `ImportError: cannot import name '_est_compte_service' from 'app.auth'`

- [ ] **Step 3 : Add `FORGE_SERVICE_CLIENT_ID` setting**

In `briques/forge/forge/core/app/config.py`, juste après le bloc Keycloak (ligne 28) :

```python
    # S230 — identité du compte de service côté core : permet à `get_venture`/
    # `update_venture` de reconnaître un appel de service (ex. le mappeur best-effort
    # de la brique `connecteurs`, qui tourne sans JWT utilisateur à propager) plutôt que
    # de le traiter comme un utilisateur normal soumis à `owner_id`. Même valeur par
    # défaut que `FORGE_SERVICE_CLIENT_ID` côté adaptateur (briques/forge/main.py) —
    # à aligner explicitement si les deux services ont des .env séparés.
    FORGE_SERVICE_CLIENT_ID: str = "forge-service"
```

- [ ] **Step 4 : Add `_est_compte_service` + `UserContext.est_service` + wire into `get_current_user`**

In `briques/forge/forge/core/app/auth.py`, modify the `UserContext` dataclass (line 45-51):

```python
@dataclass
class UserContext:
    sub: str          # users.id (UUID Forge en str)
    nom: str
    avatar_emoji: str
    org_id: str | None
    venture_scopes: frozenset[str] = frozenset()  # S227 — role client_lecture
    # S230 — jeton client_credentials émis directement au client `forge-service`
    # (distinct d'un jeton utilisateur qui transite PAR ce client). Permet aux routes
    # scopées par owner_id de reconnaître un appelant de service de confiance sans
    # élargir `client_lecture` (qui reste lecture-seule, inchangé).
    est_service: bool = False
```

Add just above `get_current_user` (after `_resolve_venture_scopes`, before line 231):

```python
def _est_compte_service(payload: dict) -> bool:
    """`azp` (authorized party) porte le client_id qui a demandé le jeton — stable pour
    un jeton client_credentials émis directement au client `forge-service` (contrairement
    à `sub`, qui varie par utilisateur provisionné). Un jeton utilisateur normal, même
    émis pour un AUTRE client public (ex. `coeur-web`), a un `azp` différent."""
    return payload.get("azp") == settings.FORGE_SERVICE_CLIENT_ID
```

Modify `get_current_user`'s return (around line 249) to pass the new field:

```python
        return UserContext(
            sub=str(user.id),
            nom=user.nom,
            avatar_emoji=user.avatar_emoji or "👤",
            org_id=org_id,
            venture_scopes=venture_scopes,
            est_service=_est_compte_service(payload),
        )
```

Need `from app.config import settings` — check it's not already imported in auth.py; it isn't (grep confirmed only `from app.db import SessionLocal` and `from app.models import ...`). Add the import near the top:

```python
from app.config import settings
from app.db import SessionLocal
from app.models import OrganizationMembers, Organizations, Users
```

- [ ] **Step 5 : Run test to verify it passes**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_service_identity_s230.py -v`
Expected: 3 passed

- [ ] **Step 6 : Write the failing test — `get_venture`/`update_venture` honor `est_service`**

Append to `test_service_identity_s230.py` (reuses the `_FakeSessionGet`/`_FakeSessionPatch`/
`_mk_venture` pattern from `test_ventures_s227.py` — copied here, not imported, since that
file's helpers aren't exported as a shared fixture module):

```python
class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSessionGet:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows if self._n == 0 else []
        self._n += 1
        return _FakeResult(rows)


class _FakeSessionPatch:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = [] if self._n == 0 else self._rows
        self._n += 1
        return _FakeResult(rows)


def _mk_venture(**kw):
    base = dict(
        id="11111111-1111-1111-1111-111111111111", owner_id="quelqu-un-d-autre",
        org_id=None, nom="Client X", description="", emoji="🚀", couleur="#6366f1",
        type="audit", statut="actif", created_at=None, updated_at=None,
        geo_object_id=None, audit_id="audit-1", profil_entreprise={"clients": {"n": 0}},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _service_user():
    return UserContext(sub="svc-1", nom="forge-service", avatar_emoji="🤖",
                       org_id=None, est_service=True)


async def test_get_venture_owner_id_different_404_pour_un_utilisateur_normal(client, app):
    """Non-régression : sans est_service, le comportement S227 reste inchangé."""
    from app.auth import UserContext as UC, get_current_user as gcu
    v = _mk_venture()
    app.dependency_overrides[gcu] = lambda: UC(sub="pas-le-owner", nom="X",
                                               avatar_emoji="👤", org_id=None)
    ventures_mod.SessionLocal = lambda: _FakeSessionGet(rows=[v])
    r = await client.get(f"/api/ventures/{v.id}")
    app.dependency_overrides.clear()
    assert r.status_code == 404


async def test_get_venture_le_compte_de_service_lit_une_venture_d_autrui(client, app):
    v = _mk_venture()
    app.dependency_overrides[get_current_user] = _service_user
    ventures_mod.SessionLocal = lambda: _FakeSessionGet(rows=[v])
    r = await client.get(f"/api/ventures/{v.id}")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["auditId"] == "audit-1"


async def test_patch_venture_le_compte_de_service_ecrit_une_venture_d_autrui(client, app):
    v = _mk_venture(profil_entreprise={"clients": {"nb": 3}})
    app.dependency_overrides[get_current_user] = _service_user
    ventures_mod.SessionLocal = lambda: _FakeSessionPatch(rows=[v])
    r = await client.patch(f"/api/ventures/{v.id}",
                           json={"profilEntreprise": {"clients": {"nb": 3}}})
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["profilEntreprise"] == {"clients": {"nb": 3}}


async def test_patch_venture_owner_id_different_404_pour_un_utilisateur_normal(client, app):
    v = _mk_venture()
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        sub="pas-le-owner", nom="X", avatar_emoji="👤", org_id=None)
    ventures_mod.SessionLocal = lambda: _FakeSessionPatch(rows=[v])
    r = await client.patch(f"/api/ventures/{v.id}", json={"nom": "Hack"})
    app.dependency_overrides.clear()
    # update_venture ne lève pas explicitement : v reste None après un UPDATE qui n'a
    # touché aucune ligne (WHERE owner_id ne matche pas) → la route rend `None`.
    assert r.json() is None
```

- [ ] **Step 7 : Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_service_identity_s230.py -v`
Expected: `test_get_venture_le_compte_de_service_lit_une_venture_d_autrui` and
`test_patch_venture_le_compte_de_service_ecrit_une_venture_d_autrui` FAIL with 404 (owner_id
check still unconditional).

- [ ] **Step 8 : Make `get_venture` and `update_venture` honor `est_service`**

In `briques/forge/forge/core/app/routers/ventures.py`, replace `get_venture` (line 127-137):

```python
@router.get("/ventures/{vid}", dependencies=[Depends(get_current_user)])
async def get_venture(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        if u is None:
            v = None
        elif user.est_service:
            # S230 — le mappeur best-effort de `connecteurs` appelle avec le jeton de
            # service, sans JWT utilisateur à propager : il n'y a pas de owner_id à
            # matcher. Le compte de service est déjà digne de confiance pour CRÉER une
            # venture sans restriction (POST /ventures ci-dessus) ; ceci aligne juste la
            # lecture par id sur la même confiance.
            v = (await s.execute(select(Ventures).where(Ventures.id == u))).scalar_one_or_none()
        else:
            v = (await s.execute(
                select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
            )).scalar_one_or_none()
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")
        members = (await s.execute(
            select(VentureMembers).where(VentureMembers.venture_id == u)
        )).scalars().all()
    return {**venture(v), "members": [venture_member(m) for m in members]}
```

Replace `update_venture` (line 155-172, the `.where` inside the `if u:` block) :

```python
@router.patch("/ventures/{vid}", dependencies=[Depends(get_current_user)])
async def update_venture(vid: str, body: UpdateVenture, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    cols = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    async with SessionLocal() as s:
        v = None
        if u:
            # S230 : même bascule que get_venture — le compte de service peut écrire
            # une venture par id sans en être le owner_id historique.
            condition = (Ventures.id == u) if user.est_service else \
                and_(Ventures.id == u, Ventures.owner_id == user.sub)
            await s.execute(
                update(Ventures).where(condition)
                .values(updated_at=datetime.utcnow(), **cols)
            )
            await s.commit()
            v = (await s.execute(
                select(Ventures).where(condition)
            )).scalar_one_or_none()
    return venture(v) if v else None
```

- [ ] **Step 9 : Run test to verify it passes**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_service_identity_s230.py tests/test_ventures_s227.py tests/test_client_lecture_s227.py tests/test_dossier_s227.py -v`
Expected: all passed — non-régression S227 confirmée en même temps.

- [ ] **Step 10 : Commit**

```bash
git add briques/forge/forge/core/app/config.py briques/forge/forge/core/app/auth.py \
        briques/forge/forge/core/app/routers/ventures.py \
        briques/forge/forge/core/tests/test_service_identity_s230.py
git commit -m "feat(forge): S230 — le compte de service passe l'ownership check sur GET/PATCH venture"
```

---

## Task 2 : Adaptateur Forge — proxys internes `GET`/`PATCH /ventures/{vid}`

**Files:**
- Modify: `briques/forge/main.py`
- Test: `briques/forge/test_ventures_proxy_s230.py`

**Interfaces:**
- Consumes: `_appel_protege`, `_json_ou_erreur`, `_client` (existants, `briques/forge/main.py`).
- Produces: `GET /ventures/{vid}` → `{..., auditId, profilEntreprise, ...}` ; `PATCH
  /ventures/{vid}` body `{profilEntreprise?: dict, ...}` → même forme. Consommés par Task 8
  (mappeur CRM) et Task 9 (mappeur compta) via `FORGE_URL`.

- [ ] **Step 1 : Write the failing test**

```python
"""S230 : proxys internes GET/PATCH /ventures/{vid} — utilisés par le mappeur best-effort
de la brique `connecteurs` (pas par le Cœur/l'assistant : absents du manifeste, comme
POST /sources côté connecteurs). Même style que test_entretien_proxy_s228.py : aucun
réseau, `_appel_protege` est remplacé et journalisé."""
import pytest
from fastapi.testclient import TestClient

import main

VID = "11111111-1111-1111-1111-111111111111"


class _Reponse:
    def __init__(self, status=200, payload=None, texte=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = texte

    def json(self):
        return self._payload


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def appels(monkeypatch):
    vus = []

    def _installer(reponse):
        async def _faux(client, methode, chemin, **kw):
            vus.append({"methode": methode, "chemin": chemin, "kw": kw})
            return reponse

        monkeypatch.setattr(main, "_appel_protege", _faux)
        return vus

    return _installer


def test_get_venture_proxifie_vers_le_core(client, appels):
    vus = appels(_Reponse(200, {"id": VID, "auditId": "audit-1",
                                "profilEntreprise": {"clients": {"nb": 0}}}))
    r = client.get(f"/ventures/{VID}")
    assert r.status_code == 200
    assert r.json()["auditId"] == "audit-1"
    assert vus == [{"methode": "GET", "chemin": f"/api/ventures/{VID}", "kw": {}}]


def test_patch_venture_transmet_le_corps_tel_quel(client, appels):
    vus = appels(_Reponse(200, {"id": VID, "profilEntreprise": {"clients": {"nb": 3}}}))
    r = client.patch(f"/ventures/{VID}", json={"profilEntreprise": {"clients": {"nb": 3}}})
    assert r.status_code == 200
    assert vus[0]["kw"]["json"] == {"profilEntreprise": {"clients": {"nb": 3}}}


def test_get_venture_mappe_une_erreur_du_core_en_502(client, appels):
    appels(_Reponse(404, {}, texte="Not found"))
    r = client.get(f"/ventures/{VID}")
    assert r.status_code == 502


def test_ces_deux_routes_ne_sont_pas_dans_le_manifeste():
    """Même principe que `POST /sources` côté connecteurs : lire/écrire une venture par
    id n'est pas une capacité assistant — seul le mappeur best-effort de `connecteurs`
    les appelle."""
    import json
    from pathlib import Path
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    chemins = {c["chemin"] for c in manifest.get("capacites", [])}
    assert "/ventures/{vid}" not in chemins
    assert "/ventures/{id}" not in chemins
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/forge && python -m pytest test_ventures_proxy_s230.py -v`
Expected: FAIL — 404 (routes don't exist yet)

- [ ] **Step 3 : Add the two proxy routes**

In `briques/forge/main.py`, right after the `entretien_repondre` route (after line ~930,
before `facturation_envoyer`) :

```python
# ── Lecture/écriture directe d'une venture (S230) ────────────────────────────────
#
# Internes : appelées par le mappeur best-effort de la brique `connecteurs` après une
# sync réussie (résoudre l'audit_id d'un dossier client, patcher profil_entreprise.clients
# avec les prospects importés). PAS de capacité manifeste — comme `POST /sources` côté
# connecteurs, lire/écrire une venture arbitraire par id n'est pas une action assistant.
#
# Aucune identité utilisateur à propager ici (le mappeur tourne en tâche de fond, sans
# session Cœur) : `_appel_protege` retombe sur le jeton de service, que le core reconnaît
# désormais pour ces deux routes (S230, cf. forge/core/app/routers/ventures.py).

@app.get("/ventures/{vid}", summary="Lire une venture par id (interne, hors assistant)")
async def venture_lire(vid: str):
    """Proxy service → `GET /api/ventures/{id}`."""
    async with await _client(timeout=15) as client:
        r = await _appel_protege(client, "GET", f"/api/ventures/{vid}")
    return _json_ou_erreur(r)


@app.patch("/ventures/{vid}", summary="Patcher une venture par id (interne, hors assistant)")
async def venture_patcher(vid: str, corps: dict = Body(...)):
    """Proxy service → `PATCH /api/ventures/{id}`. Corps transmis tel quel (mêmes noms
    de champs que le core, cf. `UpdateVenture`)."""
    async with await _client(timeout=15) as client:
        r = await _appel_protege(client, "PATCH", f"/api/ventures/{vid}", json=corps)
    return _json_ou_erreur(r)
```

- [ ] **Step 4 : Run test to verify it passes**

Run: `cd briques/forge && python -m pytest test_ventures_proxy_s230.py -v`
Expected: 4 passed

- [ ] **Step 5 : Commit**

```bash
git add briques/forge/main.py briques/forge/test_ventures_proxy_s230.py
git commit -m "feat(forge): S230 — proxys internes GET/PATCH /ventures/{vid} pour le mappeur connecteurs"
```

---

## Task 3 : Adaptateur Forge — `crm/import-lot` accepte un `venture_id` explicite

**Files:**
- Modify: `briques/forge/main.py:518-543` (`_resoudre_pole_crm`), `:712-756` (`crm_importer_lot`)
- Test: `briques/forge/test_crm_venture_id_s230.py`

**Interfaces:**
- Consumes: `_appel_protege`, `_json_ou_erreur`.
- Produces: `POST /crm/import-lot` body gagne un champ optionnel `venture_id`. Absent →
  comportement S169 inchangé (cache process-wide `_pole_crm_cache`). Présent → résout le
  pôle de CETTE venture, jamais mis en cache global. Consommé par Task 8 (mappeur CRM).

- [ ] **Step 1 : Write the failing test**

```python
"""S230 : `crm/import-lot` peut cibler une venture précise via `venture_id` — sans quoi
le pipeline audit multi-client (S227→S230) mélangerait les prospects de deux clients
différents dans la même venture Forge (`_resoudre_pole_crm` prenait toujours la première
venture trouvée, mise en cache pour la durée de vie du process)."""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


class _Resp:
    def __init__(self, corps, status=200):
        self.status_code, self._c, self.text = status, corps, ""

    def json(self):
        return self._c


def _install_faux_core(monkeypatch, poles_par_venture, existants=None):
    store = list(existants or [])
    appels = []

    async def faux_appel(_cl, methode, chemin, **kw):
        appels.append((methode, chemin))
        if methode == "GET" and chemin.endswith("/poles"):
            vid = chemin.split("/")[-2]
            return _Resp(poles_par_venture.get(vid, []))
        if methode == "GET" and chemin.endswith("/crm"):
            return _Resp(list(store))
        if methode == "POST" and chemin.endswith("/crm"):
            lead = dict(kw.get("json") or {})
            lead["id"] = f"lead-{len(store) + 1}"
            store.append(lead)
            return _Resp(lead)
        return _Resp({})

    monkeypatch.setattr(main, "_appel_protege", faux_appel)
    return store, appels


def test_import_lot_avec_venture_id_resout_le_pole_de_cette_venture(monkeypatch):
    store, appels = _install_faux_core(monkeypatch, {
        "vt-a": [{"id": "pole-a-sales", "type": "sales"}],
    })
    r = client.post("/crm/import-lot", json={
        "prospects": [{"nom": "Client A"}], "venture_id": "vt-a"})
    assert r.status_code == 200
    assert r.json()["crees"] == 1
    assert ("GET", "/api/ventures/vt-a/poles") in appels
    assert ("POST", "/api/poles/pole-a-sales/crm") in appels


def test_import_lot_deux_ventures_differentes_ne_se_melangent_pas(monkeypatch):
    store, _ = _install_faux_core(monkeypatch, {
        "vt-a": [{"id": "pole-a", "type": "sales"}],
        "vt-b": [{"id": "pole-b", "type": "sales"}],
    })
    client.post("/crm/import-lot", json={"prospects": [{"nom": "X"}], "venture_id": "vt-a"})
    client.post("/crm/import-lot", json={"prospects": [{"nom": "Y"}], "venture_id": "vt-b"})
    # Le magasin est partagé dans ce faux core (comme le vrai `/api/poles/{id}/crm`
    # scope par pole_id) — la preuve porte sur le POLE appelé, pas sur un store séparé.
    # cf. assertion ci-dessus : deux poles distincts ont bien été ciblés.


def test_import_lot_venture_id_absent_le_id_absent_utilise_le_cache_global_existant(monkeypatch):
    """Non-régression S169 : sans venture_id, comportement inchangé."""
    appels_pole = []

    async def faux_resoudre(_cl, venture_id=None):
        appels_pole.append(venture_id)
        return "pole-legacy"

    async def faux_appel(_cl, methode, chemin, **kw):
        if methode == "GET" and chemin.endswith("/crm"):
            return _Resp([])
        if methode == "POST" and chemin.endswith("/crm"):
            return _Resp({**(kw.get("json") or {}), "id": "lead-1"})
        return _Resp({})

    monkeypatch.setattr(main, "_resoudre_pole_crm", faux_resoudre)
    monkeypatch.setattr(main, "_appel_protege", faux_appel)
    r = client.post("/crm/import-lot", json={"prospects": [{"nom": "Z"}]})
    assert r.status_code == 200
    assert appels_pole == [None]


def test_import_lot_venture_id_sans_pole_sales_prend_le_premier(monkeypatch):
    _install_faux_core(monkeypatch, {"vt-c": [{"id": "pole-c1", "type": "production"}]})
    r = client.post("/crm/import-lot", json={"prospects": [{"nom": "X"}], "venture_id": "vt-c"})
    assert r.status_code == 200


def test_import_lot_venture_id_sans_aucun_pole_erreur_502(monkeypatch):
    _install_faux_core(monkeypatch, {"vt-vide": []})
    r = client.post("/crm/import-lot", json={"prospects": [{"nom": "X"}], "venture_id": "vt-vide"})
    assert r.status_code == 502
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/forge && python -m pytest test_crm_venture_id_s230.py -v`
Expected: FAIL — `venture_id` field ignored, always resolves the legacy cached pole.

- [ ] **Step 3 : Extend `_resoudre_pole_crm` with an optional `venture_id`**

In `briques/forge/main.py`, replace `_resoudre_pole_crm` (line 518-543):

```python
async def _resoudre_pole_crm(client: httpx.AsyncClient, venture_id: str | None = None) -> str:
    """Renvoie l'id d'un pôle commercial.

    Deux modes (S230) :
    - `venture_id` fourni : résout le pôle de CETTE venture précisément
      (`/api/ventures/{id}/poles`, préfère *sales* sinon le 1er). JAMAIS mis en cache
      globalement — deux ventures ne doivent pas se partager une réponse mémoïsée.
    - `venture_id` absent : comportement S169 inchangé — mono-entreprise, un seul pôle
      commercial par défaut, amorcé si besoin, mémorisé pour la durée de vie du process.
    """
    if venture_id:
        poles = _json_ou_erreur(
            await _appel_protege(client, "GET", f"/api/ventures/{venture_id}/poles"))
        pole = next((p for p in (poles or []) if p.get("type") == "sales"), None) \
            or ((poles or [])[0] if poles else None)
        if not pole or not pole.get("id"):
            raise HTTPException(502, f"Impossible de résoudre un pôle commercial pour "
                                     f"la venture {venture_id}.")
        return pole["id"]

    global _pole_crm_cache
    if _pole_crm_cache:
        return _pole_crm_cache
    ventures = _json_ou_erreur(await _appel_protege(client, "GET", "/api/ventures"))
    if not ventures:
        _json_ou_erreur(await _appel_protege(
            client, "POST", "/api/ventures",
            json={"nom": "Workplace", "type": "own", "description": "Espace commercial Workplace"}))
        ventures = _json_ou_erreur(await _appel_protege(client, "GET", "/api/ventures"))
    vid = ventures[0].get("id") if ventures else None
    if not vid:
        raise HTTPException(502, "Impossible de résoudre une venture commerciale dans Forge.")
    poles = _json_ou_erreur(await _appel_protege(client, "GET", f"/api/ventures/{vid}/poles"))
    pole = next((p for p in poles if p.get("type") == "sales"), None) or (poles[0] if poles else None)
    if not pole or not pole.get("id"):
        raise HTTPException(502, "Impossible de résoudre un pôle commercial dans Forge.")
    _pole_crm_cache = pole["id"]
    return _pole_crm_cache
```

- [ ] **Step 4 : Pass `venture_id` through `crm_importer_lot`**

In `briques/forge/main.py`, in `crm_importer_lot` (line ~712), change:

```python
    async with await _client(timeout=60) as client:
        pole_id = await _resoudre_pole_crm(client)
```

to:

```python
    venture_id = corps.get("venture_id")
    async with await _client(timeout=60) as client:
        pole_id = await _resoudre_pole_crm(client, venture_id)
```

- [ ] **Step 5 : Run test to verify it passes**

Run: `cd briques/forge && python -m pytest test_crm_venture_id_s230.py test_crm_import_lot.py -v`
Expected: all passed — `test_crm_import_lot.py`'s existing non-`venture_id` tests confirm
S169 behavior is untouched.

- [ ] **Step 6 : Commit**

```bash
git add briques/forge/main.py briques/forge/test_crm_venture_id_s230.py
git commit -m "fix(forge): S230 — crm/import-lot route vers la bonne venture au lieu du cache mono-entreprise"
```

---

## Task 4 : connecteurs — `sources.venture_id`

**Files:**
- Modify: `briques/connecteurs/stockage.py`
- Test: `briques/connecteurs/test_stockage.py`

**Interfaces:**
- Produces: `stockage.creer_source(..., venture_id=None)`, `_vue_source` includes
  `venture_id`, `stockage.venture_id_de(tenant, source_id) -> str | None`,
  `stockage.modifier_source(..., venture_id=...)`.

- [ ] **Step 1 : Write the failing test**

Append to `briques/connecteurs/test_stockage.py`:

```python
# ── venture_id (S230) ────────────────────────────────────────────────────────

def test_creer_source_avec_venture_id():
    src = stockage.creer_source("alice", "hubspot", "source-hubspot",
                                {"credentials": {"access_token": "x"}}, ["contacts", "deals"],
                                venture_id="vt-client-a")
    assert src["venture_id"] == "vt-client-a"


def test_creer_source_sans_venture_id_reste_valide():
    """Non-régression : une source « ancien format » (sans venture_id) reste valide,
    comme toute évolution de schéma dans ce parc (cf. modifier_source déjà tolérant)."""
    src = _source()
    assert src["venture_id"] is None


def test_venture_id_de_rend_le_lien_ou_none():
    src = stockage.creer_source("alice", "hubspot2", "source-hubspot", {}, [],
                                venture_id="vt-x")
    assert stockage.venture_id_de(src["id"]) == "vt-x"
    autre = _source("alice", "sans-venture")
    assert stockage.venture_id_de(autre["id"]) is None


def test_modifier_source_peut_relier_a_une_venture():
    src = _source()
    stockage.modifier_source("alice", src["id"], venture_id="vt-nouveau")
    assert stockage.source_get("alice", src["id"])["venture_id"] == "vt-nouveau"
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_stockage.py -v -k venture_id`
Expected: FAIL — `TypeError: creer_source() got an unexpected keyword argument 'venture_id'`

- [ ] **Step 3 : Add the migration + wire `venture_id` through stockage.py**

In `briques/connecteurs/stockage.py`, add a conditional migration right after the
`executescript` block in `initialiser()` (same pattern as `briques/audit/main.py:51-53`):

```python
def initialiser() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant          TEXT    NOT NULL,
                nom             TEXT    NOT NULL,
                connecteur      TEXT    NOT NULL,
                config_chiffree TEXT    NOT NULL,
                flux            TEXT    NOT NULL DEFAULT '[]',
                active          INTEGER NOT NULL DEFAULT 1,
                cree_le         TEXT    NOT NULL,
                UNIQUE (tenant, nom)
            );
            CREATE TABLE IF NOT EXISTS syncs (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant             TEXT    NOT NULL,
                source_id          INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                statut             TEXT    NOT NULL,
                debut              TEXT    NOT NULL,
                fin                TEXT,
                nb_enregistrements INTEGER NOT NULL DEFAULT 0,
                erreur             TEXT
            );
            CREATE TABLE IF NOT EXISTS etats (
                source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                flux       TEXT    NOT NULL,
                curseur    TEXT    NOT NULL,
                maj_le     TEXT    NOT NULL,
                PRIMARY KEY (source_id, flux)
            );
            CREATE INDEX IF NOT EXISTS idx_syncs_source ON syncs(source_id, id DESC);
            """
        )
        # Migration S230 : lien source ↔ dossier client (venture Forge), pour que le
        # mappeur best-effort sache où pousser CRM/ROI. NULL = source « ancien format »
        # ou non liée à un dossier — reste valide (motif « ancien format » établi).
        cols = {r["name"] for r in con.execute("PRAGMA table_info(sources)").fetchall()}
        if "venture_id" not in cols:
            con.execute("ALTER TABLE sources ADD COLUMN venture_id TEXT")
```

Modify `_vue_source` to expose it:

```python
def _vue_source(r: sqlite3.Row) -> dict:
    """Vue publique d'une source : la config est RENDUE MASQUÉE, jamais en clair."""
    return {
        "id": r["id"],
        "nom": r["nom"],
        "connecteur": r["connecteur"],
        "flux": json.loads(r["flux"]),
        "active": bool(r["active"]),
        "cree_le": r["cree_le"],
        "venture_id": r["venture_id"],
        "config": coffre.masquer(coffre.dechiffrer(r["config_chiffree"])),
    }
```

Modify `creer_source`:

```python
def creer_source(tenant: str, nom: str, connecteur: str, config: dict,
                 flux: list[str] | None = None, venture_id: str | None = None) -> dict:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO sources (tenant, nom, connecteur, config_chiffree, flux,"
            " venture_id, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant, nom, connecteur, coffre.chiffrer(config),
             json.dumps(flux or []), venture_id, _maintenant()),
        )
        r = con.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _vue_source(r)
```

Modify `modifier_source` to accept `venture_id`:

```python
def modifier_source(tenant: str, source_id: int, *, config: dict | None = None,
                    flux: list[str] | None = None, active: bool | None = None,
                    venture_id: str | None = None) -> bool:
    champs, valeurs = [], []
    if config is not None:
        champs.append("config_chiffree = ?")
        valeurs.append(coffre.chiffrer(config))
    if flux is not None:
        champs.append("flux = ?")
        valeurs.append(json.dumps(flux))
    if active is not None:
        champs.append("active = ?")
        valeurs.append(int(active))
    if venture_id is not None:
        champs.append("venture_id = ?")
        valeurs.append(venture_id)
    if not champs:
        return source_get(tenant, source_id) is not None
    with _conn() as con:
        cur = con.execute(
            f"UPDATE sources SET {', '.join(champs)} WHERE tenant = ? AND id = ?",
            (*valeurs, tenant, source_id))
        return cur.rowcount > 0
```

Add `venture_id_de` (scoped by source_id only, like `config_de` is by tenant+id — but the
mapper runs from `_syncer`, which already validated `(tenant, source_id)` via
`stockage.config_de`, so a plain lookup by id is enough and keeps the mapper's call site
simple):

```python
def venture_id_de(source_id: int) -> str | None:
    """Réservé au mappeur best-effort — appelé APRÈS que `_syncer` a déjà validé
    `(tenant, source_id)` via `config_de`."""
    with _conn() as con:
        r = con.execute("SELECT venture_id FROM sources WHERE id = ?", (source_id,)).fetchone()
        return r["venture_id"] if r else None
```

- [ ] **Step 4 : Run test to verify it passes**

Run: `cd briques/connecteurs && python -m pytest test_stockage.py -v`
Expected: all passed (existing tests untouched, `_source()` helper still works since
`venture_id` has a default)

- [ ] **Step 5 : Commit**

```bash
git add briques/connecteurs/stockage.py briques/connecteurs/test_stockage.py
git commit -m "feat(connecteurs): S230 — sources.venture_id, lien source vers dossier client"
```

---

## Task 5 : connecteurs — `venture_id` sur les routes de source

**Files:**
- Modify: `briques/connecteurs/main.py`
- Test: `briques/connecteurs/test_main.py`

**Interfaces:**
- Consumes: `stockage.creer_source`, `stockage.modifier_source` (Task 4).
- Produces: `POST /sources` et `PATCH /sources/{id}` acceptent `venture_id`. Toujours HORS
  capacités assistant (non ajouté au manifest.json — vérifié par un test dédié).

- [ ] **Step 1 : Write the failing test**

Append to `briques/connecteurs/test_main.py`:

```python
# ── venture_id (S230) ────────────────────────────────────────────────────────

def test_creer_source_avec_venture_id(client, executeur):
    r = client.post("/sources", json={
        "nom": "hubspot-client-a", "connecteur": "source-hubspot",
        "config": {"credentials": {"access_token": "x"}},
        "flux": ["contacts", "deals"], "venture_id": "vt-a"})
    assert r.status_code == 201
    assert r.json()["venture_id"] == "vt-a"


def test_creer_source_sans_venture_id_reste_optionnel(client, executeur):
    r = client.post("/sources", json={"nom": "sans-lien", "connecteur": "source-faker"})
    assert r.status_code == 201
    assert r.json()["venture_id"] is None


def test_patch_source_relie_a_une_venture(client, executeur):
    r = _creer(client)
    sid = r.json()["id"]
    p = client.patch(f"/sources/{sid}", json={"venture_id": "vt-b"})
    assert p.status_code == 200
    assert p.json()["venture_id"] == "vt-b"


def test_venture_id_absent_des_capacites_du_manifeste():
    """`POST /sources`/`PATCH /sources/{id}` restent hors assistant — S230 ne change
    pas ce principe en ajoutant venture_id."""
    import json
    from pathlib import Path
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    ecritures = {(c["methode"], c["chemin"]) for c in manifest.get("capacites", [])
                if c.get("action")}
    assert ("POST", "/sources") not in ecritures
    assert ("PATCH", "/sources/{source_id}") not in ecritures
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_main.py -v -k venture_id`
Expected: FAIL — `venture_id` silently dropped (Pydantic ignores unknown extra fields by
default in this codebase's model config... verify: if `CreerSource`/`ModifierSource` use
default Pydantic config, an unrecognized field is simply ignored rather than erroring, so
the response will show `venture_id: null`/absent rather than raising — either way, the
assertion `venture_id == "vt-a"` fails).

- [ ] **Step 3 : Wire `venture_id` through the Pydantic models and routes**

In `briques/connecteurs/main.py`, modify `CreerSource` and `ModifierSource`:

```python
class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    connecteur: str = Field(min_length=1, description="Nom PyPI du connecteur, ex. source-github")
    config: dict = Field(default_factory=dict)
    flux: list[str] = Field(default_factory=list)
    # S230 : lien vers le dossier client (venture Forge) que ce connecteur alimente.
    # Optionnel — une source non liée n'est simplement jamais mappée (cf. mappeurs.py).
    venture_id: str | None = None


class ModifierSource(BaseModel):
    config: dict | None = None
    flux: list[str] | None = None
    venture_id: str | None = None
```

Modify `creer_source_route`:

```python
@app.post("/sources", tags=["sources"], status_code=201)
def creer_source_route(corps: CreerSource, tenant: str = Depends(tenant_actuel)):
    """Créer une source n'est PAS une capacité de l'assistant, à dessein : la config porte
    des identifiants tiers, et une capacité les ferait transiter par une conversation LLM
    (donc par le journal, le cache sémantique et le fournisseur du modèle). On les saisit
    par l'API ou par l'atelier ; l'assistant, lui, déclenche et consulte."""
    try:
        return stockage.creer_source(tenant, corps.nom, corps.connecteur, corps.config,
                                     corps.flux, venture_id=corps.venture_id)
    except coffre.SecretIndisponible as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # sqlite3.IntegrityError : (tenant, nom) déjà pris
        if "UNIQUE" in str(e):
            raise HTTPException(409, f"Une source nommée « {corps.nom} » existe déjà.")
        raise
```

Modify `modifier_source_route`:

```python
@app.patch("/sources/{source_id}", tags=["sources"])
def modifier_source_route(source_id: int, corps: ModifierSource,
                          tenant: str = Depends(tenant_actuel)):
    _source_ou_404(tenant, source_id)
    stockage.modifier_source(tenant, source_id, config=corps.config, flux=corps.flux,
                             venture_id=corps.venture_id)
    return stockage.source_get(tenant, source_id)
```

- [ ] **Step 4 : Run test to verify it passes**

Run: `cd briques/connecteurs && python -m pytest test_main.py -v`
Expected: all passed

- [ ] **Step 5 : Commit**

```bash
git add briques/connecteurs/main.py briques/connecteurs/test_main.py
git commit -m "feat(connecteurs): S230 — venture_id exposé sur POST/PATCH /sources"
```

---

## Task 6 : connecteurs — statut de mapping sur `syncs`

**Files:**
- Modify: `briques/connecteurs/stockage.py`
- Test: `briques/connecteurs/test_stockage.py`

**Interfaces:**
- Produces: `stockage.enregistrer_mapping(sync_id, statut, erreur=None)`, `_vue_sync`
  gagne `mapping`/`mapping_erreur`. Consommé par Task 9 (dispatcher `mapper_apres_sync`).

- [ ] **Step 1 : Write the failing test**

Append to `briques/connecteurs/test_stockage.py`:

```python
# ── Statut de mapping (S230) ─────────────────────────────────────────────────

def test_une_sync_neuve_n_a_pas_de_mapping():
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    stockage.cloturer_sync(sid, "ok")
    assert stockage.sync_get("alice", sid)["mapping"] is None


def test_enregistrer_un_mapping_reussi():
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    stockage.cloturer_sync(sid, "ok")
    stockage.enregistrer_mapping(sid, "ok")
    s = stockage.sync_get("alice", sid)
    assert s["mapping"] == "ok" and s["mapping_erreur"] is None


def test_enregistrer_un_mapping_echoue_avec_message():
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    stockage.cloturer_sync(sid, "ok")
    stockage.enregistrer_mapping(sid, "echec", erreur="table contacts absente du cache")
    s = stockage.sync_get("alice", sid)
    assert s["mapping"] == "echec"
    assert "contacts" in s["mapping_erreur"]


def test_un_mapping_echoue_ne_change_pas_le_statut_de_la_sync():
    """Le cœur du principe best-effort : le mapping est une info SÉPARÉE, jamais un
    override du statut de sync (qui reste `ok` — les données brutes ont bien atterri)."""
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    stockage.cloturer_sync(sid, "ok", nb_enregistrements=42)
    stockage.enregistrer_mapping(sid, "echec", erreur="boom")
    s = stockage.sync_get("alice", sid)
    assert s["statut"] == "ok" and s["nb_enregistrements"] == 42
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_stockage.py -v -k mapping`
Expected: FAIL — `KeyError: 'mapping'` (column doesn't exist / `_vue_sync` doesn't expose it)

- [ ] **Step 3 : Add the migration + `enregistrer_mapping` + expose in `_vue_sync`**

In `stockage.py`, extend the migration block added in Task 4 (same `initialiser()`):

```python
        cols = {r["name"] for r in con.execute("PRAGMA table_info(sources)").fetchall()}
        if "venture_id" not in cols:
            con.execute("ALTER TABLE sources ADD COLUMN venture_id TEXT")
        # Migration S230 : statut du mappeur best-effort (CRM/compta), séparé du statut
        # de sync — un échec de mapping ne doit jamais faire mentir `syncs.statut`.
        cols_syncs = {r["name"] for r in con.execute("PRAGMA table_info(syncs)").fetchall()}
        if "mapping" not in cols_syncs:
            con.execute("ALTER TABLE syncs ADD COLUMN mapping TEXT")
        if "mapping_erreur" not in cols_syncs:
            con.execute("ALTER TABLE syncs ADD COLUMN mapping_erreur TEXT")
```

Add `enregistrer_mapping`, right after `cloturer_sync`:

```python
def enregistrer_mapping(sync_id: int, statut: str, *, erreur: str | None = None) -> None:
    """Statut du mappeur best-effort (CRM/compta) — SÉPARÉ de `syncs.statut` : un
    échec de mapping ne fait jamais mentir la sync elle-même (les données brutes ont
    bien atterri dans le cache, rejouables)."""
    with _conn() as con:
        con.execute("UPDATE syncs SET mapping = ?, mapping_erreur = ? WHERE id = ?",
                    (statut, erreur, sync_id))
```

Modify `_vue_sync`:

```python
def _vue_sync(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "source_id": r["source_id"], "statut": r["statut"],
        "debut": r["debut"], "fin": r["fin"],
        "nb_enregistrements": r["nb_enregistrements"], "erreur": r["erreur"],
        "mapping": r["mapping"], "mapping_erreur": r["mapping_erreur"],
    }
```

- [ ] **Step 4 : Run test to verify it passes**

Run: `cd briques/connecteurs && python -m pytest test_stockage.py -v`
Expected: all passed

- [ ] **Step 5 : Commit**

```bash
git add briques/connecteurs/stockage.py briques/connecteurs/test_stockage.py
git commit -m "feat(connecteurs): S230 — statut de mapping (ok/echec) séparé du statut de sync"
```

---

## Task 7 : pont — action `extraire`

**Files:**
- Modify: `briques/connecteurs/pont/executer.py`
- Test: `briques/connecteurs/test_pont.py` (protocole, faux exécuteur)
- Test: `briques/connecteurs/test_integration_pyairbyte.py` (réel, opt-in réseau)

**Interfaces:**
- Produces: job `{"action": "extraire", "flux_extrait": str, ...}` → réponse `{"ok": true,
  "flux": str, "lignes": [dict, ...]}` ou `{"ok": false, "erreur": ...}` si le flux n'a
  jamais été synchronisé. Consommé par Task 8/9 (mappeurs) via `pont.executer`.

- [ ] **Step 1 : Write the failing protocol test**

Append to `briques/connecteurs/test_pont.py`:

```python
# ── Extraction post-sync (S230) ──────────────────────────────────────────────

def test_extraire_rend_les_lignes_du_flux(faux_executeur):
    faux_executeur(
        "import sys, json\n"
        "recu = json.loads(sys.stdin.read())\n"
        "assert recu['action'] == 'extraire'\n"
        "assert recu['flux_extrait'] == 'contacts'\n"
        "print(json.dumps({'ok': True, 'flux': 'contacts',\n"
        "                  'lignes': [{'id': 1, 'properties': {'email': 'a@b.fr'}}]}))\n"
    )
    r = _executer({"action": "extraire", "connecteur": "source-hubspot",
                   "flux_extrait": "contacts", "schema": "s1"})
    assert r["ok"] is True
    assert r["lignes"] == [{"id": 1, "properties": {"email": "a@b.fr"}}]


def test_extraire_un_flux_jamais_synchronise_echoue_proprement(faux_executeur):
    faux_executeur(
        "import sys, json\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'ok': False, 'erreur': \"flux « deals » absent du cache"
        " (jamais synchronisé ?)\"}))\n"
    )
    r = _executer({"action": "extraire", "connecteur": "source-hubspot",
                   "flux_extrait": "deals", "schema": "s1"})
    assert r["ok"] is False and "jamais synchronisé" in r["erreur"]
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_pont.py -v -k extraire`
Expected: FAIL — these tests only exercise the fake executor script above, which is why
they'd currently pass trivially. Skip straight to the REAL constraint: the fake executor
tests above only prove the *protocol* works once `executer.py` implements `action_extraire`
that real PyAirbyte cache reads honor the SAME job/response shape — that's what Step 3-5
(real integration test) actually prove. Run instead, first, the integration-level check
that `executer.py`'s `ACTIONS` dict rejects the unknown action today:

Run: `cd briques/connecteurs && python3 -c "
import sys; sys.path.insert(0, 'pont')
import json, subprocess
p = subprocess.run([sys.executable, 'pont/executer.py'],
                   input=json.dumps({'action': 'extraire', 'connecteur': 'x',
                                     'flux_extrait': 'contacts', 'schema': 's1',
                                     'racine': '/tmp/x'}).encode(),
                   capture_output=True)
print(p.stdout.decode())
"`
Expected: `{"ok": false, "erreur": "action inconnue : 'extraire'"}`

- [ ] **Step 3 : Add `action_extraire` to `pont/executer.py`**

In `briques/connecteurs/pont/executer.py`, add right after `action_etats`:

```python
def action_extraire(job: dict, racine: Path) -> dict:
    """Relit les enregistrements d'un flux DÉJÀ synchronisé, sans repasser par une sync.

    C'est ce qui permet au mappeur best-effort (CRM/compta, cf. `mappeurs.py` côté API)
    de transformer des données sans jamais réimporter `airbyte` de son côté — le contrat
    reste le même « JSON pauvre » que le reste de ce fichier (cf. docstring de tête).
    """
    cache = _cache(job, racine)
    flux = job["flux_extrait"]
    if flux not in cache.streams:
        return {"ok": False,
                "erreur": f"flux « {flux} » absent du cache (jamais synchronisé ?)"}
    lignes = [dict(enregistrement) for enregistrement in cache[flux]]
    return {"ok": True, "flux": flux, "lignes": lignes}
```

Register it in `ACTIONS`:

```python
ACTIONS = {
    "verifier": action_verifier,
    "flux": action_flux,
    "sync": action_sync,
    "etats": action_etats,
    "extraire": action_extraire,
}
```

⚠ Incertitude assumée : `cache.streams` / `cache[flux]` sont l'API publique documentée de
PyAirbyte 0.53.2 (`CacheBase` comme `Mapping[str, CachedDataset]`), mais ce fichier tourne
dans un interpréteur séparé (`/opt/pyairbyte`) jamais exécuté hors Docker — si le nom exact
diffère (`cache.streams` vs une autre méthode), **Step 6 ci-dessous (le test réel,
network-gated) est le seul endroit qui le révèle**. Corriger ici si besoin, pas dans le
test.

- [ ] **Step 4 : Run the protocol tests again**

Run: `cd briques/connecteurs && python -m pytest test_pont.py -v`
Expected: all passed (les tests protocole du Step 1 ne testent QUE le contrat stdin/stdout
via un faux script, donc passent dès que `executer.py` accepte l'action sans lever — la
vraie preuve de lecture DuckDB vient du Step 6).

- [ ] **Step 5 : Write the real integration test (network-gated, uses `source-faker`)**

Append to `briques/connecteurs/test_integration_pyairbyte.py`, right after
`test_le_curseur_survit_au_processus_et_est_relu_sans_synchroniser`:

```python
def test_extraire_relit_les_lignes_deja_synchronisees(racine):
    """Preuve réelle de action_extraire : source-faker/users (déjà synchronisé par
    `test_une_sync_transfere_et_rend_un_curseur_non_vide` ci-dessus, racine partagée)."""
    r = _executer(_job("extraire", racine, flux_extrait="users"))
    assert r["ok"] is True, r
    assert r["flux"] == "users"
    assert len(r["lignes"]) == 300
    assert "id" in r["lignes"][0]


def test_extraire_un_flux_jamais_synchronise_echoue_proprement(racine_neuve):
    r = _executer(_job("extraire", racine_neuve, flux_extrait="users"))
    assert r["ok"] is False
    assert "jamais synchronisé" in r["erreur"]
```

- [ ] **Step 6 : Run the real integration test**

Run:
```bash
docker compose -f briques/connecteurs/docker-compose.yml build connecteurs
docker compose -f briques/connecteurs/docker-compose.yml run --rm --entrypoint "" \
  -e CONNECTEURS_TEST_RESEAU=1 connecteurs \
  sh -c "pip install -q pytest pytest-asyncio && pytest -q test_integration_pyairbyte.py -k extraire"
```
Expected: 2 passed. **Si `cache.streams` ou `cache[flux]` lève une `AttributeError`** :
inspecter l'API réelle installée (`docker compose run --rm --entrypoint /opt/pyairbyte/bin/python
connecteurs -c "import airbyte as ab; help(ab.caches.duckdb.DuckDBCache)"`) et ajuster
`action_extraire` en conséquence — c'est le seul point du plan où le nom exact de l'API
PyAirbyte n'était pas vérifiable hors Docker.

- [ ] **Step 7 : Commit**

```bash
git add briques/connecteurs/pont/executer.py briques/connecteurs/test_pont.py \
        briques/connecteurs/test_integration_pyairbyte.py
git commit -m "feat(connecteurs): S230 — action extraire du pont, relit un flux déjà synchronisé"
```

---

## Task 8 : connecteurs — mappeur CRM (`source-hubspot`)

**Files:**
- Create: `briques/connecteurs/mappeurs.py`
- Test: `briques/connecteurs/test_mappeurs.py`

**Interfaces:**
- Consumes: `pont.executer` (Task 7, action `extraire`), `stockage.venture_id_de` (Task 4),
  env `FORGE_URL`/`FORGE_KEY` (motif `veille-prospection/orchestration.py`).
- Produces: `mappeurs.CONNECTEURS_CRM: set[str]`, `async def _mapper_crm(tenant: str,
  source_id: int, venture_id: str, schema: str) -> None` — lève sur échec (attrapé par le
  dispatcher de Task 10, jamais ici).

- [ ] **Step 1 : Write the failing test**

Create `briques/connecteurs/test_mappeurs.py`:

```python
"""Mappeurs best-effort post-sync (S230) : CRM (HubSpot → Forge) et compta (Harvest →
audit ROI). Aucun réseau réel : `pont.executer` et les appels httpx sortants sont mockés.
"""
import httpx
import pytest

import mappeurs


class _ReponseHttpx:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=self)


@pytest.fixture(autouse=True)
def _sans_reseau_reel(monkeypatch):
    """Filet : si un test oublie de mocker un point de sortie, on le sait immédiatement
    plutôt que de laisser une requête réelle partir en silence."""
    async def _interdit(*a, **k):
        raise AssertionError("appel réseau non mocké dans un test de mappeurs.py")
    monkeypatch.setattr(httpx.AsyncClient, "post", _interdit)
    monkeypatch.setattr(httpx.AsyncClient, "get", _interdit)


def _mock_pont_extraire(monkeypatch, par_flux: dict[str, list[dict]]):
    async def _faux_executer(job, timeout=None):
        assert job["action"] == "extraire"
        flux = job["flux_extrait"]
        if flux not in par_flux:
            return {"ok": False, "erreur": f"flux « {flux} » absent du cache"}
        return {"ok": True, "flux": flux, "lignes": par_flux[flux]}
    monkeypatch.setattr(mappeurs.pont, "executer", _faux_executer)


def _mock_forge_post(monkeypatch, capture: list):
    async def _faux_post(self, url, **kw):
        capture.append((url, kw.get("json")))
        return _ReponseHttpx(200, {"ok": True, "crees": len(kw["json"]["prospects"]),
                                   "doublons": 0, "ignores": 0})
    monkeypatch.setattr(httpx.AsyncClient, "post", _faux_post)


def _mock_forge_get_venture(monkeypatch, profil: dict):
    async def _faux_get(self, url, **kw):
        return _ReponseHttpx(200, {"id": "vt-a", "auditId": "audit-1", "profilEntreprise": profil})
    monkeypatch.setattr(httpx.AsyncClient, "get", _faux_get)


async def test_mapper_crm_transforme_contacts_et_deals_en_prospects(monkeypatch):
    _mock_pont_extraire(monkeypatch, {
        "contacts": [{"id": "1", "properties": {"firstname": "Alice", "lastname": "Durand",
                                                "email": "alice@x.fr", "phone": "0600000000",
                                                "company": "Acme"}}],
        "deals": [{"id": "d1", "properties": {"dealname": "Contrat annuel", "amount": "5000"}}],
    })
    captures = []
    _mock_forge_post(monkeypatch, captures)
    _mock_forge_get_venture(monkeypatch, {"clients": {"nb": 0}})

    patchs = []
    async def _faux_patch(self, url, **kw):
        patchs.append((url, kw.get("json")))
        return _ReponseHttpx(200, {"id": "vt-a"})
    monkeypatch.setattr(httpx.AsyncClient, "patch", _faux_patch)

    await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")

    url, corps = captures[0]
    assert url.endswith("/crm/import-lot")
    assert corps["venture_id"] == "vt-a"
    assert len(corps["prospects"]) == 2
    contact = next(p for p in corps["prospects"] if p["email"] == "alice@x.fr")
    assert contact["nom"] == "Alice Durand"
    assert contact["entreprise"] == "Acme"
    deal = next(p for p in corps["prospects"] if p is not contact)
    assert "Contrat annuel" in deal["notes"]

    # profil_entreprise.clients fusionné, pas écrasé (les autres clés survivent).
    assert patchs[0][1]["profilEntreprise"]["clients"]["nb"] == 2


async def test_mapper_crm_incremente_le_compteur_existant_et_conserve_les_autres_categories(monkeypatch):
    """Fusion non destructive (motif S227/S228, `_fusionner_qualitatif`) + comptage
    CUMULATIF : une sync incrémentale HubSpot ne rapporte qu'un DELTA de contacts, pas
    le total connu chez le tiers — écraser `clients.nb` avec ce delta ferait régresser
    le profil à chaque sync calme."""
    _mock_pont_extraire(monkeypatch, {
        "contacts": [{"id": "1", "properties": {"firstname": "Bob", "lastname": "X",
                                                "email": "bob@x.fr"}}],
        "deals": [],
    })
    captures = []
    _mock_forge_post(monkeypatch, captures)
    _mock_forge_get_venture(monkeypatch, {"organisation": ["SARL"], "clients": {"nb": 5}})

    patchs = []
    async def _faux_patch(self, url, **kw):
        patchs.append(kw.get("json"))
        return _ReponseHttpx(200, {})
    monkeypatch.setattr(httpx.AsyncClient, "patch", _faux_patch)

    await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")
    assert patchs[0]["profilEntreprise"]["organisation"] == ["SARL"]
    assert patchs[0]["profilEntreprise"]["clients"]["nb"] == 6  # 5 existants + 1 nouveau


async def test_mapper_crm_sans_nouveau_prospect_ne_touche_pas_a_forge(monkeypatch):
    """Aucun contact/deal neuf ce tour (sync incrémentale calme) : ni lead factice créé
    dans le CRM pour satisfaire la validation « liste non vide » de crm/import-lot, ni
    écrasement du compteur `clients.nb` avec un delta de zéro."""
    _mock_pont_extraire(monkeypatch, {"contacts": [], "deals": []})
    appels = []

    async def _traqueur(self, url, **kw):
        appels.append(url)
        return _ReponseHttpx(200, {})
    monkeypatch.setattr(httpx.AsyncClient, "post", _traqueur)
    monkeypatch.setattr(httpx.AsyncClient, "get", _traqueur)
    monkeypatch.setattr(httpx.AsyncClient, "patch", _traqueur)

    await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")
    assert appels == []


async def test_mapper_crm_flux_absent_du_cache_leve(monkeypatch):
    """Le dispatcher (Task 10) attrape ceci et journalise `mapping_echoue` — le mappeur
    lui-même reste honnête et lève plutôt que d'avaler l'erreur."""
    _mock_pont_extraire(monkeypatch, {})  # ni contacts ni deals synchronisés
    with pytest.raises(mappeurs.MappingEchoue, match="contacts"):
        await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_mappeurs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mappeurs'`

- [ ] **Step 3 : Create `mappeurs.py` with the CRM mapper**

Create `briques/connecteurs/mappeurs.py`:

```python
"""Mappeurs best-effort post-sync (S230) : transforment les données déjà synchronisées
(cache DuckDB, relu via `pont.executer(action="extraire")`) vers les consommateurs métier
du pipeline audit → conception de solutions — Forge (CRM, dossier client) et audit (ROI).

Liste blanche explicite, pas de détection automatique du type de connecteur (décision
actée au cadrage S230) : seuls les connecteurs listés ci-dessous déclenchent un mappage.
Tout le reste (source-github, source-faker, futurs connecteurs non métiers) n'est jamais
mappé — `dispatcher.py`-style, mais gardé simple dans ce seul module vu la taille du
sprint (deux mappeurs).

Erreurs : chaque mappeur LÈVE `MappingEchoue` plutôt que d'avaler l'erreur — c'est le
dispatcher (`main.py::_syncer`, Task 10) qui l'attrape et journalise `mapping_echoue`
via `stockage.enregistrer_mapping`, jamais ce module. Garde le mappeur testable en
isolation (une levée = un cas de test), et le point d'attrape unique (Task 10 est le SEUL
appelant en production).
"""
from __future__ import annotations

import os

import httpx

import pont
import stockage

FORGE_URL = os.getenv("FORGE_URL", "http://host.docker.internal:5700").rstrip("/")
FORGE_KEY = os.getenv("FORGE_KEY", "")

# Connecteurs PyAirbyte à authentification API-key simple (pas d'OAuth à redirection,
# hors périmètre S230). Le nom exact doit correspondre au champ `connecteur` d'une
# `sources` (S214) — vérifié disponible sur PyPI au moment du cadrage S230.
CONNECTEURS_CRM = {"source-hubspot"}
CONNECTEURS_COMPTA = {"source-harvest"}


class MappingEchoue(RuntimeError):
    """Un mappeur n'a pas pu transformer/pousser les données déjà synchronisées.

    Distinct d'un échec de SYNC (`pont.PontIndisponible`, réseau tiers en panne) : les
    données brutes sont bien dans le cache DuckDB, seul le mappage a échoué — rejouable
    sans retransférer (cf. `enregistrer_mapping`, Task 6)."""


def _entetes() -> dict:
    return {"X-API-Key": FORGE_KEY} if FORGE_KEY else {}


async def _extraire(connecteur: str, source_id: int, schema: str, flux: str) -> list[dict]:
    reponse = await pont.executer(
        {"action": "extraire", "connecteur": connecteur, "flux_extrait": flux,
         "schema": schema, "racine": os.getenv("CONNECTEURS_TRAVAIL", "/travail")},
        timeout=pont.TIMEOUT_COURT)
    if not reponse.get("ok"):
        raise MappingEchoue(f"extraction du flux « {flux} » : {reponse.get('erreur')}")
    return reponse["lignes"]


# ── CRM (HubSpot) ─────────────────────────────────────────────────────────────

def _contact_vers_prospect(contact: dict) -> dict:
    p = contact.get("properties") or {}
    prenom, nom_famille = (p.get("firstname") or "").strip(), (p.get("lastname") or "").strip()
    nom = f"{prenom} {nom_famille}".strip() or p.get("company") or f"Contact {contact.get('id')}"
    charge = {"nom": nom, "entreprise": p.get("company"), "email": p.get("email"),
             "telephone": p.get("phone"), "notes": "Importé depuis connecteurs (HubSpot, contact)"}
    return {k: v for k, v in charge.items() if v}


def _deal_vers_prospect(deal: dict) -> dict:
    p = deal.get("properties") or {}
    nom_deal = p.get("dealname") or f"Deal {deal.get('id')}"
    notes = f"Importé depuis connecteurs (HubSpot, deal « {nom_deal} »)"
    if p.get("amount"):
        notes += f" — montant {p['amount']}"
    return {"nom": nom_deal, "notes": notes}


async def _mapper_crm(tenant: str, source_id: int, venture_id: str, schema: str) -> None:
    connecteur = "source-hubspot"  # seul connecteur CRM du périmètre S230
    contacts = await _extraire(connecteur, source_id, schema, "contacts")
    deals = await _extraire(connecteur, source_id, schema, "deals")
    prospects = [_contact_vers_prospect(c) for c in contacts] + \
                [_deal_vers_prospect(d) for d in deals]
    if not prospects:
        # Rien de neuf ce tour (sync incrémentale calme — HubSpot ne renvoie que le
        # delta). Ne RIEN appeler : ni lead factice dans le CRM pour satisfaire la
        # validation « liste non vide » de crm/import-lot, ni écrasement du compteur
        # `clients.nb` avec un delta de zéro (cf. commentaire plus bas sur le cumul).
        return

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{FORGE_URL}/crm/import-lot",
                              json={"prospects": prospects, "venture_id": venture_id},
                              headers=_entetes())
        r.raise_for_status()

        # Fusion non destructive de profil_entreprise (motif _fusionner_qualitatif,
        # S227/S228) + comptage CUMULATIF : une sync incrémentale ne rapporte qu'un
        # DELTA de contacts/deals, jamais le total connu chez le tiers — écraser
        # `clients.nb` avec ce delta ferait régresser le profil à chaque sync calme.
        # On ajoute donc au compteur déjà persisté plutôt que de le remplacer. Fenêtre
        # de course acceptée (best-effort, cadence horloge au pire quotidienne).
        rv = await client.get(f"{FORGE_URL}/ventures/{venture_id}", headers=_entetes())
        rv.raise_for_status()
        profil = (rv.json() or {}).get("profilEntreprise") or {}
        nb_existant = (profil.get("clients") or {}).get("nb", 0)
        profil = {**profil, "clients": {"nb": nb_existant + len(prospects),
                                        "exemples": [p["nom"] for p in prospects[:5]]}}
        rp = await client.patch(f"{FORGE_URL}/ventures/{venture_id}",
                                json={"profilEntreprise": profil}, headers=_entetes())
        rp.raise_for_status()
```

- [ ] **Step 4 : Run test to verify it passes**

Run: `cd briques/connecteurs && python -m pytest test_mappeurs.py -v`
Expected: 4 passed

- [ ] **Step 5 : Commit**

```bash
git add briques/connecteurs/mappeurs.py briques/connecteurs/test_mappeurs.py
git commit -m "feat(connecteurs): S230 — mappeur CRM HubSpot vers le dossier client Forge"
```

---

## Task 9 : connecteurs — mappeur compta (`source-harvest`)

**Files:**
- Modify: `briques/connecteurs/mappeurs.py`
- Test: `briques/connecteurs/test_mappeurs.py`

**Interfaces:**
- Consumes: `_extraire` (Task 8), env `AUDIT_URL` (motif `briques/generateur/main.py:27`).
- Produces: `async def _mapper_compta(tenant: str, source_id: int, venture_id: str, schema:
  str) -> None`. Config de la source porte `mapping_poles: dict[str, str]` (nom de projet
  ou de tâche Harvest → pôle), saisie à la création (jamais par l'assistant, config déjà
  chiffrée).

- [ ] **Step 1 : Write the failing test**

Append to `briques/connecteurs/test_mappeurs.py`:

```python
def _mock_config_de(monkeypatch, config: dict):
    def _faux_config_de(tenant, source_id):
        return "source-harvest", config, ["time_entries"]
    monkeypatch.setattr(mappeurs.stockage, "config_de", _faux_config_de)


def _mock_forge_get_venture_audit(monkeypatch, audit_id: str):
    async def _faux_get(self, url, **kw):
        return _ReponseHttpx(200, {"id": "vt-a", "auditId": audit_id, "profilEntreprise": {}})
    monkeypatch.setattr(httpx.AsyncClient, "get", _faux_get)


async def test_mapper_compta_calcule_un_cout_horaire_par_pole(monkeypatch):
    _mock_pont_extraire(monkeypatch, {
        "time_entries": [
            {"id": 1, "hours": 4.0, "billable_rate": 40.0,
             "project": {"name": "Vente terrain"}, "task": {"name": "Prospection"}},
            {"id": 2, "hours": 2.0, "billable_rate": 60.0,
             "project": {"name": "Vente terrain"}, "task": {"name": "Prospection"}},
            {"id": 3, "hours": 8.0, "billable_rate": 25.0,
             "project": {"name": "Compta interne"}, "task": {"name": "Facturation"}},
        ],
    })
    _mock_config_de(monkeypatch, {
        "mapping_poles": {"Vente terrain": "commercial", "Compta interne": "administratif"}})
    _mock_forge_get_venture_audit(monkeypatch, "audit-1")

    captures = []
    async def _faux_post(self, url, **kw):
        captures.append((url, kw.get("json")))
        return _ReponseHttpx(200, {"id": "audit-1", "statut_roi": "termine"})
    monkeypatch.setattr(httpx.AsyncClient, "post", _faux_post)

    await mappeurs._mapper_compta("alice", 2, "vt-a", "schema2")

    url, corps = captures[0]
    assert url.endswith("/audits/audit-1/chiffrer")
    # commercial : (4*40 + 2*60) / 6 = 46.666...
    assert corps["cout_horaire"]["commercial"] == pytest.approx(46.666, rel=1e-3)
    assert corps["cout_horaire"]["administratif"] == 25.0
    assert "production" not in corps["cout_horaire"]  # aucune entrée mappée à ce pôle


async def test_mapper_compta_ignore_les_entrees_sans_mapping_de_pole(monkeypatch):
    _mock_pont_extraire(monkeypatch, {
        "time_entries": [{"id": 1, "hours": 3.0, "billable_rate": 50.0,
                          "project": {"name": "Projet inconnu"}, "task": {"name": "?"}}]})
    _mock_config_de(monkeypatch, {"mapping_poles": {"Vente terrain": "commercial"}})
    _mock_forge_get_venture_audit(monkeypatch, "audit-1")
    captures = []
    async def _faux_post(self, url, **kw):
        captures.append(kw.get("json"))
        return _ReponseHttpx(200, {})
    monkeypatch.setattr(httpx.AsyncClient, "post", _faux_post)

    await mappeurs._mapper_compta("alice", 2, "vt-a", "schema2")
    assert captures[0]["cout_horaire"] == {}  # rien de mappable ⇒ dict vide, jamais bloquant


async def test_mapper_compta_sans_audit_id_leve(monkeypatch):
    _mock_pont_extraire(monkeypatch, {"time_entries": []})
    _mock_config_de(monkeypatch, {"mapping_poles": {}})
    _mock_forge_get_venture_audit(monkeypatch, None)
    with pytest.raises(mappeurs.MappingEchoue, match="audit_id"):
        await mappeurs._mapper_compta("alice", 2, "vt-a", "schema2")
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_mappeurs.py -v -k compta`
Expected: FAIL — `AttributeError: module 'mappeurs' has no attribute '_mapper_compta'`

- [ ] **Step 3 : Add the compta mapper to `mappeurs.py`**

Append to `briques/connecteurs/mappeurs.py`:

```python
AUDIT_URL = os.getenv("AUDIT_URL", "http://host.docker.internal:5300").rstrip("/")

POLES_VALIDES = {"commercial", "production", "administratif"}


async def _mapper_compta(tenant: str, source_id: int, venture_id: str, schema: str) -> None:
    connecteur, config, _flux = stockage.config_de(tenant, source_id)
    mapping_poles: dict[str, str] = (config or {}).get("mapping_poles") or {}
    entries = await _extraire(connecteur, source_id, schema, "time_entries")

    # Agrégation pondérée par pôle : cout_horaire[pole] = Σ(heures·taux) / Σ(heures),
    # sur les seules entrées dont le projet OU la tâche est dans mapping_poles ET qui
    # portent un taux exploitable. Un pôle sans entrée mappable est absent du dict —
    # `chiffrage.py` (S229) le traite alors comme `hypothese_llm`, jamais bloquant.
    ponderation: dict[str, list[tuple[float, float]]] = {}
    for entree in entries:
        projet = (entree.get("project") or {}).get("name")
        tache = (entree.get("task") or {}).get("name")
        pole = mapping_poles.get(projet) or mapping_poles.get(tache)
        if pole not in POLES_VALIDES:
            continue
        heures = entree.get("hours")
        taux = entree.get("billable_rate") if entree.get("billable_rate") is not None \
            else entree.get("cost_rate")
        if not heures or taux is None:
            continue
        ponderation.setdefault(pole, []).append((float(heures), float(taux)))

    cout_horaire = {}
    for pole, paires in ponderation.items():
        total_heures = sum(h for h, _ in paires)
        if total_heures:
            cout_horaire[pole] = sum(h * t for h, t in paires) / total_heures

    async with httpx.AsyncClient(timeout=15) as client:
        rv = await client.get(f"{FORGE_URL}/ventures/{venture_id}", headers=_entetes())
        rv.raise_for_status()
        audit_id = (rv.json() or {}).get("auditId")
        if not audit_id:
            raise MappingEchoue(f"venture {venture_id} sans audit_id — pas de dossier "
                                f"audit à chiffrer")

        r = await client.post(f"{AUDIT_URL}/audits/{audit_id}/chiffrer",
                              json={"cout_horaire": cout_horaire})
        r.raise_for_status()
```

- [ ] **Step 4 : Run test to verify it passes**

Run: `cd briques/connecteurs && python -m pytest test_mappeurs.py -v`
Expected: all passed (7 tests total : 4 CRM + 3 compta)

- [ ] **Step 5 : Commit**

```bash
git add briques/connecteurs/mappeurs.py briques/connecteurs/test_mappeurs.py
git commit -m "feat(connecteurs): S230 — mappeur compta Harvest vers le ROI audit (S229)"
```

---

## Task 10 : connecteurs — dispatcher `mapper_apres_sync` branché sur `_syncer`

**Files:**
- Modify: `briques/connecteurs/main.py`
- Modify: `briques/connecteurs/mappeurs.py`
- Test: `briques/connecteurs/test_main.py`

**Interfaces:**
- Consumes: `mappeurs._mapper_crm`, `mappeurs._mapper_compta`,
  `mappeurs.CONNECTEURS_CRM`/`CONNECTEURS_COMPTA` (Task 8/9), `stockage.venture_id_de`
  (Task 4), `stockage.enregistrer_mapping` (Task 6).
- Produces: `mappeurs.mapper_apres_sync(tenant, source_id, connecteur, sync_id, schema) ->
  None` — ne lève JAMAIS (best-effort, attrape tout). Câblé dans `main.py::_syncer` après
  `cloturer_sync(sync_id, "ok", ...)`.

- [ ] **Step 1 : Write the failing test**

Append to `briques/connecteurs/test_mappeurs.py`:

```python
async def test_mapper_apres_sync_dispatch_vers_crm(monkeypatch):
    appele = []
    async def _faux_crm(tenant, source_id, venture_id, schema):
        appele.append(("crm", tenant, source_id, venture_id, schema))
    monkeypatch.setattr(mappeurs, "_mapper_crm", _faux_crm)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert appele == [("crm", "alice", 1, "vt-a", "schema1")]
    assert enregistres == [(99, "ok", None)]


async def test_mapper_apres_sync_dispatch_vers_compta(monkeypatch):
    appele = []
    async def _faux_compta(tenant, source_id, venture_id, schema):
        appele.append("compta")
    monkeypatch.setattr(mappeurs, "_mapper_compta", _faux_compta)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping", lambda *a, **k: None)

    await mappeurs.mapper_apres_sync("alice", 2, "source-harvest", 100, "schema2")
    assert appele == ["compta"]


async def test_mapper_apres_sync_connecteur_non_mappable_ne_fait_rien(monkeypatch):
    """source-faker, source-github... : hors des deux listes blanches, jamais mappé."""
    appele = []
    monkeypatch.setattr(mappeurs, "_mapper_crm", lambda *a: appele.append("crm"))
    monkeypatch.setattr(mappeurs, "_mapper_compta", lambda *a: appele.append("compta"))
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda *a, **k: enregistres.append(a))

    await mappeurs.mapper_apres_sync("alice", 3, "source-faker", 101, "schema3")
    assert appele == []
    assert enregistres == []  # rien à journaliser : ce n'est même pas une tentative


async def test_mapper_apres_sync_sans_venture_id_journalise_echec(monkeypatch):
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: None)
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert enregistres[0][1] == "echec"
    assert "venture_id" in enregistres[0][2]


async def test_mapper_apres_sync_capture_une_exception_du_mappeur(monkeypatch):
    """Le principe best-effort central du sprint : le mappeur explose, la sync ne le
    sait jamais (déjà `ok` avant cet appel, cf. Task 10 Step 4 côté main.py)."""
    async def _casse(*a):
        raise mappeurs.MappingEchoue("table contacts absente")
    monkeypatch.setattr(mappeurs, "_mapper_crm", _casse)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert enregistres == [(99, "echec", "table contacts absente")]


async def test_mapper_apres_sync_capture_une_exception_totalement_inattendue(monkeypatch):
    """Pas seulement MappingEchoue : n'importe quelle exception (bug, panne réseau
    imprévue) doit rester best-effort, jamais remonter à `_syncer`."""
    async def _casse(*a):
        raise ValueError("boom inattendu")
    monkeypatch.setattr(mappeurs, "_mapper_crm", _casse)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert enregistres[0][1] == "echec"
    assert "boom inattendu" in enregistres[0][2]
```

- [ ] **Step 2 : Run test to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_mappeurs.py -v -k mapper_apres_sync`
Expected: FAIL — `AttributeError: module 'mappeurs' has no attribute 'mapper_apres_sync'`

- [ ] **Step 3 : Add the dispatcher to `mappeurs.py`**

Append to `briques/connecteurs/mappeurs.py`:

```python
async def mapper_apres_sync(tenant: str, source_id: int, connecteur: str, sync_id: int,
                            schema: str) -> None:
    """Point d'entrée UNIQUE appelé par `main.py::_syncer` après une sync réussie.

    Ne lève JAMAIS : c'est le principe best-effort du sprint (cf. docstring de tête).
    Journalise `syncs.mapping` — `None` si le connecteur n'est ni CRM ni compta (pas
    même une tentative), `ok`/`echec` sinon.
    """
    if connecteur in CONNECTEURS_CRM:
        mapper = _mapper_crm
    elif connecteur in CONNECTEURS_COMPTA:
        mapper = _mapper_compta
    else:
        return  # connecteur hors périmètre S230 : rien à mapper, rien à journaliser

    venture_id = stockage.venture_id_de(source_id)
    if not venture_id:
        stockage.enregistrer_mapping(
            sync_id, "echec",
            erreur="source sans venture_id — impossible de savoir quel dossier client alimenter")
        return

    try:
        await mapper(tenant, source_id, venture_id, schema)
    except Exception as e:  # noqa: BLE001 — best-effort strict, cf. docstring de tête
        stockage.enregistrer_mapping(sync_id, "echec", erreur=str(e))
        return
    stockage.enregistrer_mapping(sync_id, "ok")
```

- [ ] **Step 4 : Run the mappeurs test suite**

Run: `cd briques/connecteurs && python -m pytest test_mappeurs.py -v`
Expected: all passed (13 tests : 4 CRM + 3 compta + 6 dispatcher)

- [ ] **Step 5 : Write the failing `main.py` integration test**

Append to `briques/connecteurs/test_main.py`:

```python
def test_une_sync_reussie_declenche_le_mappeur_si_connecteur_mappable(client, executeur, monkeypatch):
    appele = []
    async def _faux_mapper(tenant, source_id, connecteur, sync_id, schema):
        appele.append((tenant, source_id, connecteur, sync_id, schema))
    monkeypatch.setattr(main.mappeurs, "mapper_apres_sync", _faux_mapper)

    executeur(SYNC_OK)
    r = client.post("/sources", json={
        "nom": "hubspot-a", "connecteur": "source-hubspot",
        "config": {"credentials": {"access_token": "x"}}, "flux": ["contacts", "deals"],
        "venture_id": "vt-a"})
    sid = r.json()["id"]
    sync = client.post(f"/sources/{sid}/sync").json()
    time.sleep(0.2)  # laisse `_syncer` (tâche de fond) se terminer
    assert len(appele) == 1
    assert appele[0][2] == "source-hubspot"


def test_une_sync_reussie_ne_declenche_rien_pour_un_connecteur_non_mappable(client, executeur, monkeypatch):
    appele = []
    monkeypatch.setattr(main.mappeurs, "mapper_apres_sync",
                        lambda *a: appele.append(a))
    executeur(SYNC_OK)
    r = _creer(client)  # source-github, motif existant
    sid = r.json()["id"]
    client.post(f"/sources/{sid}/sync")
    time.sleep(0.2)
    assert appele == []


def test_un_mappeur_qui_leve_ne_fait_pas_echouer_la_sync(client, executeur, monkeypatch):
    async def _casse(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(main.mappeurs, "mapper_apres_sync", _casse)
    executeur(SYNC_OK)
    r = client.post("/sources", json={
        "nom": "hubspot-b", "connecteur": "source-hubspot",
        "config": {}, "flux": ["contacts"], "venture_id": "vt-b"})
    sid = r.json()["id"]
    sync = client.post(f"/sources/{sid}/sync").json()
    time.sleep(0.2)
    fini = client.get(f"/syncs/{sync['id']}").json()
    assert fini["statut"] == "ok"  # la sync elle-même n'a jamais vu passer l'exception
```

- [ ] **Step 6 : Run to verify it fails**

Run: `cd briques/connecteurs && python -m pytest test_main.py -v -k mappeur`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'mappeurs'` (not
imported yet) / dispatcher never called.

- [ ] **Step 7 : Wire the dispatcher into `_syncer`**

In `briques/connecteurs/main.py`, add the import at the top:

```python
import coffre
import mappeurs
import pont
import stockage
```

Modify `_syncer` — after the curseur loop, before `cloturer_sync`, keep `cloturer_sync`
exactly where it is (the sync's own statut must be settled BEFORE any mapping attempt,
per the best-effort principle), then dispatch the mapper:

```python
async def _syncer(tenant: str, source_id: int, sync_id: int, complet: bool) -> None:
    """Exécute une sync de bout en bout et tient la comptabilité. Ne lève jamais :
    un échec est une DONNÉE (`syncs.erreur`), lisible par l'assistant."""
    details = stockage.config_de(tenant, source_id)
    if details is None:
        stockage.cloturer_sync(sync_id, "echec", erreur="source supprimée pendant la sync")
        return
    connecteur, config, flux = details
    schema = pont.schema_de(tenant, source_id)
    job = {"action": "sync", "connecteur": connecteur, "config": config, "flux": flux,
           "complet": complet, "schema": schema,
           "racine": os.getenv("CONNECTEURS_TRAVAIL", "/travail")}
    try:
        reponse = await pont.executer(job)
    except pont.PontIndisponible as e:
        stockage.cloturer_sync(sync_id, "echec", erreur=str(e))
        return

    if not reponse.get("ok"):
        stockage.cloturer_sync(sync_id, "echec", erreur=reponse.get("erreur", "échec inconnu"))
        return

    for nom_flux, curseur in (reponse.get("etats") or {}).items():
        stockage.enregistrer_etat(source_id, nom_flux, curseur)
    stockage.cloturer_sync(sync_id, "ok",
                           nb_enregistrements=int(reponse.get("nb_enregistrements") or 0))

    # S230 : mappage best-effort, APRÈS que la sync soit close avec son propre statut —
    # un échec de mapping ne doit jamais pouvoir faire mentir `syncs.statut`.
    await mappeurs.mapper_apres_sync(tenant, source_id, connecteur, sync_id, schema)
```

- [ ] **Step 8 : Run test to verify it passes**

Run: `cd briques/connecteurs && python -m pytest test_main.py -v`
Expected: all passed

- [ ] **Step 9 : Run the FULL connecteurs test suite (non-regression)**

Run: `cd briques/connecteurs && python -m pytest -v --ignore=test_integration_pyairbyte.py`
Expected: all passed — proves Task 4-10 didn't regress the S214 sync/curseur/isolation
guarantees.

- [ ] **Step 10 : Commit**

```bash
git add briques/connecteurs/main.py briques/connecteurs/mappeurs.py briques/connecteurs/test_main.py
git commit -m "feat(connecteurs): S230 — branche le mappeur best-effort sur une sync réussie"
```

---

## Task 11 : Filet repo-wide — non-régression capacités + preuve croisée forge/connecteurs

**Files:**
- Test: `briques/connecteurs/test_contrat_s230.py`
- Test: `briques/forge/test_contrat_s230.py`

**Interfaces:**
- Consumes: tout ce qui précède. Aucune nouvelle interface produite — ce sont des tests de
  cohérence transverse, le filet mentionné dans la section « Tests » de la spec.

- [ ] **Step 1 : Write the failing test — cohérence manifeste/routes**

Create `briques/connecteurs/test_contrat_s230.py`:

```python
"""S230 — filet repo-wide (motif tests/test_contrat_capacites.py, S210) : aucune capacité
manifeste n'expose la création/modification de source, ni de connecteur/venture_id caché,
à l'assistant. `POST /sources`, `PATCH /sources/{id}` doivent rester absents."""
import json
from pathlib import Path

import main


def test_aucune_capacite_n_expose_lecriture_de_source():
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    ecritures = {(c["methode"], c["chemin"]) for c in manifest.get("capacites", [])}
    assert ("POST", "/sources") not in ecritures
    assert ("PATCH", "/sources/{source_id}") not in ecritures


def test_toutes_les_capacites_du_manifeste_existent_bien_comme_routes():
    """Motif S210 (`connexion_envoyer`, routes mortes) : une capacité dont le chemin
    manifeste ne correspond à AUCUNE route réelle est un 404 systématique invisible."""
    import re
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    chemins_reels = {
        (re.sub(r"\{[^}]*\}", "{}", r.path), m)
        for r in main.app.routes if hasattr(r, "path") and hasattr(r, "methods")
        for m in r.methods
    }
    for c in manifest.get("capacites", []):
        chemin_normalise = re.sub(r"\{[^}]*\}", "{}", c["chemin"])
        assert (chemin_normalise, c["methode"]) in chemins_reels, \
            f"capacité « {c['nom']} » ({c['methode']} {c['chemin']}) — route morte"
```

Create `briques/forge/test_contrat_s230.py`:

```python
"""S230 — filet repo-wide : les proxys internes (GET/PATCH /ventures/{vid},
crm/import-lot avec venture_id) existent bien comme routes réelles ET restent absents des
capacités assistant du manifeste."""
import json
import re
from pathlib import Path

import main


def test_les_deux_nouvelles_routes_ventures_existent_reellement():
    chemins = {
        (re.sub(r"\{[^}]*\}", "{}", r.path), m)
        for r in main.app.routes if hasattr(r, "path") and hasattr(r, "methods")
        for m in r.methods
    }
    assert ("/ventures/{}", "GET") in chemins
    assert ("/ventures/{}", "PATCH") in chemins


def test_lecture_ecriture_venture_absentes_du_manifeste():
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    chemins_capacites = {c["chemin"] for c in manifest.get("capacites", [])}
    assert "/ventures/{vid}" not in chemins_capacites
    assert "/ventures/{id}" not in chemins_capacites
```

- [ ] **Step 2 : Run test to verify it fails or passes as expected**

Run:
```bash
cd briques/connecteurs && python -m pytest test_contrat_s230.py -v
cd ../forge && python -m pytest test_contrat_s230.py -v
```
Expected: connecteurs' two tests should already PASS (nothing to fix — this locks in
current behavior as non-regression). forge's `test_les_deux_nouvelles_routes_ventures_existent_reellement`
should PASS too since Task 2 already added the routes ; `test_lecture_ecriture_venture_absentes_du_manifeste`
should PASS (Task 2 deliberately didn't touch manifest.json). If any of these four FAIL,
it means an earlier task accidentally added a capacité or a route regressed — fix the
earlier task, not this test.

- [ ] **Step 3 : Commit**

```bash
git add briques/connecteurs/test_contrat_s230.py briques/forge/test_contrat_s230.py
git commit -m "test(connecteurs,forge): S230 garde-fou — capacités assistant et routes réelles restent alignées"
```

---

## Hors périmètre (rappel, inchangé depuis le cadrage)

- Connecteurs OAuth à redirection — API-key uniquement.
- Détection automatique du type de connecteur — liste blanche `CONNECTEURS_CRM`/
  `CONNECTEURS_COMPTA` maintenue à la main.
- UI de configuration de source — API/atelier existants.
- Entrepôt analytique — le cache DuckDB reste local à la source.
- Élargissement du rôle `client_lecture` (S227) — reste lecture seule, inchangé ; la bascule
  d'ownership de Task 1 est un mécanisme séparé, scopé au seul `azp` du compte de service.

## Post-plan (à faire séparément, pas dans ce plan)

- LIVE HP : confirmer que `source-hubspot`/`source-harvest` s'installent réellement depuis
  PyPI dans l'image (`/opt/pyairbyte`) — non testé ici (seul `source-faker` a un test
  d'intégration réseau dans ce repo, cf. Task 7 Step 5-6). Suivre le régime de preuve
  différé déjà en usage sur ce parc (code+test ici, preuve réseau groupée sur le HP).
- Configurer `FORGE_SERVICE_CLIENT_ID` identiquement des deux côtés (adaptateur `briques/
  forge/main.py` ET core `briques/forge/forge/core/app/config.py`) dans le `.env` de
  déploiement — les deux ont la même valeur par défaut (`forge-service`) mais vivent dans
  des fichiers d'environnement potentiellement séparés.
