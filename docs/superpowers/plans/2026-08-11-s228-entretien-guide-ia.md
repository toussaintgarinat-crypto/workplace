# S228 — Entretien guidé IA — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un entretien guidé (squelette fixe de 13 sections, relance dynamique pilotée par LLM) qui alimente `Ventures.profil_entreprise` (fusion non destructive) et pousse le transcript vers `briques/audit` via `briques/ingestion`, avec pause/reprise obligatoire et routage structurel côté Cœur.

**Architecture:** Nouveau router Forge (`entretiens.py`, table `entretiens`) qui expose démarrer/répondre/terminer/état. Le Cœur route structurellement les tours de conversation d'un fil où un entretien est actif directement vers `/entretien/repondre` (bypass du LLM tool-calling), via un nouveau module `core/entretien_routage.py` activé quand la capacité manifest `forge_entretien_demarrer` est appelée avec succès.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (Forge, Python), FastAPI (Cœur, Python), Postgres (Forge), LLM one-shot via `app.llm.generate_text` (Forge) pour extraction qualitative + décision de relance.

## Global Constraints

- Dépend de S227 (déjà mergé sur `main`) : `Ventures.geo_object_id/audit_id/profil_entreprise` (JSONB), 9 catégories qualitatives sans accent : `organisation`, `activites`, `clients`, `fournisseurs`, `outils_utilises`, `personnel`, `contraintes`, `objectifs`, `problemes_connus`.
- `briques/audit` n'a AUCUNE écriture incrémentale (`POST /auditer` = analyse en un seul bloc) — ne pas y toucher, décision actée dans le design S228.
- Fusion de `profil_entreprise` : JAMAIS d'écrasement. `PATCH /ventures/{id}` existant (S227) REMPLACE `profil_entreprise` en bloc — ne pas le réutiliser pour l'entretien, écrire un read-modify-write dédié dans le nouveau router.
- `POST /documents/import` d'ingestion NE PROPAGE PAS `venture_id` (`stockage.importer`, `briques/ingestion/stockage.py:105-128`, absent de l'INSERT) — utiliser exclusivement `POST /ingerer` (multipart, `venture_id` en `Form`) pour pousser le transcript.
- Auth des nouveaux endpoints Forge : propriétaire de la venture UNIQUEMENT (`Ventures.owner_id == user.sub`), jamais `client_lecture` — ce rôle est lecture seule scopée (cf. `app/auth.py:54-69`, fix Critical S227).
- Convention `_uuid` : chaque router Forge définit sa propre fonction locale `_uuid(v)` (dupliquée ~50×, `briques/forge/forge/core/app/routers/*.py`) — ne pas importer celle de `ventures.py`.
- Convention manual models Forge : PK `Uuid` + `server_default=text("gen_random_uuid()")` (pas `TEXT PRIMARY KEY` malgré le sketch SQL du spec) — cf. `app/models/manual.py`.
- Une table 100% neuve n'a besoin d'AUCUNE entrée dans `MIGRATIONS_S227`/nouvelle liste de migrations — `Base.metadata.create_all(checkfirst=True)` dans `scripts/init_db.py:57` la crée automatiquement dès qu'elle hérite de `Base` (cf. `VentureDeleteTokens`/`PoleDevRequests`/`DecisionsN0` qui n'ont aucune ligne dans `MIGRATIONS_S227`).
- Tests Forge : pas de vraie DB (`conftest.py` fixe juste `DATABASE_URL` pour que `check_pg()` échoue proprement) — toujours des fakes (`_FakeSession`, monkeypatch `SessionLocal`, monkeypatch `httpx.AsyncClient.get/post` au niveau CLASSE, monkeypatch `generate_text` au niveau du MODULE routeur : `app.routers.entretiens.generate_text`).
- Tests Cœur : jamais de TestClient/ASGI complet pour le flux SSE — tester les fonctions pures/async directement (cf. `test_assistant_routes.py`, `test_gate_action_bout_en_bout.py`, `test_converser_stream.py`).
- `"niveau": 1` sur les capacités manifest est actuellement un NO-OP tant que `PORTE_PROGRESSIVE` (env, défaut `"0"`) n'est pas activé (`core/outils.py:322,362-366`) — l'inclure quand même (conforme au spec), documenté comme dormant.

---

## File Structure

**Forge** (`briques/forge/forge/core/`) :
- `app/models/manual.py` — ajoute `Entretiens` (modèle SQLAlchemy, table neuve)
- `app/models/__init__.py` — exporte `Entretiens`
- `app/serde.py` — ajoute `entretien(r)` (sérialisation camelCase)
- `app/routers/entretiens.py` — NOUVEAU : squelette de sections + 4 endpoints + helpers de clôture
- `app/main.py` — monte le nouveau router
- `../../manifest.json` (`briques/forge/manifest.json`) — 2 nouvelles capacités
- `tests/test_models_s228.py` — NOUVEAU
- `tests/test_entretiens_s228.py` — NOUVEAU

**Cœur** (`core/`) :
- `entretien_routage.py` — NOUVEAU : registre en mémoire (fil_accord → venture active), détection pause, appel structurel à Forge
- `assistant.py` — hook dans la boucle d'outils : active le registre quand `forge_entretien_demarrer` réussit
- `routers/assistant.py` — interception avant `assistant.converser` : si un entretien est actif et non en pause, route directement vers Forge
- `test_entretien_routage.py` — NOUVEAU
- `test_entretien_routage_hook.py` — NOUVEAU (hook dans `assistant.converser`)

---

## Task 1 : Forge — modèle `Entretiens`

**Files:**
- Modify: `briques/forge/forge/core/app/models/manual.py`
- Modify: `briques/forge/forge/core/app/models/__init__.py`
- Test: `briques/forge/forge/core/tests/test_models_s228.py`

**Interfaces:**
- Produces: `app.models.Entretiens` (colonnes : `id`, `venture_id`, `section_courante`, `sections_couvertes`, `transcript`, `statut`, `sync_erreur`, `derniere_activite`, `created_at`)

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_models_s228.py
"""S228 : table entretiens (état de l'entretien guidé IA)."""
from app.models.manual import Entretiens


def test_entretiens_a_les_bonnes_colonnes():
    colonnes = set(Entretiens.__table__.columns.keys())
    assert colonnes == {
        "id", "venture_id", "section_courante", "sections_couvertes",
        "transcript", "statut", "sync_erreur", "derniere_activite", "created_at",
    }


def test_entretiens_tablename():
    assert Entretiens.__tablename__ == "entretiens"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_models_s228.py -v`
Expected: FAIL with `ImportError: cannot import name 'Entretiens'`

- [ ] **Step 3: Add the model**

In `briques/forge/forge/core/app/models/manual.py`, add `JSONB` to the sqlalchemy import line:

```python
from sqlalchemy import Boolean, DateTime, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
```

Then append at the end of the file:

```python
class Entretiens(Base):
    """S228 — état de l'entretien guidé IA (une ligne par entretien en cours/terminé).

    Table neuve : aucune entrée dans MIGRATIONS_S227/S228 nécessaire, `create_all`
    (scripts/init_db.py) la crée seule (même motif que VentureDeleteTokens ci-dessus).
    """
    __tablename__ = "entretiens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    venture_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    section_courante: Mapped[str] = mapped_column(Text, nullable=False)
    sections_couvertes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    transcript: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    statut: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'en_cours'"))
    # Renseigné best-effort si ingestion/audit injoignables à la clôture (jamais bloquant).
    sync_erreur: Mapped[str | None] = mapped_column(Text)
    derniere_activite: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
```

- [ ] **Step 4: Export it**

In `briques/forge/forge/core/app/models/__init__.py`, add `Entretiens` to the `from app.models.manual import (...)` block (alphabetical, same place as `DecisionsN0`) and to the `__all__` list.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_models_s228.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add briques/forge/forge/core/app/models/manual.py briques/forge/forge/core/app/models/__init__.py briques/forge/forge/core/tests/test_models_s228.py
git commit -m "feat(forge): S228 — table entretiens (modèle SQLAlchemy, création auto)"
```

---

## Task 2 : Forge — squelette de sections + serde

**Files:**
- Create: `briques/forge/forge/core/app/routers/entretiens.py`
- Modify: `briques/forge/forge/core/app/serde.py`
- Test: `briques/forge/forge/core/tests/test_entretiens_s228.py`

**Interfaces:**
- Produces: `SECTIONS: list[dict]` (13 entrées, champs `id`/`famille`/`categorie` ou `zone`/`premiere_question`), `_section(section_id) -> dict | None`, `_prochaine_section(couvertes: list[str]) -> dict | None`, `serde.entretien(r) -> dict`
- Consumes: rien (module autonome à ce stade)

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_entretiens_s228.py (nouveau fichier, sections ajoutées au fil du plan)
"""S228 : entretien guidé IA."""
from __future__ import annotations

import app.routers.entretiens as entretiens_mod


def test_squelette_a_9_qualitatif_et_4_processus():
    familles = [s["famille"] for s in entretiens_mod.SECTIONS]
    assert familles.count("qualitatif") == 9
    assert familles.count("processus") == 4
    assert len(entretiens_mod.SECTIONS) == 13


def test_squelette_categories_qualitatif_s227():
    cats = {s["categorie"] for s in entretiens_mod.SECTIONS if s["famille"] == "qualitatif"}
    assert cats == {
        "organisation", "activites", "clients", "fournisseurs", "outils_utilises",
        "personnel", "contraintes", "objectifs", "problemes_connus",
    }


def test_prochaine_section_renvoie_la_premiere_non_couverte():
    premiere = entretiens_mod.SECTIONS[0]["id"]
    deuxieme = entretiens_mod.SECTIONS[1]["id"]
    assert entretiens_mod._prochaine_section([])["id"] == premiere
    assert entretiens_mod._prochaine_section([premiere])["id"] == deuxieme


def test_prochaine_section_renvoie_none_si_squelette_complet():
    tous = [s["id"] for s in entretiens_mod.SECTIONS]
    assert entretiens_mod._prochaine_section(tous) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.routers.entretiens'`

- [ ] **Step 3: Write the module skeleton**

```python
# briques/forge/forge/core/app/routers/entretiens.py
"""Router entretiens (S228) — entretien guidé IA, greffé sur Forge à côté de Ventures.

Squelette de sections FIXE (garde-fou) : deux familles jamais mélangées dans le
traitement d'une réponse.
- « qualitatif » : les 9 catégories du profil_entreprise (S227) — extraction LLM
  ciblée, patch direct (fusion non destructive, jamais d'écrasement).
- « processus » : les 4 zones de la vision (Commercial/Production/Administratif/
  Communication) — accumulées en transcript brut, analysées par briques/audit
  (aucune écriture incrémentale là-bas, décision actée S228).

Dans chaque section, le LLM décide de la relance (réponse courte → question de
suivi ciblée) ; il ne quitte une section que si elle est jugée suffisamment
couverte. Pause/reprise obligatoire : l'état est persisté à chaque tour.
"""

from __future__ import annotations

SECTIONS: list[dict] = [
    {"id": "qualitatif.organisation", "famille": "qualitatif", "categorie": "organisation",
     "premiere_question": "Comment votre entreprise est-elle organisée (statut juridique, effectif, structure) ?"},
    {"id": "qualitatif.activites", "famille": "qualitatif", "categorie": "activites",
     "premiere_question": "Quelles sont vos activités principales ?"},
    {"id": "qualitatif.clients", "famille": "qualitatif", "categorie": "clients",
     "premiere_question": "Qui sont vos clients types ?"},
    {"id": "qualitatif.fournisseurs", "famille": "qualitatif", "categorie": "fournisseurs",
     "premiere_question": "Quels sont vos principaux fournisseurs ou partenaires ?"},
    {"id": "qualitatif.outils_utilises", "famille": "qualitatif", "categorie": "outils_utilises",
     "premiere_question": "Quels outils ou logiciels utilisez-vous au quotidien ?"},
    {"id": "qualitatif.personnel", "famille": "qualitatif", "categorie": "personnel",
     "premiere_question": "Parlez-moi de votre équipe : effectif, rôles clés."},
    {"id": "qualitatif.contraintes", "famille": "qualitatif", "categorie": "contraintes",
     "premiere_question": "Quelles contraintes fortes pèsent sur votre activité (réglementaires, saisonnières...) ?"},
    {"id": "qualitatif.objectifs", "famille": "qualitatif", "categorie": "objectifs",
     "premiere_question": "Quels sont vos objectifs pour les 12 prochains mois ?"},
    {"id": "qualitatif.problemes_connus", "famille": "qualitatif", "categorie": "problemes_connus",
     "premiere_question": "Quels problèmes avez-vous déjà identifiés dans votre organisation ?"},
    {"id": "processus.commercial", "famille": "processus", "zone": "commercial",
     "premiere_question": "Comment arrive une demande client, de la prospection jusqu'au devis ?"},
    {"id": "processus.production", "famille": "processus", "zone": "production",
     "premiere_question": "Comment se déroule une intervention, du planning au compte rendu ?"},
    {"id": "processus.administratif", "famille": "processus", "zone": "administratif",
     "premiere_question": "Comment gérez-vous la facturation et les documents administratifs ?"},
    {"id": "processus.communication", "famille": "processus", "zone": "communication",
     "premiere_question": "Quels canaux utilisez-vous pour communiquer (email, téléphone, SMS, réseaux sociaux) ?"},
]

_PAR_ID = {s["id"]: s for s in SECTIONS}


def _section(section_id: str) -> dict | None:
    return _PAR_ID.get(section_id)


def _prochaine_section(couvertes: list[str]) -> dict | None:
    """Première section du squelette pas encore dans `couvertes`, ou None si complet."""
    deja = set(couvertes or ())
    for s in SECTIONS:
        if s["id"] not in deja:
            return s
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the serde function (test + code together, it's a 1-line-body pure function)**

Add to `tests/test_entretiens_s228.py`:

```python
from types import SimpleNamespace
from app.serde import entretien


def test_serde_entretien_camel_case():
    r = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        venture_id="22222222-2222-2222-2222-222222222222",
        section_courante="qualitatif.organisation",
        sections_couvertes=["qualitatif.activites"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=None, created_at=None,
    )
    d = entretien(r)
    assert d["sectionCourante"] == "qualitatif.organisation"
    assert d["sectionsCouvertes"] == ["qualitatif.activites"]
    assert d["ventureId"] == "22222222-2222-2222-2222-222222222222"
    assert d["statut"] == "en_cours"
    assert d["syncErreur"] is None
```

In `briques/forge/forge/core/app/serde.py`, add near `venture_member`:

```python
def entretien(r) -> dict:
    return {
        "id": _sid(r.id),
        "ventureId": _sid(r.venture_id),
        "sectionCourante": r.section_courante,
        "sectionsCouvertes": r.sections_couvertes,
        "transcript": r.transcript,
        "statut": r.statut,
        "syncErreur": r.sync_erreur,
        "derniereActivite": iso(r.derniere_activite),
        "createdAt": iso(r.created_at),
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add briques/forge/forge/core/app/routers/entretiens.py briques/forge/forge/core/app/serde.py briques/forge/forge/core/tests/test_entretiens_s228.py
git commit -m "feat(forge): S228 — squelette de sections (13, garde-fou) + serde entretien"
```

---

## Task 3 : Forge — `POST /ventures/{vid}/entretien/demarrer`

**Files:**
- Modify: `briques/forge/forge/core/app/routers/entretiens.py`
- Modify: `briques/forge/forge/core/app/main.py`
- Test: `briques/forge/forge/core/tests/test_entretiens_s228.py`

**Interfaces:**
- Consumes: `SECTIONS`, `_prochaine_section` (Task 2) ; `app.auth.UserContext`, `get_current_user`, `_membre_actif` pattern (owner-only, PAS `client_lecture`) ; `app.models.Entretiens`, `Ventures` ; `app.serde.entretien`
- Produces: `router` (`APIRouter`), monté sur `/api` — `POST /ventures/{vid}/entretien/demarrer` → `{id, ventureId, sectionCourante, question, rappel, statut}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entretiens_s228.py`:

```python
import uuid as uuidlib
from datetime import datetime, timezone

from app.auth import UserContext, get_current_user
import app.routers.entretiens as entretiens_mod


def _fake_user():
    return UserContext(sub="user-1", nom="Bob", avatar_emoji="🦊", org_id=None)


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Fake session générique : une liste de résultats, un par appel .execute() consécutif."""
    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


VID = "11111111-1111-1111-1111-111111111111"


def _mk_venture(**kw):
    from types import SimpleNamespace
    base = dict(id=VID, owner_id="user-1", audit_id=None, profil_entreprise=None)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_demarrer_cree_un_entretien_si_aucun_en_cours(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    # 1er execute: SELECT venture ; 2e execute: SELECT entretien en_cours (vide)
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], []]))
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 200
    body = r.json()
    assert body["sectionCourante"] == "qualitatif.organisation"
    assert body["statut"] == "en_cours"
    assert body["rappel"] is None
    assert "organisée" in body["question"]


async def test_demarrer_reprend_un_entretien_existant(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    from types import SimpleNamespace
    existant = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="processus.commercial", sections_couvertes=["qualitatif.organisation"],
        transcript="## commercial\nOn répond au téléphone.", statut="en_cours",
        sync_erreur=None, derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [existant]]))
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 200
    body = r.json()
    assert body["sectionCourante"] == "processus.commercial"
    assert body["sectionsCouvertes"] == ["qualitatif.organisation"]
    assert "téléphone" in body["rappel"]


async def test_demarrer_404_si_venture_pas_a_soi(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -k demarrer -v`
Expected: FAIL (404 on unknown route — no `router` defined yet)

- [ ] **Step 3: Write the endpoint**

Add to `briques/forge/forge/core/app/routers/entretiens.py` (after the skeleton block):

```python
import uuid as uuidlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, desc, select

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Entretiens, Ventures
from app.serde import entretien

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _rappel(row) -> str | None:
    """Les 50 derniers caractères pertinents du transcript, ou None — jamais inventé."""
    if row.transcript:
        return row.transcript[-50:]
    return None


@router.post("/ventures/{vid}/entretien/demarrer", dependencies=[Depends(get_current_user)])
async def demarrer_entretien(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")

        existant = (await s.execute(
            select(Entretiens)
            .where(and_(Entretiens.venture_id == u, Entretiens.statut == "en_cours"))
            .order_by(desc(Entretiens.derniere_activite))
        )).scalar_one_or_none()

        if existant:
            section = _section(existant.section_courante) or SECTIONS[0]
            return {
                **entretien(existant),
                "question": f"On reprend où on s'était arrêté : {section['premiere_question']}",
                "rappel": _rappel(existant),
            }

        premiere = SECTIONS[0]
        now = datetime.now(timezone.utc)
        row = Entretiens(
            venture_id=u, section_courante=premiere["id"], sections_couvertes=[],
            transcript="", statut="en_cours", derniere_activite=now, created_at=now,
        )
        s.add(row)
        await s.flush()
        await s.commit()
        await s.refresh(row)
        return {**entretien(row), "question": premiere["premiere_question"], "rappel": None}
```

- [ ] **Step 4: Mount the router**

In `briques/forge/forge/core/app/main.py`, add the import near `ventures_router` (line 84) and the mount call near `mount_both(ventures_router, "/api")` (line 208):

```python
from app.routers.entretiens import router as entretiens_router
```

```python
# S228 — entretien guidé IA (greffé sur Forge, à côté de ventures)
mount_both(entretiens_router, "/api")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -k demarrer -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add briques/forge/forge/core/app/routers/entretiens.py briques/forge/forge/core/app/main.py briques/forge/forge/core/tests/test_entretiens_s228.py
git commit -m "feat(forge): S228 — POST /ventures/{id}/entretien/demarrer (créer/reprendre)"
```

---

## Task 4 : Forge — `POST /entretien/repondre`, section qualitative (extraction + fusion)

**Files:**
- Modify: `briques/forge/forge/core/app/routers/entretiens.py`
- Test: `briques/forge/forge/core/tests/test_entretiens_s228.py`

**Interfaces:**
- Consumes: `app.llm.generate_text(prompt, system=None, ...)` (monkeypatché en test comme `entretiens_mod.generate_text`, cf. `tests/test_s129_routers.py:20-25`)
- Produces: `_fusionner_qualitatif(existant: dict | None, categorie: str, valeurs: list[str]) -> dict` ; endpoint `POST /ventures/{vid}/entretien/repondre`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entretiens_s228.py`:

```python
def test_fusionner_qualitatif_est_non_destructif():
    existant = {"organisation": ["SARL, 5 salariés"]}
    fusion = entretiens_mod._fusionner_qualitatif(existant, "organisation", ["Basée à Lyon"])
    assert fusion == {"organisation": ["SARL, 5 salariés", "Basée à Lyon"]}


def test_fusionner_qualitatif_dedoublonne():
    existant = {"activites": ["conseil"]}
    fusion = entretiens_mod._fusionner_qualitatif(existant, "activites", ["conseil", "formation"])
    assert fusion == {"activites": ["conseil", "formation"]}


def test_fusionner_qualitatif_categorie_absente():
    fusion = entretiens_mod._fusionner_qualitatif(None, "clients", ["PME locales"])
    assert fusion == {"clients": ["PME locales"]}


async def test_repondre_section_qualitative_fusionne_et_relance(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    appels = []

    async def _fake_generate(prompt, system=None, **kw):
        appels.append(prompt)
        if len(appels) == 1:
            return '{"valeurs": ["Basée à Lyon"]}'
        return '{"couverte": false, "question": "Combien de salariés au total ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "On est à Lyon"})
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "en_cours"
    assert body["sectionCourante"] == "qualitatif.organisation"
    assert body["question"] == "Combien de salariés au total ?"
    assert body["extractionEchouee"] is False


async def test_repondre_section_qualitative_couverte_avance_au_squelette(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise=None)
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '{"valeurs": ["SARL, 5 salariés"]}'
        return '{"couverte": true, "question": null}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "SARL, 5 salariés"})
    body = r.json()
    assert body["sectionCourante"] == "qualitatif.activites"
    assert body["sectionsCouvertes"] == ["qualitatif.organisation"]


async def test_repondre_extraction_llm_incoherente_ne_bloque_pas(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return "réponse non-JSON du LLM"
        return '{"couverte": false, "question": "Peux-tu préciser ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["extractionEchouee"] is True
    assert body["question"] == "Peux-tu préciser ?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -k "fusionner or repondre" -v`
Expected: FAIL (`_fusionner_qualitatif` / route inconnues)

- [ ] **Step 3: Write the implementation**

Add to `briques/forge/forge/core/app/routers/entretiens.py`:

```python
import json
import logging

from pydantic import BaseModel
from sqlalchemy import update

from app.llm import generate_text

logger = logging.getLogger(__name__)


def _fusionner_qualitatif(existant: dict | None, categorie: str, valeurs: list[str]) -> dict:
    """Fusion non destructive : ajoute les nouvelles valeurs à la liste existante de la
    catégorie, dé-doublonne, ne touche à AUCUNE autre catégorie."""
    base = dict(existant or {})
    deja = list(base.get(categorie) or [])
    for val in valeurs:
        if val and val not in deja:
            deja.append(val)
    base[categorie] = deja
    return base


_PROMPT_EXTRACTION = (
    "Tu extrais des informations d'entreprise depuis une réponse d'entretien.\n"
    "Catégorie : {categorie}\n"
    "Réponse de l'utilisateur : \"{message}\"\n\n"
    "Réponds UNIQUEMENT en JSON strict : {{\"valeurs\": [\"...\"]}} — une liste de faits "
    "courts et autonomes extraits de cette réponse. Liste vide si rien d'exploitable."
)

_PROMPT_DECISION_QUALITATIF = (
    "Tu mènes un entretien d'audit d'entreprise, catégorie « {categorie} ».\n"
    "Dernière réponse de l'utilisateur : \"{message}\"\n"
    "Ce qu'on sait déjà sur cette catégorie : {connu}\n\n"
    "Décide si cette catégorie est maintenant suffisamment couverte, ou s'il faut relancer "
    "avec une question de suivi CIBLÉE (une réponse courte appelle une relance précise).\n"
    "Réponds UNIQUEMENT en JSON strict : {{\"couverte\": true|false, \"question\": \"...\"|null}}."
)


class RepondreBody(BaseModel):
    message: str


@router.post("/ventures/{vid}/entretien/repondre", dependencies=[Depends(get_current_user)])
async def repondre_entretien(vid: str, body: RepondreBody, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        row = (await s.execute(
            select(Entretiens).where(and_(Entretiens.venture_id == u, Entretiens.statut == "en_cours"))
        )).scalar_one_or_none() if u else None
        if row is None:
            raise HTTPException(status_code=404, detail="Aucun entretien en cours pour cette venture")

        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none()
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")

        section = _section(row.section_courante) or SECTIONS[0]
        now = datetime.now(timezone.utc)
        extraction_echouee = False

        if section["famille"] == "qualitatif":
            categorie = section["categorie"]
            connu = (v.profil_entreprise or {}).get(categorie) or []
            try:
                brut = await generate_text(
                    _PROMPT_EXTRACTION.format(categorie=categorie, message=body.message))
                data = json.loads(brut)
                valeurs = data.get("valeurs") or []
                if not isinstance(valeurs, list):
                    raise ValueError("valeurs doit être une liste")
            except (json.JSONDecodeError, ValueError, TypeError):
                extraction_echouee = True
                valeurs = []
                logger.warning(
                    "[entretien:extraction_echouee] venture=%s categorie=%s — tour conservé, "
                    "fusion sautée pour ce tour", vid, categorie)

            if valeurs:
                nouveau_profil = _fusionner_qualitatif(v.profil_entreprise, categorie, valeurs)
                await s.execute(update(Ventures).where(Ventures.id == u)
                                .values(profil_entreprise=nouveau_profil, updated_at=now))
                connu = nouveau_profil[categorie]

            decision_brut = await generate_text(
                _PROMPT_DECISION_QUALITATIF.format(categorie=categorie, message=body.message, connu=connu))
        else:
            zone = section["zone"]
            row.transcript = (row.transcript or "") + f"\n\n## {zone}\n{body.message}"
            decision_brut = await generate_text(
                _PROMPT_DECISION_PROCESSUS.format(zone=zone, message=body.message))

        try:
            decision = json.loads(decision_brut)
            couverte = bool(decision.get("couverte"))
            question_suivante = decision.get("question")
        except (json.JSONDecodeError, ValueError, TypeError):
            couverte = False
            question_suivante = "Peux-tu préciser ?"

        statut = "en_cours"
        if couverte:
            couvertes = list(row.sections_couvertes or []) + [row.section_courante]
            suivante = _prochaine_section(couvertes)
            if suivante is None:
                statut, _sync_erreur = await _cloturer(s, v, row, transcript=row.transcript)
                row.sections_couvertes = couvertes
                row.statut = statut
                row.sync_erreur = _sync_erreur
                question_suivante = None
            else:
                row.section_courante = suivante["id"]
                row.sections_couvertes = couvertes
                question_suivante = suivante["premiere_question"]

        row.derniere_activite = now
        await s.execute(update(Entretiens).where(Entretiens.id == row.id).values(
            section_courante=row.section_courante, sections_couvertes=row.sections_couvertes,
            transcript=row.transcript, statut=row.statut, sync_erreur=getattr(row, "sync_erreur", None),
            derniere_activite=now,
        ))
        await s.commit()

    return {
        "sectionCourante": row.section_courante,
        "sectionsCouvertes": row.sections_couvertes,
        "question": question_suivante,
        "statut": row.statut,
        "extractionEchouee": extraction_echouee,
    }
```

Note the `_PROMPT_DECISION_PROCESSUS` and `_cloturer` referenced here are written in Task 5 — this task's tests only exercise the `qualitatif` branch, so leave a minimal stub for now:

```python
_PROMPT_DECISION_PROCESSUS = (
    "STUB — remplacé en Task 5"
)


async def _cloturer(s, v, row, transcript: str):
    """STUB — remplacé en Task 5 (push ingestion + rappel /auditer)."""
    return "termine", None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -k "fusionner or repondre" -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/forge/forge/core/app/routers/entretiens.py briques/forge/forge/core/tests/test_entretiens_s228.py
git commit -m "feat(forge): S228 — POST /entretien/repondre, section qualitative (extraction + fusion non destructive)"
```

---

## Task 5 : Forge — section processus + clôture (push ingestion + rappel `/auditer`)

**Files:**
- Modify: `briques/forge/forge/core/app/routers/entretiens.py`
- Test: `briques/forge/forge/core/tests/test_entretiens_s228.py`

**Interfaces:**
- Consumes: `app.config.settings.{INGESTION_URL,INGESTION_KEY,AUDIT_URL}` (déjà câblés côté Forge, cf. `ventures.py:266-337`)
- Produces: `_PROMPT_DECISION_PROCESSUS` (remplace le stub), `_cloturer(s, v, row, transcript) -> (statut, sync_erreur)` (remplace le stub)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entretiens_s228.py`:

```python
async def test_repondre_section_processus_accumule_le_transcript(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="processus.commercial", sections_couvertes=list(
            s["id"] for s in entretiens_mod.SECTIONS if s["famille"] == "qualitatif"),
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_generate(prompt, system=None, **kw):
        return '{"couverte": false, "question": "Et après le devis, comment ça se passe ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre",
                          json={"message": "Un client appelle, on qualifie, on envoie un devis."})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "Et après le devis, comment ça se passe ?"
    assert "qualifie" in row.transcript


async def test_derniere_section_couverte_declenche_la_cloture(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    toutes_sauf_derniere = [s["id"] for s in entretiens_mod.SECTIONS[:-1]]
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante=entretiens_mod.SECTIONS[-1]["id"], sections_couvertes=toutes_sauf_derniere,
        transcript="## communication\n", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_generate(prompt, system=None, **kw):
        return '{"couverte": true, "question": null}'

    async def _fake_cloturer(s, v, row, transcript):
        return "termine", None

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "Par email surtout."})
    body = r.json()
    assert body["statut"] == "termine"
    assert body["question"] is None


async def test_cloturer_pousse_le_transcript_puis_rappelle_auditer(monkeypatch):
    from types import SimpleNamespace
    v = SimpleNamespace(id=VID, audit_id=None)
    row = SimpleNamespace(id="e1")

    calls = []

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            calls.append((url, kw))
            if url.endswith("/ingerer"):
                return SimpleNamespace(status_code=200, json=lambda: {"id": "doc-transcript"})
            if url.endswith("/auditer"):
                return SimpleNamespace(status_code=202, json=lambda: {"id": "audit-new", "statut": "en_cours"})
            raise AssertionError(f"unexpected POST {url}")

        async def get(self, url, **kw):
            calls.append((url, kw))
            return SimpleNamespace(status_code=200, json=lambda: {"documents": [{"id": "doc-transcript"}]})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(entretiens_mod.settings, "INGESTION_URL", "http://ingestion.test")
    monkeypatch.setattr(entretiens_mod.settings, "AUDIT_URL", "http://audit.test")
    monkeypatch.setattr(entretiens_mod.settings, "INGESTION_KEY", "k")

    class _FakeSessionCloture:
        async def execute(self, *a, **k):
            return None

    statut, sync_erreur = await entretiens_mod._cloturer(
        _FakeSessionCloture(), v, row, transcript="## commercial\nOn répond au tel.")
    assert statut == "termine"
    assert sync_erreur is None
    assert v.audit_id == "audit-new"
    urls = [c[0] for c in calls]
    assert any(u.endswith("/ingerer") for u in urls)
    assert any(u.endswith("/auditer") for u in urls)


async def test_cloturer_best_effort_si_ingestion_injoignable(monkeypatch):
    from types import SimpleNamespace
    import httpx
    v = SimpleNamespace(id=VID, audit_id=None)
    row = SimpleNamespace(id="e1")

    class _FakeAsyncClientEnPanne:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            raise httpx.ConnectError("down")

        async def get(self, url, **kw):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClientEnPanne)
    monkeypatch.setattr(entretiens_mod.settings, "INGESTION_URL", "http://ingestion.test")
    monkeypatch.setattr(entretiens_mod.settings, "AUDIT_URL", "http://audit.test")

    class _FakeSessionCloture:
        async def execute(self, *a, **k):
            return None

    statut, sync_erreur = await entretiens_mod._cloturer(
        _FakeSessionCloture(), v, row, transcript="texte")
    assert statut == "termine"  # ne bloque JAMAIS la clôture
    assert sync_erreur is not None
    assert v.audit_id is None  # pas de rappel /auditer possible sans doc_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -k "processus or cloture or cloturer" -v`
Expected: FAIL (stub `_cloturer` returns `("termine", None)` unconditionally, no push/call happens; `_PROMPT_DECISION_PROCESSUS` is a placeholder string but functionally harmless since it's mocked in most tests — the `_cloturer` tests fail because there is no real HTTP logic yet)

- [ ] **Step 3: Replace the stubs with the real implementation**

In `briques/forge/forge/core/app/routers/entretiens.py`, replace the Task 4 stub block:

```python
import httpx

from app.config import settings

_PROMPT_DECISION_PROCESSUS = (
    "Tu mènes un entretien d'audit d'entreprise sur le processus « {zone} ».\n"
    "Dernière réponse de l'utilisateur : \"{message}\"\n\n"
    "Décide si ce processus est maintenant suffisamment décrit (de bout en bout), ou s'il "
    "faut relancer avec une question de suivi CIBLÉE (une réponse courte appelle une "
    "relance précise, motif : « comment arrive une demande » → « qui répond » → « combien "
    "de temps » → ...).\n"
    "Réponds UNIQUEMENT en JSON strict : {{\"couverte\": true|false, \"question\": \"...\"|null}}."
)


async def _cloturer(s, v, row, transcript: str) -> tuple[str, str | None]:
    """Pousse le transcript vers ingestion (POST /ingerer, JAMAIS /documents/import qui ne
    propage pas venture_id) puis rappelle POST {AUDIT_URL}/auditer avec tous les doc_ids de
    la venture. Best-effort : une panne à N'IMPORTE QUELLE étape ne bloque JAMAIS la clôture
    (`statut` devient toujours "termine"), seul `sync_erreur` signale un défaut de synchro,
    rejouable en rappelant /entretien/terminer."""
    if not settings.INGESTION_URL or not settings.AUDIT_URL:
        return "termine", "ingestion/audit non configurés"

    ingestion_headers = {"X-API-Key": settings.INGESTION_KEY} if settings.INGESTION_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            fichier = transcript.encode("utf-8")
            r_push = await c.post(
                f"{settings.INGESTION_URL.rstrip('/')}/ingerer",
                files={"fichier": (f"entretien-{v.id}.txt", fichier, "text/plain")},
                data={"venture_id": str(v.id)},
                headers=ingestion_headers,
            )
            if r_push.status_code >= 400:
                return "termine", f"push ingestion échoué ({r_push.status_code})"

            r_docs = await c.get(
                f"{settings.INGESTION_URL.rstrip('/')}/documents",
                params={"venture_id": str(v.id)}, headers=ingestion_headers,
            )
            if r_docs.status_code >= 400:
                return "termine", f"lecture documents échouée ({r_docs.status_code})"
            doc_ids = [d["id"] for d in r_docs.json().get("documents", [])]
            if not doc_ids:
                return "termine", "aucun doc_id disponible après push"

            r_audit = await c.post(f"{settings.AUDIT_URL.rstrip('/')}/auditer",
                                   json={"doc_ids": doc_ids})
            if r_audit.status_code >= 400:
                return "termine", f"rappel /auditer échoué ({r_audit.status_code})"
            audit_id = r_audit.json().get("id")
    except (httpx.HTTPError, ValueError) as e:
        return "termine", f"panne réseau : {e}"

    v.audit_id = audit_id
    await s.execute(update(Ventures).where(Ventures.id == v.id).values(audit_id=audit_id))
    return "termine", None
```

Also update `repondre_entretien` to pass the correct transcript at the point of calling `_cloturer` — it already does (`_cloturer(s, v, row, transcript=row.transcript)`), no change needed there since the field was already updated on `row.transcript` earlier for the `processus` branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add briques/forge/forge/core/app/routers/entretiens.py briques/forge/forge/core/tests/test_entretiens_s228.py
git commit -m "feat(forge): S228 — section processus + clôture (push ingestion, rappel /auditer, best-effort)"
```

---

## Task 6 : Forge — `POST /entretien/terminer` (clôture explicite/retry) + `GET /entretien/etat`

**Files:**
- Modify: `briques/forge/forge/core/app/routers/entretiens.py`
- Test: `briques/forge/forge/core/tests/test_entretiens_s228.py`

**Interfaces:**
- Consumes: `_cloturer` (Task 5)
- Produces: `POST /ventures/{vid}/entretien/terminer`, `GET /ventures/{vid}/entretien/etat`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entretiens_s228.py`:

```python
async def test_terminer_cloture_explicitement_avant_squelette_complet(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.clients", sections_couvertes=["qualitatif.organisation"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_cloturer(s, v, row, transcript):
        return "termine", None

    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)

    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 200
    assert r.json()["statut"] == "termine"


async def test_terminer_404_si_aucun_entretien(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 404


async def test_etat_renvoie_l_entretien_courant(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.clients", sections_couvertes=["qualitatif.organisation"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))
    r = await client.get(f"/api/ventures/{VID}/entretien/etat")
    assert r.status_code == 200
    assert r.json()["sectionCourante"] == "qualitatif.clients"


async def test_etat_404_si_aucun_entretien(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], []]))
    r = await client.get(f"/api/ventures/{VID}/entretien/etat")
    assert r.status_code == 404


async def test_etat_404_si_venture_pas_a_soi(client, app, monkeypatch):
    """Sécurité : sans le filtre owner_id, n'importe quel utilisateur authentifié pourrait
    lire l'état d'entretien de n'importe quelle venture en devinant son id (même classe de
    bug que les fixes Critical S227 sur les scopes client_lecture)."""
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.get(f"/api/ventures/{VID}/entretien/etat")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -k "terminer or etat" -v`
Expected: FAIL (404 on unknown routes)

- [ ] **Step 3: Write the endpoints**

Add to `briques/forge/forge/core/app/routers/entretiens.py`:

```python
@router.post("/ventures/{vid}/entretien/terminer", dependencies=[Depends(get_current_user)])
async def terminer_entretien(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        row = (await s.execute(
            select(Entretiens).where(Entretiens.venture_id == u).order_by(desc(Entretiens.derniere_activite))
        )).scalar_one_or_none() if u else None
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none()
        if row is None or v is None:
            raise HTTPException(status_code=404, detail="Aucun entretien pour cette venture")

        statut, sync_erreur = await _cloturer(s, v, row, transcript=row.transcript)
        now = datetime.now(timezone.utc)
        await s.execute(update(Entretiens).where(Entretiens.id == row.id).values(
            statut=statut, sync_erreur=sync_erreur, derniere_activite=now))
        await s.commit()
        row.statut, row.sync_erreur = statut, sync_erreur

    return entretien(row)


@router.get("/ventures/{vid}/entretien/etat", dependencies=[Depends(get_current_user)])
async def etat_entretien(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        # Ownership d'abord : sans ce filtre, n'importe quel utilisateur authentifié pourrait
        # lire l'état d'entretien de n'importe quelle venture en devinant son id — même
        # classe de bug que les fixes Critical S227 sur les scopes client_lecture.
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        row = (await s.execute(
            select(Entretiens).where(Entretiens.venture_id == u).order_by(desc(Entretiens.derniere_activite))
        )).scalar_one_or_none() if u and v is not None else None
        if v is None or row is None:
            raise HTTPException(status_code=404, detail="Aucun entretien pour cette venture")
    return entretien(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/test_entretiens_s228.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the FULL forge test suite to check no regression**

Run: `cd briques/forge/forge/core && python3 -m pytest tests/ -q`
Expected: PASS, no regression on S227 tests

- [ ] **Step 6: Commit**

```bash
git add briques/forge/forge/core/app/routers/entretiens.py briques/forge/forge/core/tests/test_entretiens_s228.py
git commit -m "feat(forge): S228 — POST /entretien/terminer (clôture explicite/retry) + GET /entretien/etat"
```

---

## Task 7 : Forge — capacités manifest

**Files:**
- Modify: `briques/forge/manifest.json`

**Interfaces:**
- Produces: 2 entrées dans `capacites` : `forge_entretien_demarrer`, `forge_entretien_repondre`

- [ ] **Step 1: Add the capacities**

Read `briques/forge/manifest.json`, locate the `"capacites"` array (16 entries today), and append two entries (JSON, comma after the previous last entry):

```json
{
  "nom": "forge_entretien_demarrer",
  "description": "Démarre (ou reprend) l'entretien guidé d'audit d'entreprise pour une venture — creuse organisation/activités/clients/... puis les processus (commercial/production/administratif/communication). Renvoie la première question ou reprend là où on s'était arrêté. ACTION.",
  "methode": "POST",
  "chemin": "/ventures/{id}/entretien/demarrer",
  "params": {
    "id": {"type": "string", "description": "Id de la venture (via forge_venture ou le dossier).", "requis": true}
  },
  "action": true,
  "niveau": 1
},
{
  "nom": "forge_entretien_repondre",
  "description": "Fait avancer l'entretien guidé d'audit d'entreprise d'une venture d'un tour : extrait/fusionne le profil qualitatif ou accumule le processus décrit, puis renvoie la relance ou la question suivante. Normalement appelé automatiquement par le Cœur tant qu'un entretien est actif sur ce fil — à n'utiliser explicitement qu'en cas de besoin. ACTION.",
  "methode": "POST",
  "chemin": "/ventures/{id}/entretien/repondre",
  "params": {
    "id": {"type": "string", "description": "Id de la venture.", "requis": true},
    "message": {"type": "string", "description": "La réponse de l'utilisateur à traiter.", "requis": true}
  },
  "action": true,
  "niveau": 1
}
```

- [ ] **Step 2: Verify the manifest is still valid JSON**

Run: `python3 -c "import json; json.load(open('briques/forge/manifest.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Verify the capacity count**

Run: `python3 -c "import json; d = json.load(open('briques/forge/manifest.json')); print(len(d['capacites']))"`
Expected: `18`

- [ ] **Step 4: Commit**

```bash
git add briques/forge/manifest.json
git commit -m "feat(forge): S228 — capacités manifest forge_entretien_demarrer/repondre (niveau 1)"
```

---

## Task 8 : Cœur — module `entretien_routage.py`

**Files:**
- Create: `core/entretien_routage.py`
- Test: `core/test_entretien_routage.py`

**Interfaces:**
- Consumes: `catalogue.base_brique(registre, "forge")` (existant, `core/catalogue.py:32-43`)
- Produces: `REGISTRE: Registre` (singleton, mirroring `accord_action.REGISTRE`), `Registre.activer(fil_accord, venture_id)`, `Registre.actif(fil_accord) -> str | None`, `Registre.desactiver(fil_accord)`, `est_pause(message: str) -> bool`, `async def repondre(registre, fil_accord, venture_id, message, client) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# core/test_entretien_routage.py
"""S228 — routage structurel des tours de conversation vers l'entretien Forge actif.

Offline, calqué sur test_accord_action.py : le registre en mémoire est testé seul, sans
serveur ni réseau réel (l'appel HTTP à Forge est testé séparément, httpx mocké).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import entretien_routage  # noqa: E402


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def test_activer_puis_actif():
    entretien_routage.REGISTRE.activer("fil-1", "venture-1")
    assert entretien_routage.REGISTRE.actif("fil-1") == "venture-1"


def test_actif_none_si_jamais_active():
    assert entretien_routage.REGISTRE.actif("fil-inconnu") is None


def test_desactiver():
    entretien_routage.REGISTRE.activer("fil-1", "venture-1")
    entretien_routage.REGISTRE.desactiver("fil-1")
    assert entretien_routage.REGISTRE.actif("fil-1") is None


def test_isolation_par_fil_accord():
    """Deux fils_accord distincts (donc deux (fil, personne) distincts, cf. accord_action.cle)
    ne partagent JAMAIS le même entretien actif — non-régression directe de la leçon S222."""
    entretien_routage.REGISTRE.activer("web:dashboard\x00alice", "venture-alice")
    entretien_routage.REGISTRE.activer("web:dashboard\x00bob", "venture-bob")
    assert entretien_routage.REGISTRE.actif("web:dashboard\x00alice") == "venture-alice"
    assert entretien_routage.REGISTRE.actif("web:dashboard\x00bob") == "venture-bob"


def test_est_pause_detecte_les_mots_cles_explicites():
    assert entretien_routage.est_pause("pause")
    assert entretien_routage.est_pause("On reprendra plus tard, merci")
    assert entretien_routage.est_pause("PAUSE STP")


def test_est_pause_faux_sur_message_normal():
    assert not entretien_routage.est_pause("On est une SARL de 5 salariés")
    assert not entretien_routage.est_pause("")


def test_repondre_appelle_forge_et_renvoie_le_json():
    calls = []

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Et ensuite ?", "statut": "en_cours", "sectionCourante": "processus.commercial"}

    class _FakeClient:
        async def post(self, url, **kw):
            calls.append((url, kw))
            return _FakeResp()

    async def _run():
        return await entretien_routage.repondre(
            registre=object(), fil_accord="fil-1", venture_id="venture-1",
            message="On qualifie puis on envoie un devis.", client=_FakeClient(),
            base_forge="http://forge.test/api")

    data = asyncio.run(_run())
    assert data["question"] == "Et ensuite ?"
    assert calls[0][0] == "http://forge.test/api/ventures/venture-1/entretien/repondre"
    assert calls[0][1]["json"] == {"message": "On qualifie puis on envoie un devis."}


def test_repondre_desactive_le_registre_quand_termine():
    entretien_routage.REGISTRE.activer("fil-1", "venture-1")

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return await entretien_routage.repondre(
            registre=object(), fil_accord="fil-1", venture_id="venture-1",
            message="Terminé.", client=_FakeClient(), base_forge="http://forge.test/api")

    asyncio.run(_run())
    assert entretien_routage.REGISTRE.actif("fil-1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_entretien_routage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'entretien_routage'`

- [ ] **Step 3: Write the module**

```python
# core/entretien_routage.py
"""Routage structurel des tours d'un entretien guidé actif (S228) vers Forge.

Tant qu'un entretien Forge (venture d'audit) est `en_cours` pour un fil de conversation,
les tours ne passent PAS par le LLM/tool-calling habituel : ils sont routés directement
vers `POST /ventures/{id}/entretien/repondre`. Ça évite deux écueils : le LLM qui oublie
d'appeler l'outil, et le coût d'un tour de function-calling pour chaque réponse d'entretien.

Clé du registre = `accord_action.cle(fil, utilisateur)` (le MÊME motif que le gate d'action,
S222) : le fil seul ne suffit pas, deux personnes sur le même fil web ne doivent jamais
partager le même entretien actif.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Mots-clés EXPLICITES de pause. Volontairement court et ancré sur des frontières de mots —
# même philosophie que `accord_action._REFUS` : un faux positif ne coûte qu'une relance
# évitable, un faux négatif laisse l'entretien actif (état jamais perdu, juste pas
# repris automatiquement ce tour-ci). La détection d'un « changement de sujet clair » au
# sens large (spec S228) est volontairement hors scope de ce mot-clé — trop ambigu pour
# une regex fiable ; le dirigeant garde la main via ces mots-clés explicites.
_PAUSE = re.compile(r"\b(pause|on reprendra|plus tard|reprendrons)\b")


def _sans_accents(texte: str) -> str:
    plie = unicodedata.normalize("NFD", texte or "").casefold()
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def est_pause(message: str) -> bool:
    return bool(_PAUSE.search(_sans_accents(message)))


@dataclass
class Registre:
    """Entretiens actifs, indexés par `fil_accord` (= `accord_action.cle(fil, utilisateur)`)."""

    _actifs: dict[str, str] = field(default_factory=dict)  # fil_accord -> venture_id

    def activer(self, fil_accord: str, venture_id: str) -> None:
        self._actifs[fil_accord] = venture_id

    def actif(self, fil_accord: str) -> str | None:
        return self._actifs.get(fil_accord)

    def desactiver(self, fil_accord: str) -> None:
        self._actifs.pop(fil_accord, None)


REGISTRE = Registre()


async def repondre(registre, fil_accord: str, venture_id: str, message: str, client,
                   base_forge: str) -> dict:
    """Appelle Forge `/entretien/repondre` et désactive le registre si l'entretien se
    termine (clôture naturelle du squelette). `registre` (catalogue Cœur) n'est pas utilisé
    ici mais gardé dans la signature pour cohérence avec le reste du fichier appelant."""
    r = await client.post(f"{base_forge}/ventures/{venture_id}/entretien/repondre",
                          json={"message": message})
    data = r.json()
    if data.get("statut") == "termine":
        REGISTRE.desactiver(fil_accord)
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_entretien_routage.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add core/entretien_routage.py core/test_entretien_routage.py
git commit -m "feat(coeur): S228 — module entretien_routage (registre actif, pause, appel Forge structurel)"
```

---

## Task 9 : Cœur — activation du registre dans `assistant.py`

**Files:**
- Modify: `core/assistant.py`
- Test: `core/test_entretien_routage_hook.py`

**Interfaces:**
- Consumes: `entretien_routage.REGISTRE.activer` (Task 8), `outils.executer` result shape (JSON string)
- Produces: hook dans la boucle d'outils de `assistant.converser` — quand `forge_entretien_demarrer` réussit, `entretien_routage.REGISTRE.actif(fil)` devient non-None

- [ ] **Step 1: Write the failing test**

```python
# core/test_entretien_routage_hook.py
"""S228 — quand le LLM appelle `forge_entretien_demarrer` avec succès, le Cœur active le
routage structurel pour ce fil. Offline, calqué sur test_gate_action_bout_en_bout.py."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import entretien_routage  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "forge": {"nom": "forge", "port": 8600, "capacites": [
        {"nom": "forge_entretien_demarrer", "chemin": "/ventures/{id}/entretien/demarrer",
         "methode": "POST", "action": True, "description": "Démarre l'entretien.",
         "params": {"id": {"type": "string", "requis": True}}},
    ]},
})


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def _jouer(appel_nom, appel_args_json, resultat_outil, fil="fil-test"):
    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": appel_nom, "arguments": appel_args_json}}]}}],
        [{"type": "fin", "message": {"role": "assistant", "content": "C'est parti."}}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        return resultat_outil

    async def _run():
        return [evt async for evt in assistant.converser(
            [{"role": "user", "content": "Auditons l'entreprise X"}], REGISTRE, fil=fil)]

    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        return asyncio.run(_run())
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec


def test_demarrer_reussi_active_le_registre():
    resultat = '{"id": "e1", "ventureId": "venture-1", "sectionCourante": "qualitatif.organisation", "question": "...", "rappel": null, "statut": "en_cours"}'
    _jouer("forge_entretien_demarrer",
           '{"id": "venture-1", "confirme": true}', resultat, fil="fil-test")
    assert entretien_routage.REGISTRE.actif("fil-test") == "venture-1"


def test_demarrer_en_echec_n_active_rien():
    _jouer("forge_entretien_demarrer",
           '{"id": "venture-1", "confirme": true}',
           '{"erreur": "Brique injoignable"}', fil="fil-echec")
    assert entretien_routage.REGISTRE.actif("fil-echec") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_entretien_routage_hook.py -v`
Expected: FAIL — `entretien_routage.REGISTRE.actif("fil-test")` is `None` (no hook yet). Note: `forge_entretien_demarrer` is an `action: true` capacity, so the first tool call with `confirme=true` but no prior `accord_action.demander` will actually be REFUSED by the S222 gate (`refus_accord` branch) — the test above passes `confirme: true` directly which the gate rejects without a prior human turn. Adjust the test to go through the gate properly: replace the single `_jouer` call with a two-turn helper that first calls without `confirme`, then calls again with `confirme=true` after a human turn — OR (simpler, and what this step actually needs) drop `"confirme": true` from `appel_args_json` and assert on `outils_appeles`/gate behavior separately; for THIS hook, the simplest correct fix is to pre-seed the accord so `executer` actually runs. Use this corrected version of `_jouer` before writing the implementation:

```python
def _jouer(appel_nom, appel_args_json, resultat_outil, fil="fil-test"):
    import accord_action
    import json as _json
    args = _json.loads(appel_args_json)
    accord_action.REGISTRE.demander(fil, appel_nom, {k: v for k, v in args.items() if k != "confirme"})
    accord_action.REGISTRE.tour_utilisateur(fil, "oui vas-y")
    ...  # (reste inchangé)
```

Re-run: `cd core && python3 -m pytest test_entretien_routage_hook.py -v` — now it correctly reaches `outils.executer` and fails only because the activation hook doesn't exist yet (`entretien_routage.REGISTRE.actif("fil-test")` still `None`).

- [ ] **Step 3: Write the hook**

In `core/assistant.py`, add the import near the top (with the other local imports, e.g. near `import accord_action` — check the existing import block and match its style, e.g. `import entretien_routage`).

Then, inside the tool-execution loop, right after the line (already present, ~line 380-383):

```python
                else:
                    resultat = await outils.executer(nom, args, registre)
                    # S143 — mise à jour de l'état + idempotence.
                    guardrail.after_call(nom, args, resultat,
                                         erreur=_est_erreur_outil(resultat))
```

Add immediately after (still inside the `else:` block, after the `guardrail.after_call` line):

```python
                    # S228 — un démarrage d'entretien réussi active le routage structurel :
                    # les tours SUIVANTS de ce fil iront directement à /entretien/repondre
                    # sans repasser par le LLM (cf. entretien_routage + routers/assistant.py).
                    if nom == "forge_entretien_demarrer" and not _est_erreur_outil(resultat):
                        try:
                            _data_entretien = json.loads(resultat)
                            _venture_id = _data_entretien.get("ventureId") or args.get("id")
                            if _venture_id:
                                entretien_routage.REGISTRE.activer(fil_accord, _venture_id)
                        except (json.JSONDecodeError, ValueError):
                            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_entretien_routage_hook.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full Cœur test suite to check no regression**

Run: `cd core && python3 -m pytest -q`
Expected: PASS, no regression (in particular `test_gate_action_bout_en_bout.py`, `test_accord_action.py`)

- [ ] **Step 6: Commit**

```bash
git add core/assistant.py core/test_entretien_routage_hook.py
git commit -m "feat(coeur): S228 — active le routage structurel d'entretien sur forge_entretien_demarrer réussi"
```

---

## Task 10 : Cœur — interception dans `routers/assistant.py`

**Files:**
- Modify: `core/routers/assistant.py`
- Test: `core/test_entretien_routage_route.py`

**Interfaces:**
- Consumes: `entretien_routage.REGISTRE.actif`, `entretien_routage.est_pause`, `entretien_routage.repondre` (Task 8), `catalogue.base_brique` (existant)
- Produces: fonction extraite `_flux_entretien(venture_id, fil_accord, message, registre) -> AsyncIterator[dict]` (testable seule, sans ASGI), branchement dans `assistant_chat`

- [ ] **Step 1: Write the failing test**

```python
# core/test_entretien_routage_route.py
"""S228 — quand un entretien est actif pour (fil, personne), le tour de chat est routé
directement vers Forge au lieu du LLM habituel. Teste la fonction extraite, pas tout le
serveur HTTP/SSE (cf. convention test_assistant_routes.py / test_gate_action_bout_en_bout.py)."""
import asyncio
import os
import sys

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")
sys.path.insert(0, os.path.dirname(__file__))

import entretien_routage  # noqa: E402
from routers.assistant import _flux_entretien  # noqa: E402


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def test_flux_entretien_emet_texte_puis_fin():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Et les fournisseurs ?", "statut": "en_cours"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    types = [e["type"] for e in evts]
    assert types == ["texte", "fin"]
    assert evts[0]["contenu"] == "Et les fournisseurs ?"


def test_flux_entretien_sur_cloture_naturelle():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="Terminé.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert evts[0]["type"] == "texte"
    assert "terminé" in evts[0]["contenu"].lower() or "termine" in evts[0]["contenu"].lower()
    assert evts[-1]["type"] == "fin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_entretien_routage_route.py -v`
Expected: FAIL with `ImportError: cannot import name '_flux_entretien'`

- [ ] **Step 3: Write `_flux_entretien` and wire the interception**

In `core/routers/assistant.py`, add the import near the top (with `import accord_action`, etc.):

```python
import entretien_routage
```

Add the extracted generator function, placed just before `assistant_chat` (after `_resoudre_utilisateur`):

```python
async def _flux_entretien(venture_id: str, fil_accord: str, message: str, client, base_forge: str):
    """Tour de conversation routé structurellement vers l'entretien Forge actif (S228),
    au lieu du LLM habituel. Émet les mêmes types d'événements que `assistant.converser`
    (`texte` puis `fin`) pour que le front n'ait rien à changer."""
    data = await entretien_routage.repondre(
        registre=None, fil_accord=fil_accord, venture_id=venture_id, message=message,
        client=client, base_forge=base_forge)
    question = data.get("question")
    if data.get("statut") == "termine":
        texte = question or "Entretien terminé, merci ! L'analyse est relancée avec tout ce qu'on a recueilli."
    else:
        texte = question or "D'accord, continuons."
    yield {"type": "texte", "contenu": texte}
    yield {"type": "fin"}
```

Now wire it into `assistant_chat`, right before the `async def flux():` definition (after the existing S222 block, i.e. after `accord_action.REGISTRE.tour_utilisateur(fil_accord, dernier_user or "")`):

```python
    # S228 — routage structurel : tant qu'un entretien Forge est actif pour CE fil ET cette
    # personne, et que le dernier message n'est pas une pause explicite, on route directement
    # vers Forge au lieu du chat libre habituel (cf. entretien_routage).
    venture_active = entretien_routage.REGISTRE.actif(fil_accord)
    if venture_active and not entretien_routage.est_pause(dernier_user or ""):
        base_forge = catalogue.base_brique(registre, "forge")
        if base_forge:
            async def flux_entretien():
                final = ""
                async with httpx.AsyncClient(timeout=30) as forge_client:
                    async for evt in _flux_entretien(venture_active, fil_accord, dernier_user or "",
                                                      forge_client, base_forge):
                        if evt.get("type") == "texte":
                            final = evt.get("contenu") or ""
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if final.strip():
                    journal_conversations.enregistrer(surface, interlocuteur, "assistant", final,
                                                      utilisateur=utilisateur)

            return StreamingResponse(flux_entretien(), media_type="text/event-stream")
```

This block goes right before `async def flux():` — both branches share the earlier `fil_accord`/`dernier_user` computation. `catalogue` is already imported at the top of this file (line 16); `httpx` too (line 7).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_entretien_routage_route.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full Cœur test suite to check no regression**

Run: `cd core && python3 -m pytest -q`
Expected: PASS, no regression

- [ ] **Step 6: Commit**

```bash
git add core/routers/assistant.py core/test_entretien_routage_route.py
git commit -m "feat(coeur): S228 — routage structurel d'un tour de chat vers l'entretien Forge actif"
```

---

## Task 11 : Cœur — isolation `(fil, personne)` bout-en-bout (non-régression S222)

**Files:**
- Test: `core/test_entretien_routage.py` (already covers pure registre isolation in Task 8)
- Test: `core/test_entretien_routage_route.py` (extend)

**Interfaces:**
- Consumes: `_flux_entretien`, `entretien_routage.REGISTRE` (both already built)

This task is the explicit spec requirement ("Routage Cœur : deux personnes sur le même fil web avec un entretien actif chacune — un tour de l'une ne doit jamais avancer l'entretien de l'autre") proven at the HTTP-routing-decision level, complementing Task 8's registre-level isolation test.

- [ ] **Step 1: Write the failing test**

Append to `core/test_entretien_routage_route.py`:

```python
import accord_action


def test_deux_personnes_meme_fil_entretiens_isoles():
    """web:dashboard est le fil pour TOUT LE MONDE côté web — seule la clé
    (fil, personne) (accord_action.cle) distingue Alice de Bob."""
    fil = "web:dashboard"
    fil_alice = accord_action.cle(fil, "alice")
    fil_bob = accord_action.cle(fil, "bob")

    entretien_routage.REGISTRE.activer(fil_alice, "venture-alice")
    entretien_routage.REGISTRE.activer(fil_bob, "venture-bob")

    assert entretien_routage.REGISTRE.actif(fil_alice) == "venture-alice"
    assert entretien_routage.REGISTRE.actif(fil_bob) == "venture-bob"

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Question pour Bob", "statut": "en_cours"}

    calls = []

    class _FakeClient:
        async def post(self, url, **kw):
            calls.append(url)
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id=entretien_routage.REGISTRE.actif(fil_bob), fil_accord=fil_bob,
            message="Réponse de Bob", client=_FakeClient(), base_forge="http://forge.test/api")]

    asyncio.run(_run())
    # Le tour de Bob n'a appelé QUE la venture de Bob — jamais celle d'Alice.
    assert calls == ["http://forge.test/api/ventures/venture-bob/entretien/repondre"]
    # L'entretien d'Alice reste totalement inchangé.
    assert entretien_routage.REGISTRE.actif(fil_alice) == "venture-alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_entretien_routage_route.py -k isoles -v`
Expected: This should actually PASS already given Task 10's implementation (the isolation is a natural consequence of keying the registre by `fil_accord`, not `fil`) — run it to CONFIRM, not to find a bug. If it fails, it means Task 9/10 accidentally used `fil` instead of `fil_accord` somewhere — fix that regression before proceeding.

- [ ] **Step 3: If it already passes, no code change needed — this step just documents the guarantee**

No implementation step: this test is a regression guard, matching the codebase's convention of dedicating a named test to a specific, previously-fixed vulnerability class (cf. `test_client_lecture_s227.py`, `d674378 test(forge): S227 — durcit les tests _membre_actif contre un retrait silencieux du fix` in git log).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_entretien_routage_route.py -v`
Expected: PASS (3 tests total in this file)

- [ ] **Step 5: Commit**

```bash
git add core/test_entretien_routage_route.py
git commit -m "test(coeur): S228 — durcit l'isolation (fil, personne) du routage d'entretien contre une régression silencieuse"
```

---

## Final check: full test suites

- [ ] Run `cd briques/forge/forge/core && python3 -m pytest tests/ -q` — expect PASS, no regression.
- [ ] Run `cd core && python3 -m pytest -q` — expect PASS, no regression.
- [ ] Run `python3 -c "import json; json.load(open('briques/forge/manifest.json'))"` — expect no exception.

## Explicitly out of scope (per spec's own "Hors périmètre")

- Dedicated UI (progress bar, section display) — API/manifest only.
- Manual correction of a wrong qualitative extraction — no edit screen.
- Voice interview (phone/video) — text chat flow only.
- Incremental writes inside `briques/audit` — explicitly rejected, block-mode unchanged.
- Proactive follow-up (AI re-contacting a stalled interview) — user-initiated resume only.
- "Changement de sujet clair" detection beyond the explicit pause keywords (`pause`, `on reprendra`, `plus tard`, `reprendrons`) — deliberately narrowed in this plan (see Task 8's docstring) because the spec gives no concrete trigger phrasing to implement against; broadening this is a follow-up, not a blocker for S228.
