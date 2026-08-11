# S227 — Entité Entreprise unifiée — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner une vraie substance à `Ventures.type = 'audit'` dans `briques/forge` en reliant l'identité entreprise (`briques/geo`), l'audit business (`briques/audit`) et les documents (`briques/ingestion`) par des références souples, plus un endpoint agrégateur unique et un rôle client en lecture seule scopé à sa venture.

**Architecture:** Greffe sur Forge (pas de nouvelle brique). Trois colonnes ajoutées à `ventures` (`geo_object_id`, `audit_id`, `profil_entreprise` JSONB), une colonne à `organization_members` (`venture_scope`), une colonne indexée à `ingestion.documents` (`venture_id`). Un nouvel endpoint `GET /objets/{objet_id}` côté `geo` (n'existe pas aujourd'hui). Un endpoint agrégateur `GET /ventures/{id}/dossier` côté Forge qui appelle geo/audit/ingestion/AuditMissions internes en parallèle logique, avec repli honnête (`"indisponible"`) par section si une brique est injoignable — jamais de 500 global pour une panne partielle.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (Forge, Postgres/asyncpg) ; FastAPI + sqlite3 (ingestion, geo) ; httpx pour les ponts inter-brique ; pytest + pytest-asyncio.

## Global Constraints

- Pas de nouvelle brique : tout est greffé sur `briques/forge` (`Ventures.type='audit'`).
- Pas de duplication de données existantes ; `profil_entreprise` n'ajoute QUE les champs qualitatifs qui n'existent nulle part ailleurs.
- Deux systèmes d'audit distincts et référencés séparément : `AuditMissions` (Forge interne, `pole_id`) reste inchangé structurellement ; `briques/audit` (5300) est LE moteur référencé par `Ventures.audit_id` pour la suite du pipeline (`briques/generateur`).
- Repli honnête (jamais de donnée inventée) : si `geo` ou `briques/audit` est injoignable au moment d'agréger le dossier, la section correspondante porte `"statut": "indisponible"` avec le dernier id connu — jamais omise silencieusement, jamais simulée.
- Aucune migration destructive de `ingestion.metadonnees.classement.entreprise_id` — la nouvelle colonne `venture_id` coexiste, ne remplace rien pour les documents déjà en base.
- Aucune FK physique inter-service — références souples (`TEXT`), pont HTTP (motif déjà prouvé : `veille-prospection/orchestration.py` → `POST {FORGE_URL}/crm/import-lot`).
- Rôle `client_lecture` : lecture seule sur `GET /ventures/{id}/dossier` **pour sa venture précisément**, 403 sur toute autre venture, aucun accès en écriture.
- Hors périmètre (ne pas coder dans ce sprint) : UI dédiée dans le frontend Forge, retrait/fusion des `AuditMissions` internes, propagation de `venture_id` à l'intérieur de `briques/audit`, entretien guidé (S228), ROI/CDC (S229), connecteurs métier réels (S230).

---

### Task 1: Migration Forge — colonnes `ventures` et `organization_members`

**Files:**
- Modify: `briques/forge/forge/core/app/models/generated.py` (classes `Ventures` lignes 729-752, `OrganizationMembers` lignes 490-504)
- Modify: `briques/forge/forge/core/scripts/init_db.py`
- Test: `briques/forge/forge/core/tests/test_models_s227.py`

**Interfaces:**
- Produces: `Ventures.geo_object_id: str | None`, `Ventures.audit_id: str | None`, `Ventures.profil_entreprise: dict | None` ; `OrganizationMembers.venture_scope: str | None` ; `scripts.init_db.MIGRATIONS_S227: tuple[str, ...]` — consommé par Task 2 (serde/router) et Task 7 (auth `venture_scope`).

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_models_s227.py
"""S227 : colonnes ajoutées au socle Entité Entreprise unifiée."""
from app.models.generated import OrganizationMembers, Ventures


def test_ventures_a_les_colonnes_s227():
    colonnes = set(Ventures.__table__.columns.keys())
    assert {"geo_object_id", "audit_id", "profil_entreprise"} <= colonnes


def test_organization_members_a_venture_scope():
    assert "venture_scope" in OrganizationMembers.__table__.columns.keys()


def test_init_db_declare_les_migrations_s227():
    from scripts.init_db import MIGRATIONS_S227
    assert "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS geo_object_id TEXT" in MIGRATIONS_S227
    assert "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS audit_id TEXT" in MIGRATIONS_S227
    assert "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS profil_entreprise JSONB" in MIGRATIONS_S227
    assert "ALTER TABLE organization_members ADD COLUMN IF NOT EXISTS venture_scope TEXT" in MIGRATIONS_S227
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_models_s227.py -v`
Expected: FAIL — `AssertionError` sur les deux premiers tests (colonnes absentes), `ImportError` ou `AttributeError` sur le troisième (`MIGRATIONS_S227` n'existe pas encore).

- [ ] **Step 3: Ajouter les colonnes au modèle `Ventures`**

Dans `briques/forge/forge/core/app/models/generated.py`, ajouter l'import JSONB en haut du fichier (après la ligne d'import sqlalchemy existante, ligne 21) :

```python
from sqlalchemy.dialects.postgresql import JSONB
```

Puis dans la classe `Ventures` (ligne ~741, juste après `statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'actif'::text"))`) :

```python
    # S227 — socle Entité Entreprise unifiée : références souples (pas de FK
    # physique inter-service) vers geo et briques/audit, + profil qualitatif.
    geo_object_id: Mapped[Optional[str]] = mapped_column(Text)
    audit_id: Mapped[Optional[str]] = mapped_column(Text)
    profil_entreprise: Mapped[Optional[dict]] = mapped_column(JSONB)
```

Dans la classe `OrganizationMembers` (ligne ~499, juste après `role: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'member'::text"))`) :

```python
    # S227 — rôle client_lecture : accès en lecture seule scopé à UNE venture.
    venture_scope: Mapped[Optional[str]] = mapped_column(Text)
```

Note : ce fichier est auto-généré par `sqlacodegen` (`gen_models.sh`) mais aucun Alembic/`schema.ts` n'existe plus (cutover S136) — l'édition manuelle ici est délibérée, cohérente avec le fait qu'`init_db.py` documente déjà `generated.py` comme source de vérité côté Python. Une future régénération contre la DB migrée produira le même résultat.

- [ ] **Step 4: Run test to verify Ventures/OrganizationMembers tests pass**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_models_s227.py::test_ventures_a_les_colonnes_s227 tests/test_models_s227.py::test_organization_members_a_venture_scope -v`
Expected: PASS

- [ ] **Step 5: Ajouter la migration idempotente à `init_db.py`**

Remplacer le contenu de `briques/forge/forge/core/scripts/init_db.py` par :

```python
"""Création idempotente du schéma Forge — migration de la brique (Workplace S17).

Contexte. Le core a été migré du Bun (Drizzle) vers Python (S126-S136). La source
de vérité historique du schéma — ``forge/core/src/db/schema.ts`` (Drizzle) — a été
supprimée avec le Bun au cutover S136. Il ne reste donc ni Alembic, ni SQL, ni
schema.ts : `app/models/generated.py` (77 modèles reflétés par sqlacodegen) est
désormais **la** définition du schéma côté Python.

Pendant la migration strangler, la DB était partagée avec le Bun et ne devait pas
bouger → `app/db.py` s'interdit tout ``create_all``. Cette contrainte est **caduque**
pour la brique Workplace : son Postgres (`forge-db`) est **dédié et vierge**. Créer
les tables depuis les modèles reflétés est ici la voie de migration honnête (S17-1).

Idempotent : ``create_all`` ne crée que les tables absentes (``checkfirst=True``),
donc rejouable à chaque démarrage et sur volume neuf (`forge_pgdata` recréé).
``create_all`` n'altère en revanche JAMAIS une table déjà présente : les colonnes
ajoutées à des tables existantes après le premier déploiement (ex. S227) sont donc
posées séparément via des ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` idempotents
(même motif que ``briques/memoire/memory/backend/app/main.py`` — pas d'Alembic
dans ce projet).

Périmètre : 77 / 87 tables. Les 10 manquantes (mcp_servers, skills, hitl_requests…)
sont des features hors-scope agents+RAG (frontière dure S17) ; aucune n'est cible
d'une FK des 77, donc leur absence ne casse pas la création.

Usage (one-shot, via le service `forge-migrate` du compose) :
    python -m scripts.init_db
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db import engine
from app.models import Base

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("forge.init_db")

# S227 — socle Entité Entreprise unifiée. Chaque statement est idempotent
# (Postgres supporte IF NOT EXISTS sur ADD COLUMN, pas besoin de PRAGMA/try-except
# comme les briques SQLite du repo).
MIGRATIONS_S227: tuple[str, ...] = (
    "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS geo_object_id TEXT",
    "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS audit_id TEXT",
    "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS profil_entreprise JSONB",
    "ALTER TABLE organization_members ADD COLUMN IF NOT EXISTS venture_scope TEXT",
)


async def main() -> None:
    log.info("→ init_db : création du schéma Forge (%d tables) si absent…", len(Base.metadata.tables))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # checkfirst=True par défaut
        for statement in MIGRATIONS_S227:
            await conn.execute(text(statement))
    await engine.dispose()
    log.info("✓ init_db : schéma présent (%d tables mappées).", len(Base.metadata.tables))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run all Task 1 tests to verify they pass**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_models_s227.py -v`
Expected: PASS (3/3)

- [ ] **Step 7: Commit**

```bash
git add briques/forge/forge/core/app/models/generated.py briques/forge/forge/core/scripts/init_db.py briques/forge/forge/core/tests/test_models_s227.py
git commit -m "feat(forge): S227 — socle DB Entité Entreprise unifiée (geo_object_id/audit_id/profil_entreprise/venture_scope)"
```

---

### Task 2: Forge — exposer les nouveaux champs (création/lecture/mise à jour d'une venture)

**Files:**
- Modify: `briques/forge/forge/core/app/serde.py` (fonction `venture`, lignes 361-374)
- Modify: `briques/forge/forge/core/app/routers/ventures.py`
- Test: `briques/forge/forge/core/tests/test_ventures_s227.py`

**Interfaces:**
- Consumes: `Ventures.geo_object_id/audit_id/profil_entreprise` (Task 1), pattern `_FakeSession`/`_FakeResult`/`_fake_user` de `briques/forge/forge/core/tests/test_skills.py`.
- Produces: `serde.venture(r)` renvoie désormais `geoObjectId`, `auditId`, `profilEntreprise` ; `PATCH /api/ventures/{id}` accepte ces 3 champs en plus de l'existant.

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_ventures_s227.py
"""S227 : exposition geoObjectId/auditId/profilEntreprise sur le CRUD ventures."""
from __future__ import annotations

from types import SimpleNamespace

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


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
    def __init__(self, rows=None):
        self._rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _FakeResult(self._rows)

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _mk_venture(**kw):
    base = dict(
        id="11111111-1111-1111-1111-111111111111", owner_id="user-1", org_id=None,
        nom="Client X", description="", emoji="🚀", couleur="#6366f1", type="audit",
        statut="actif", created_at=None, updated_at=None,
        geo_object_id=None, audit_id=None, profil_entreprise=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_get_venture_expose_les_champs_s227(client, monkeypatch):
    client.app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(geo_object_id="geo-1", audit_id="audit-1",
                     profil_entreprise={"organisation": "SARL"})
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows=[v]))
    r = await client.get(f"/api/ventures/{v.id}")
    client.app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["geoObjectId"] == "geo-1"
    assert body["auditId"] == "audit-1"
    assert body["profilEntreprise"] == {"organisation": "SARL"}


async def test_patch_venture_accepte_les_champs_s227(client, monkeypatch):
    client.app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(geo_object_id="geo-9", audit_id="audit-9",
                     profil_entreprise={"activites": ["conseil"]})
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows=[v]))
    r = await client.patch(f"/api/ventures/{v.id}", json={
        "geoObjectId": "geo-9", "auditId": "audit-9",
        "profilEntreprise": {"activites": ["conseil"]},
    })
    client.app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["geoObjectId"] == "geo-9"
    assert body["profilEntreprise"] == {"activites": ["conseil"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_ventures_s227.py -v`
Expected: FAIL — `KeyError`/`AssertionError`, `geoObjectId` absent de la réponse ; le PATCH ignore les champs (422 ou champs manquants dans la réponse).

- [ ] **Step 3: Étendre `serde.venture`**

Dans `briques/forge/forge/core/app/serde.py`, remplacer la fonction `venture` (lignes 361-374) par :

```python
def venture(r) -> dict:
    return {
        "id": _sid(r.id),
        "ownerId": r.owner_id,
        "orgId": _sid(r.org_id),
        "nom": r.nom,
        "description": r.description,
        "emoji": r.emoji,
        "couleur": r.couleur,
        "type": r.type,
        "statut": r.statut,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
        # S227 — socle Entité Entreprise unifiée.
        "geoObjectId": r.geo_object_id,
        "auditId": r.audit_id,
        "profilEntreprise": r.profil_entreprise,
    }
```

- [ ] **Step 4: Étendre `UpdateVenture` et `CreateVenture` dans le router**

Dans `briques/forge/forge/core/app/routers/ventures.py`, remplacer la classe `UpdateVenture` par :

```python
class UpdateVenture(BaseModel):
    nom: str | None = None
    description: str | None = None
    emoji: str | None = None
    couleur: str | None = None
    statut: str | None = None  # 'actif' | 'archive' | 'livre'
    geo_object_id: str | None = Field(None, alias="geoObjectId")
    audit_id: str | None = Field(None, alias="auditId")
    profil_entreprise: dict | None = Field(None, alias="profilEntreprise")

    model_config = {"populate_by_name": True}
```

Le reste de `update_venture` fonctionne sans modification : `cols = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}` produit déjà des clés `geo_object_id`/`audit_id`/`profil_entreprise` (noms Python, pas les alias) car `model_dump()` sans `by_alias=True` renvoie les noms de champs — qui correspondent exactement aux colonnes SQLAlchemy passées à `update(Ventures).values(**cols)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_ventures_s227.py tests/test_skills.py -v`
Expected: PASS (le rerun de `test_skills.py` vérifie la non-régression du CRUD voisin)

- [ ] **Step 6: Commit**

```bash
git add briques/forge/forge/core/app/serde.py briques/forge/forge/core/app/routers/ventures.py briques/forge/forge/core/tests/test_ventures_s227.py
git commit -m "feat(forge): S227 — expose geoObjectId/auditId/profilEntreprise sur le CRUD ventures"
```

---

### Task 3: Ingestion — colonne indexée `venture_id` sur `documents`

**Files:**
- Modify: `briques/ingestion/stockage.py`
- Modify: `briques/ingestion/main.py`
- Test: `briques/ingestion/test_venture_id_s227.py`

**Interfaces:**
- Produces: `stockage.sauvegarder(..., venture_id: str | None = None)`, `stockage.lister(..., venture_id: str | None = None)` (filtre sur la colonne indexée, PAS sur `metadonnees.classement`), `POST /ingerer` accepte un champ form optionnel `venture_id`, `GET /documents?venture_id=...`.

- [ ] **Step 1: Write the failing test**

```python
# briques/ingestion/test_venture_id_s227.py
"""S227 : colonne indexée venture_id sur documents (coexiste avec l'ancienne clé
JSON metadonnees.classement.entreprise_id — aucune migration destructive)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    from main import app
    with TestClient(app) as c:
        yield c


def test_documents_a_la_colonne_venture_id(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "colonnes.db")
    stockage.initialiser()
    with stockage._conn() as con:
        colonnes = {row["name"] for row in con.execute("PRAGMA table_info(documents)").fetchall()}
    assert "venture_id" in colonnes


def test_ingerer_avec_venture_id_puis_filtrer(client):
    resp = client.post(
        "/ingerer",
        files={"fichier": ("bonjour.txt", b"Bonjour monde !", "text/plain")},
        data={"venture_id": "venture-42"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    autre = client.post(
        "/ingerer",
        files={"fichier": ("autre.txt", b"Autre contenu.", "text/plain")},
    )
    assert autre.status_code == 200

    resp2 = client.get("/documents?venture_id=venture-42")
    assert resp2.status_code == 200
    docs = resp2.json()["documents"]
    assert [d["id"] for d in docs] == [doc_id]


def test_document_sans_venture_id_reste_lisible(client):
    resp = client.post(
        "/documents/import",
        json={"nom": "ancien.txt", "source": "test", "texte_extrait": "x"},
    )
    doc_id = resp.json()["id"]
    resp2 = client.get(f"/documents/{doc_id}")
    assert resp2.status_code == 200
    assert resp2.json()["nom"] == "ancien.txt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/ingestion && python -m pytest test_venture_id_s227.py -v`
Expected: FAIL — `venture_id` absent de `PRAGMA table_info`, filtre `?venture_id=` sans effet (les deux documents reviennent), `POST /ingerer` ignore le champ `venture_id`.

- [ ] **Step 3: Ajouter la colonne + index idempotents dans `stockage.py`**

Dans `briques/ingestion/stockage.py`, ajouter une fonction de migration douce (même motif que `briques/jeu-factions/stockage.py:16-23`, SQLite n'a pas `ADD COLUMN IF NOT EXISTS`) et l'appeler depuis `initialiser()` :

```python
def _migrer_colonne_venture_id(con: sqlite3.Connection) -> None:
    """S227 : ajoute `venture_id` (+ index) si absente — bases créées avant ce
    sprint. La clé JSON `metadonnees.classement.entreprise_id` n'est PAS retirée :
    les deux coexistent, la colonne indexée devient la source de vérité pour les
    nouveaux documents seulement."""
    colonnes = {row["name"] for row in con.execute("PRAGMA table_info(documents)").fetchall()}
    if "venture_id" not in colonnes:
        con.execute("ALTER TABLE documents ADD COLUMN venture_id TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_documents_venture ON documents(venture_id)")


def initialiser():
    reprendre_base_heritee()
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id            TEXT PRIMARY KEY,
                nom           TEXT NOT NULL,
                source        TEXT NOT NULL,
                type_mime     TEXT,
                taille        INTEGER,
                texte_extrait TEXT,
                metadonnees   TEXT DEFAULT '{}',
                date_ingestion TEXT NOT NULL,
                venture_id    TEXT
            )
        """)
        _migrer_colonne_venture_id(con)
```

- [ ] **Step 4: Étendre `sauvegarder`**

Dans `briques/ingestion/stockage.py`, remplacer la signature et le corps de `sauvegarder` :

```python
def sauvegarder(
    nom: str,
    source: str,
    type_mime: str | None,
    taille: int,
    texte: str,
    metadonnees: dict | None = None,
    venture_id: str | None = None,
) -> str:
    doc_id = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT INTO documents
               (id, nom, source, type_mime, taille, texte_extrait, metadonnees, date_ingestion, venture_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                nom,
                source,
                type_mime,
                taille,
                texte,
                json.dumps(metadonnees or {}, ensure_ascii=False),
                datetime.utcnow().isoformat(),
                venture_id,
            ),
        )
    return doc_id
```

- [ ] **Step 5: Étendre `lister`**

Dans `briques/ingestion/stockage.py`, remplacer la fonction `lister` :

```python
def lister(
    limite: int = 100,
    offset: int = 0,
    categorie: str | None = None,
    projet: str | None = None,
    entreprise_id: str | None = None,
    venture_id: str | None = None,
) -> list[dict]:
    """Liste les documents (du plus récent au plus ancien), avec leur `classement`.

    `venture_id` filtre sur la colonne indexée (S227) — distinct de `entreprise_id`
    qui filtre sur l'ancienne clé JSON `metadonnees.classement.entreprise_id`
    (rétrocompatibilité, non retirée).
    """
    with _conn() as con:
        if venture_id:
            rows = con.execute(
                "SELECT id, nom, source, type_mime, taille, date_ingestion, metadonnees, venture_id, "
                "LENGTH(texte_extrait) as nb_caracteres "
                "FROM documents WHERE venture_id = ? ORDER BY date_ingestion DESC",
                (venture_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, nom, source, type_mime, taille, date_ingestion, metadonnees, venture_id, "
                "LENGTH(texte_extrait) as nb_caracteres "
                "FROM documents ORDER BY date_ingestion DESC",
            ).fetchall()

    docs: list[dict] = []
    for r in rows:
        d = dict(r)
        meta = json.loads(d.pop("metadonnees") or "{}")
        classement = meta.get("classement") or {}
        if categorie and classement.get("categorie") != categorie:
            continue
        if projet and classement.get("projet") != projet:
            continue
        if entreprise_id and classement.get("entreprise_id") != entreprise_id:
            continue
        d["classement"] = classement
        docs.append(d)
    return docs[offset:offset + limite]
```

- [ ] **Step 6: Brancher `venture_id` dans `main.py`**

Dans `briques/ingestion/main.py`, modifier `ingerer_fichier` (lignes 98-129) pour accepter un champ form optionnel — ajouter `from fastapi import Form` si absent des imports, puis :

```python
@app.post("/ingerer", summary="Uploader et ingérer un fichier")
async def ingerer_fichier(
    fichier: UploadFile = File(...),
    venture_id: str | None = Form(None),
    _cle: str = Depends(cle_api),
):
    contenu = await fichier.read()
    taille = len(contenu)
    if taille == 0:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if taille > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop grand (max 50 Mo)")

    logger.info("Ingestion fichier : %s (%d octets)", fichier.filename, taille)
    texte = await extraction.extraire_texte_async(
        contenu, fichier.filename or "inconnu", fichier.content_type)

    doc_id = stockage.sauvegarder(
        nom=fichier.filename or "inconnu",
        source="upload",
        type_mime=fichier.content_type,
        taille=taille,
        texte=texte,
        venture_id=venture_id,
    )

    logger.info("Document sauvegardé : %s (%d caractères extraits)", doc_id, len(texte))
    return {
        "id": doc_id,
        "nom": fichier.filename,
        "nb_caracteres": len(texte),
        "message": "Document ingéré avec succès",
    }
```

Et `lister_documents` (lignes 177-190) :

```python
@app.get("/documents", summary="Lister les documents ingérés")
def lister_documents(
    limite: int = 50,
    offset: int = 0,
    categorie: str | None = None,
    projet: str | None = None,
    entreprise_id: str | None = None,
    venture_id: str | None = None,
    _cle: str = Depends(cle_api),
):
    docs = stockage.lister(
        limite=limite, offset=offset,
        categorie=categorie, projet=projet, entreprise_id=entreprise_id,
        venture_id=venture_id,
    )
    return {"total": stockage.compter(), "offset": offset, "documents": docs}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd briques/ingestion && python -m pytest test_venture_id_s227.py test_ingestion.py -v`
Expected: PASS — inclut la non-régression de `test_ingestion.py` (documents sans `venture_id` restent lisibles).

- [ ] **Step 8: Commit**

```bash
git add briques/ingestion/stockage.py briques/ingestion/main.py briques/ingestion/test_venture_id_s227.py
git commit -m "feat(ingestion): S227 — colonne indexée venture_id sur documents (coexiste avec metadonnees.classement)"
```

---

### Task 4: Geo — endpoint `GET /objets/{objet_id}`

**Files:**
- Modify: `briques/geo/main.py`
- Test: `briques/geo/test_lire_objet_s227.py`

**Interfaces:**
- Produces: `GET /objets/{objet_id}` → 200 avec le même shape que `POST /objets` (via `stockage._objet_dict`), 404 si absent. Consommé par Task 6 (dossier agrégé de Forge).

- [ ] **Step 1: Write the failing test**

```python
# briques/geo/test_lire_objet_s227.py
"""S227 : GET /objets/{id} — lecture d'un objet géo par id (n'existait pas)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "geo.db")
    from main import app
    with TestClient(app) as c:
        yield c


def test_lire_objet_existant(client):
    creation = client.post("/objets", json={
        "type": "entreprise", "latitude": 48.85, "longitude": 2.35,
        "metadata": {"nom": "Acme SARL"},
    })
    assert creation.status_code == 201
    objet_id = creation.json()["id"]

    lecture = client.get(f"/objets/{objet_id}")
    assert lecture.status_code == 200
    assert lecture.json()["id"] == objet_id
    assert lecture.json()["metadata"]["nom"] == "Acme SARL"


def test_lire_objet_inexistant_retourne_404(client):
    resp = client.get("/objets/inexistant-xyz")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/geo && python -m pytest test_lire_objet_s227.py -v`
Expected: FAIL — `404 Not Found` de FastAPI (route inexistante) sur `test_lire_objet_existant`.

Note préalable : vérifier le nom exact du fichier de stockage géo (`DB_CHEMIN` supposé par analogie avec `ingestion` — confirmer via `grep -n "DB_CHEMIN\|DB_PATH" briques/geo/stockage.py` avant d'écrire la fixture définitive ; adapter le nom de l'attribut monkeypatché si différent, ex. `DB_PATH`).

- [ ] **Step 3: Ajouter l'endpoint dans `main.py`**

Dans `briques/geo/main.py`, ajouter juste après `creer_objet` (après la ligne 173, `@app.post("/objets", status_code=201)` et son corps) :

```python
@app.get("/objets/{objet_id}")
def lire_objet(objet_id: str, tenant: str = Depends(tenant_actuel)):
    """Lit un objet géo par id (S227 — consommé par le dossier agrégé de Forge)."""
    objet = stockage.lire_objet(tenant, objet_id)
    if objet is None:
        raise HTTPException(404, "Objet introuvable")
    return objet
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/geo && python -m pytest test_lire_objet_s227.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add briques/geo/main.py briques/geo/test_lire_objet_s227.py
git commit -m "feat(geo): S227 — GET /objets/{id}, lecture d'un objet par id (consommé par le dossier Forge)"
```

---

### Task 5: Forge — settings pour les ponts geo/audit/ingestion + manifest

**Files:**
- Modify: `briques/forge/forge/core/app/config.py`
- Modify: `briques/forge/manifest.json`
- Test: `briques/forge/forge/core/tests/test_config_s227.py`

**Interfaces:**
- Produces: `settings.GEO_URL: str`, `settings.GEO_KEY: str`, `settings.AUDIT_URL: str`, `settings.INGESTION_URL: str`, `settings.INGESTION_KEY: str`. Consommé par Task 6.

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_config_s227.py
"""S227 : settings des ponts vers geo/audit/ingestion."""
from app.config import Settings


def test_settings_s227_existent():
    s = Settings()
    assert hasattr(s, "GEO_URL")
    assert hasattr(s, "GEO_KEY")
    assert hasattr(s, "AUDIT_URL")
    assert hasattr(s, "INGESTION_URL")
    assert hasattr(s, "INGESTION_KEY")
    assert s.GEO_URL == ""  # vide par défaut = section "indisponible" au lieu de 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_config_s227.py -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Ajouter les settings**

Dans `briques/forge/forge/core/app/config.py`, ajouter après le bloc `MEMOIRE_URL`/`MEMOIRE_ESPACE` (ligne 55) :

```python
    # S227 — socle Entité Entreprise unifiée : ponts vers geo/audit/ingestion
    # pour GET /ventures/{id}/dossier. Vide = section correspondante marquée
    # "indisponible" dans la réponse agrégée (repli honnête, jamais de 500).
    GEO_URL: str = ""  # ex. http://host.docker.internal:5100
    GEO_KEY: str = ""  # doit figurer dans API_KEYS de la brique geo
    AUDIT_URL: str = ""  # ex. http://host.docker.internal:5300
    INGESTION_URL: str = ""  # ex. http://host.docker.internal:5200
    INGESTION_KEY: str = ""  # doit figurer dans INGESTION_API_KEYS/API_KEYS de ingestion
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_config_s227.py -v`
Expected: PASS

- [ ] **Step 5: Étendre `depends_on` du manifest**

Lire `briques/forge/manifest.json`, localiser la clé `"depends_on"` (actuellement `["gateway", "memoire"]`) et la remplacer par :

```json
  "depends_on": ["gateway", "memoire", "geo", "audit", "ingestion"],
```

- [ ] **Step 6: Commit**

```bash
git add briques/forge/forge/core/app/config.py briques/forge/manifest.json briques/forge/forge/core/tests/test_config_s227.py
git commit -m "feat(forge): S227 — settings ponts geo/audit/ingestion + depends_on manifest"
```

---

### Task 6: Forge — endpoint agrégateur `GET /ventures/{id}/dossier`

**Files:**
- Modify: `briques/forge/forge/core/app/routers/ventures.py`
- Test: `briques/forge/forge/core/tests/test_dossier_s227.py`

**Interfaces:**
- Consumes: `settings.GEO_URL/GEO_KEY/AUDIT_URL/INGESTION_URL/INGESTION_KEY` (Task 5), `GET {GEO_URL}/objets/{id}` (Task 4), `GET {AUDIT_URL}/audits/{id}` (existant, confirmé `briques/audit/main.py:222-228`), `GET {INGESTION_URL}/documents?venture_id=` (Task 3), `Poles`/`AuditMissions`/`serde.audit_mission` (existants, `briques/forge/forge/core/app/routers/audit.py`).
- Produces: `GET /api/ventures/{id}/dossier` → `{"identite": {...}, "audit": {...}, "auditMissions": [...], "documents": [...], "profilEntreprise": {...}}`, chaque section `identite`/`audit` porte `"statut": "indisponible"` si la brique correspondante ne répond pas.

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_dossier_s227.py
"""S227 : GET /ventures/{id}/dossier — agrégateur avec repli honnête par section."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


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
    def __init__(self, rows_by_call):
        # rows_by_call : liste de listes, une par appel .execute() consécutif
        # (venture, poles, audit_missions dans cet ordre côté handler).
        self._rows_by_call = list(rows_by_call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)


def _mk_venture(**kw):
    base = dict(
        id="11111111-1111-1111-1111-111111111111", owner_id="user-1",
        geo_object_id="geo-1", audit_id="audit-1", profil_entreprise={"organisation": "SARL"},
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("scenario", ["nominal", "geo_en_panne", "audit_en_panne", "deux_en_panne"])
async def test_dossier_agrege(client, monkeypatch, scenario):
    client.app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [], []]))
    monkeypatch.setattr(ventures_mod.settings, "GEO_URL", "http://geo.test")
    monkeypatch.setattr(ventures_mod.settings, "AUDIT_URL", "http://audit.test")
    monkeypatch.setattr(ventures_mod.settings, "INGESTION_URL", "http://ingestion.test")

    async def _fake_get(self, url, **kw):
        if scenario in ("geo_en_panne", "deux_en_panne") and "geo.test" in url:
            raise httpx.ConnectError("geo down")
        if scenario in ("audit_en_panne", "deux_en_panne") and "audit.test" in url:
            raise httpx.ConnectError("audit down")
        if "geo.test" in url:
            return httpx.Response(200, json={"id": "geo-1", "metadata": {"nom": "Acme"}})
        if "audit.test" in url:
            return httpx.Response(200, json={"id": "audit-1", "statut": "termine"})
        if "ingestion.test" in url:
            return httpx.Response(200, json={"total": 0, "offset": 0, "documents": []})
        return httpx.Response(404)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    r = await client.get(f"/api/ventures/{v.id}/dossier")
    client.app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["profilEntreprise"] == {"organisation": "SARL"}
    if scenario == "geo_en_panne":
        assert body["identite"]["statut"] == "indisponible"
        assert body["identite"]["geoObjectId"] == "geo-1"
        assert body["audit"]["id"] == "audit-1"
    elif scenario == "audit_en_panne":
        assert body["audit"]["statut"] == "indisponible"
        assert body["audit"]["auditId"] == "audit-1"
        assert body["identite"]["id"] == "geo-1"
    elif scenario == "deux_en_panne":
        assert body["identite"]["statut"] == "indisponible"
        assert body["audit"]["statut"] == "indisponible"
    else:
        assert body["identite"]["id"] == "geo-1"
        assert body["audit"]["id"] == "audit-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_dossier_s227.py -v`
Expected: FAIL — `404 Not Found` (route inexistante).

- [ ] **Step 3: Implémenter l'agrégateur**

Dans `briques/forge/forge/core/app/routers/ventures.py`, ajouter les imports en haut du fichier :

```python
import httpx

from app.config import settings
from app.models import AuditMissions
from app.serde import audit_mission, pole, venture, venture_member
```

(remplace la ligne d'import `serde` existante `from app.serde import pole, venture, venture_member` par la ligne ci-dessus qui ajoute `audit_mission`.)

Puis ajouter, à la fin du fichier, après `create_venture_pole` :

```python
async def _lire_identite(geo_object_id: str | None) -> dict:
    if not geo_object_id:
        return {"statut": "absent"}
    if not settings.GEO_URL:
        return {"statut": "indisponible", "geoObjectId": geo_object_id}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            headers = {"X-API-Key": settings.GEO_KEY} if settings.GEO_KEY else {}
            r = await c.get(f"{settings.GEO_URL.rstrip('/')}/objets/{geo_object_id}", headers=headers)
        if r.status_code != 200:
            return {"statut": "indisponible", "geoObjectId": geo_object_id}
        return r.json()
    except httpx.HTTPError:
        return {"statut": "indisponible", "geoObjectId": geo_object_id}


async def _lire_audit_business(audit_id: str | None) -> dict:
    if not audit_id:
        return {"statut": "absent"}
    if not settings.AUDIT_URL:
        return {"statut": "indisponible", "auditId": audit_id}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{settings.AUDIT_URL.rstrip('/')}/audits/{audit_id}")
        if r.status_code != 200:
            return {"statut": "indisponible", "auditId": audit_id}
        return r.json()
    except httpx.HTTPError:
        return {"statut": "indisponible", "auditId": audit_id}


async def _lister_documents(vid: str) -> list[dict]:
    if not settings.INGESTION_URL:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            headers = {"X-API-Key": settings.INGESTION_KEY} if settings.INGESTION_KEY else {}
            r = await c.get(f"{settings.INGESTION_URL.rstrip('/')}/documents",
                            params={"venture_id": vid}, headers=headers)
        if r.status_code != 200:
            return []
        return r.json().get("documents", [])
    except httpx.HTTPError:
        return []


@router.get("/ventures/{vid}/dossier", dependencies=[Depends(get_current_user)])
async def get_venture_dossier(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")

        poles_rows = (await s.execute(select(Poles).where(Poles.venture_id == vid))).scalars().all()
        pole_ids = [p.id for p in poles_rows]
        missions_rows = []
        if pole_ids:
            missions_rows = (await s.execute(
                select(AuditMissions).where(AuditMissions.pole_id.in_(pole_ids))
            )).scalars().all()

    identite = await _lire_identite(v.geo_object_id)
    audit_business = await _lire_audit_business(v.audit_id)
    documents = await _lister_documents(vid)

    return {
        "identite": identite,
        "audit": audit_business,
        "auditMissions": [audit_mission(m) for m in missions_rows],
        "documents": documents,
        "profilEntreprise": v.profil_entreprise,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_dossier_s227.py -v`
Expected: PASS (4/4 — nominal, geo_en_panne, audit_en_panne, deux_en_panne)

- [ ] **Step 5: Run full forge/core test suite for regressions**

Run: `cd briques/forge/forge/core && python -m pytest tests/ -v`
Expected: PASS (aucune régression sur les routers voisins)

- [ ] **Step 6: Commit**

```bash
git add briques/forge/forge/core/app/routers/ventures.py briques/forge/forge/core/tests/test_dossier_s227.py
git commit -m "feat(forge): S227 — GET /ventures/{id}/dossier, agrégateur identite+audit+documents+missions avec repli honnête"
```

---

### Task 7: Forge — rôle `client_lecture` scopé à une venture

**Files:**
- Modify: `briques/forge/forge/core/app/auth.py`
- Modify: `briques/forge/forge/core/app/routers/ventures.py`
- Test: `briques/forge/forge/core/tests/test_client_lecture_s227.py`

**Interfaces:**
- Consumes: `OrganizationMembers.venture_scope` (Task 1).
- Produces: `UserContext.venture_scopes: frozenset[str]` (nouveau champ), dépendance `require_venture_access(vid)` utilisée sur `GET /ventures/{id}/dossier` : 403 si `user.sub != Ventures.owner_id` ET `vid` absent de `user.venture_scopes`.

- [ ] **Step 1: Write the failing test**

```python
# briques/forge/forge/core/tests/test_client_lecture_s227.py
"""S227 : rôle client_lecture — accès en lecture seule scopé à SA venture."""
from __future__ import annotations

from types import SimpleNamespace

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


def _client_lecture_user():
    return UserContext(sub="client-1", nom="Client", avatar_emoji="🙂", org_id=None,
                       venture_scopes=frozenset({"11111111-1111-1111-1111-111111111111"}))


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
    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)


def _mk_venture(vid, owner="someone-else"):
    return SimpleNamespace(id=vid, owner_id=owner, geo_object_id=None,
                           audit_id=None, profil_entreprise=None)


async def test_client_lecture_accede_a_sa_venture(client, monkeypatch):
    vid = "11111111-1111-1111-1111-111111111111"
    client.app.dependency_overrides[get_current_user] = _client_lecture_user
    v = _mk_venture(vid)
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [], []]))
    r = await client.get(f"/api/ventures/{vid}/dossier")
    client.app.dependency_overrides.clear()
    assert r.status_code == 200


async def test_client_lecture_403_sur_autre_venture(client, monkeypatch):
    autre_vid = "22222222-2222-2222-2222-222222222222"
    client.app.dependency_overrides[get_current_user] = _client_lecture_user
    v = _mk_venture(autre_vid)
    monkeypatch.setattr(ventures_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [], []]))
    r = await client.get(f"/api/ventures/{autre_vid}/dossier")
    client.app.dependency_overrides.clear()
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_client_lecture_s227.py -v`
Expected: FAIL — `TypeError` (`UserContext` n'a pas de champ `venture_scopes`), `test_client_lecture_accede_a_sa_venture` échoue en 404 (l'endpoint ne connaît que `owner_id`, pas `venture_scopes`).

- [ ] **Step 3: Ajouter `venture_scopes` à `UserContext` et le résoudre**

Dans `briques/forge/forge/core/app/auth.py`, remplacer le dataclass `UserContext` (lignes 45-50) :

```python
@dataclass
class UserContext:
    sub: str          # users.id (UUID Forge en str)
    nom: str
    avatar_emoji: str
    org_id: str | None
    venture_scopes: frozenset[str] = frozenset()  # S227 — role client_lecture
```

Ajouter une fonction de résolution juste avant `get_current_user` :

```python
async def _resolve_venture_scopes(session, user_id: str) -> frozenset[str]:
    """S227 — ventures accessibles en lecture seule via le rôle client_lecture."""
    rows = (
        await session.execute(
            select(OrganizationMembers.venture_scope).where(
                OrganizationMembers.user_id == user_id,
                OrganizationMembers.role == "client_lecture",
                OrganizationMembers.venture_scope.is_not(None),
            )
        )
    ).scalars().all()
    return frozenset(rows)
```

Dans `get_current_user`, entre la ligne `org_id = await _resolve_org(...)` et le `return UserContext(...)`, ajouter :

```python
        venture_scopes = await _resolve_venture_scopes(session, str(user.id))
```

et étendre le `return` :

```python
        return UserContext(
            sub=str(user.id),
            nom=user.nom,
            avatar_emoji=user.avatar_emoji or "👤",
            org_id=org_id,
            venture_scopes=venture_scopes,
        )
```

- [ ] **Step 4: Enforcer le scope sur `GET /ventures/{id}/dossier`**

Dans `briques/forge/forge/core/app/routers/ventures.py`, remplacer le bloc de résolution de la venture dans `get_venture_dossier` (Task 6, Step 3) :

```python
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")
```

par :

```python
        v = (await s.execute(select(Ventures).where(Ventures.id == u))).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")
        if v.owner_id != user.sub and vid not in user.venture_scopes:
            raise HTTPException(status_code=403, detail="Forbidden")
```

Note : ce changement élargit délibérément la lecture au-delà du seul `owner_id` (pour couvrir `venture_scopes`), mais seulement sur CET endpoint de lecture agrégée — `get_venture`, `update_venture`, `delete_venture`, `create_venture_pole` restent inchangés et continuent de filtrer strictement sur `owner_id == user.sub` (hors périmètre S227 : élargir l'accès en écriture ou aux autres routes de lecture n'est pas demandé par le spec, qui borne `client_lecture` à *ce* endpoint).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_client_lecture_s227.py tests/test_dossier_s227.py -v`
Expected: PASS (6/6 — les 4 tests de Task 6 + les 2 nouveaux)

- [ ] **Step 6: Run full forge/core test suite for regressions**

Run: `cd briques/forge/forge/core && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add briques/forge/forge/core/app/auth.py briques/forge/forge/core/app/routers/ventures.py briques/forge/forge/core/tests/test_client_lecture_s227.py
git commit -m "feat(forge): S227 — rôle client_lecture scopé à une venture sur GET /ventures/{id}/dossier"
```

---

### Task 8: Test d'intégration bout-en-bout (mock réseau)

**Files:**
- Test: `briques/forge/forge/core/tests/test_dossier_integration_s227.py`

**Interfaces:**
- Consumes: tout ce qui précède (Tasks 1-7). Aucune nouvelle interface produite — ce test valide le flux complet demandé par le spec : « Venture créée → geo_object lié → document ingéré avec `venture_id` → dossier agrégé contient bien les trois. »

- [ ] **Step 1: Write the test**

```python
# briques/forge/forge/core/tests/test_dossier_integration_s227.py
"""S227 : bout-en-bout (mock réseau) — création venture, liaison geo/audit,
document ingéré, lecture du dossier agrégé. Motif : test réel, réseau mocké,
jamais simulé silencieusement (cf. audit/test_audit.py, forge/test_crm_import_lot.py)."""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.auth import UserContext, get_current_user
import app.routers.ventures as ventures_mod


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
        obj.id = "11111111-1111-1111-1111-111111111111"
        obj.created_at = obj.updated_at = None


async def test_venture_creee_puis_dossier_agrege_bout_en_bout(client, monkeypatch):
    client.app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(ventures_mod.settings, "GEO_URL", "http://geo.test")
    monkeypatch.setattr(ventures_mod.settings, "AUDIT_URL", "http://audit.test")
    monkeypatch.setattr(ventures_mod.settings, "INGESTION_URL", "http://ingestion.test")

    # 1. Création de la venture (type='audit').
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[]))
    creation = await client.post("/api/ventures", json={"nom": "Client Acme", "type": "audit"})
    assert creation.status_code == 201
    vid = creation.json()["id"]

    # 2. Liaison geo_object_id + audit_id (PATCH).
    v = SimpleNamespace(
        id=vid, owner_id="user-1", org_id=None, nom="Client Acme", description="",
        emoji="🚀", couleur="#6366f1", type="audit", statut="actif",
        created_at=None, updated_at=None,
        geo_object_id=None, audit_id=None, profil_entreprise=None,
    )
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[v]]))
    liaison = await client.patch(f"/api/ventures/{vid}", json={"geoObjectId": "geo-1", "auditId": "audit-1"})
    assert liaison.status_code == 200
    v.geo_object_id, v.audit_id = "geo-1", "audit-1"

    # 3. Document ingéré avec venture_id (simulé côté ingestion via le mock réseau
    #    du dossier — l'upload réel est couvert par Task 3 côté ingestion).

    # 4. Lecture du dossier agrégé : identite (geo) + audit (business) + documents.
    async def _fake_get(self, url, **kw):
        if "geo.test" in url:
            return httpx.Response(200, json={"id": "geo-1", "metadata": {"nom": "Acme"}})
        if "audit.test" in url:
            return httpx.Response(200, json={"id": "audit-1", "statut": "termine"})
        if "ingestion.test" in url:
            return httpx.Response(200, json={"total": 1, "offset": 0,
                                             "documents": [{"id": "doc-1", "nom": "contrat.pdf"}]})
        return httpx.Response(404)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(ventures_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[v], [], []]))
    dossier = await client.get(f"/api/ventures/{vid}/dossier")
    client.app.dependency_overrides.clear()

    assert dossier.status_code == 200
    body = dossier.json()
    assert body["identite"]["id"] == "geo-1"
    assert body["audit"]["id"] == "audit-1"
    assert body["documents"] == [{"id": "doc-1", "nom": "contrat.pdf"}]
```

- [ ] **Step 2: Run test to verify it passes (no new implementation needed — Tasks 1-7 already cover this flow)**

Run: `cd briques/forge/forge/core && python -m pytest tests/test_dossier_integration_s227.py -v`
Expected: PASS. Si ÉCHEC, c'est le signal que Tasks 1-7 ont une lacune d'intégration — corriger la task en amont plutôt que de contourner ici.

- [ ] **Step 3: Run the FULL S227 test suite (forge + ingestion + geo)**

Run:
```bash
cd briques/forge/forge/core && python -m pytest tests/ -v
cd ../../../ingestion && python -m pytest test_venture_id_s227.py test_ingestion.py -v
cd ../geo && python -m pytest test_lire_objet_s227.py -v
```
Expected: PASS partout, zéro régression.

- [ ] **Step 4: Commit**

```bash
git add briques/forge/forge/core/tests/test_dossier_integration_s227.py
git commit -m "test(forge): S227 — intégration bout-en-bout venture→geo→audit→ingestion→dossier"
```

---

## Self-Review Notes (pour la personne qui exécute ce plan)

- **Task 4, Step 2** : le nom exact de l'attribut de chemin DB dans `briques/geo/stockage.py` n'a pas été confirmé par la recherche (seule `lire_objet`/`creer_objet`/`_conn` ont été lues). Vérifier `grep -n "DB_CHEMIN\|DB_PATH" briques/geo/stockage.py` avant d'écrire la fixture de test — adapter le nom monkeypatché en conséquence (`ingestion` utilise `DB_CHEMIN`, `jeu-factions` utilise `DB_PATH` : les deux conventions coexistent dans le repo).
- **Hors périmètre confirmé** (ne pas dériver pendant l'exécution) : UI Forge, retrait des `AuditMissions` internes, propagation de `venture_id` dans `briques/audit`, S228/S229/S230.
- **Ordre des tasks** : strictement séquentiel (1→8), chaque task suivante dépend d'au moins une interface produite par une task antérieure (voir blocs `Interfaces`).
