# S238 — Recherche Mémoire avec repli lexical : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** la recherche Mémoire retrouve les références exactes, les noms et les termes métier, y compris sans embedder, sans fuite entre espaces, avec une mesure avant/après.

**Architecture :** l'embedder signale ses échecs au lieu d'inventer un vecteur. Trois branches SQL indépendantes (références exactes, plein texte/trigrammes, vecteur) partagent un seul constructeur de conditions (espace, statut, filtres). Des fonctions pures fusionnent les classements par RRF et placent les références exactes en tête. Le schéma lexical (colonne `tsvector` générée, index GIN et trigramme) est posé par une migration idempotente jouée au démarrage et dans les tests.

**Tech Stack :** Python 3.12, FastAPI 0.115, SQLAlchemy 2 async + asyncpg, PostgreSQL 16 + pgvector 0.8.2, extensions `unaccent` et `pg_trgm`, APScheduler, pytest + pytest-asyncio 0.26, Docker.

**Spec :** `docs/superpowers/specs/2026-10-05-S238-memoire-repli-lexical-design.md`.

## Global Constraints

- Branche : `sprint/s238-memoire-repli-lexical` (déjà créée, spec committée).
- Code, commentaires, messages et noms nouveaux en français, comme le reste de la brique.
- Backend : `briques/memoire/memory/backend/` (abrégé `backend/` ci-dessous). Adaptateur : `briques/memoire/main.py`.
- Les tests du backend tournent **uniquement** via `backend/scripts/en_docker.sh` (Postgres neuf `pgvector/pgvector:0.8.2-pg16`, Python 3.12). Docker Desktop doit être lancé (`open -a Docker`). Ne jamais lancer `pytest` du backend sur le poste.
- Les tests de l'adaptateur tournent via `scripts/tests_briques.sh memoire` depuis la racine du dépôt.
- RRF : `k = 60`. Seuil trigramme : `0.3`. Similarité cosinus minimale de la branche vectorielle : `0.25`. Candidats par branche : `max(limit, 50)`. Revectorisation : lots de 50, toutes les 10 minutes.
- Une référence est une expression entre guillemets (`"…"`, `« … »`, `“…”`) ou un jeton d'au moins 2 caractères contenant au moins un caractère alphanumérique et (un chiffre ou l'un de `- _ . / @ #`).
- Correspondances : `exacte | lexicale | vectorielle | les_deux`. Modes : `hybride | lexical`, en-tête `X-Memoire-Mode`.
- Aucune erreur SQL masquée : seule `EmbeddingIndisponible` fait passer en mode lexical.
- Valeurs de référence avant S238 : backend 50 tests verts (avec pytest-asyncio 0.26.0), adaptateur 59 tests verts.
- Commits : messages en anglais, terminés par les deux lignes d'attribution de la session.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `backend/scripts/en_docker.sh` (créé) | Lance une commande du backend contre un Postgres neuf |
| `backend/requirements.txt` (modifié) | pytest-asyncio 0.24.0 → 0.26.0 |
| `briques/memoire/pytest.ini` (modifié) | Commentaire : les tests du backend ont désormais un lanceur |
| `backend/app/llm/embedder.py` (modifié) | `EmbeddingIndisponible`, plus de vecteur inventé |
| `backend/app/services/embed_service.py` (modifié) | Embedding différé, `revectoriser_manquants` |
| `backend/app/scheduler.py` (modifié) | Tâche planifiée de revectorisation |
| `backend/app/routers/search.py`, `collections.py` (modifiés) | 503 pour le sémantique ; en-tête de mode |
| `backend/app/migrations_demarrage.py` (créé) | Migrations idempotentes : historiques S109–S112 et S238 |
| `backend/app/main.py` (modifié) | Le lifespan appelle `appliquer_migrations` |
| `briques/memoire/init-pgvector.sql` (modifié) | `unaccent` et `pg_trgm` pour les installations neuves |
| `backend/app/services/recherche_fusion.py` (créé) | Fonctions pures : références, RRF, ordre final |
| `backend/app/services/recherche_conditions.py` (créé) | Clause WHERE unique (espace, statut, filtres) |
| `backend/app/services/recherche_lexicale.py` (créé) | Plein texte, trigrammes, références exactes |
| `backend/app/services/recherche_vectorielle.py` (créé) | Classement pgvector |
| `backend/app/services/search_service.py` (réécrit) | Orchestration et hydratation |
| `backend/app/schemas/search.py` (modifié) | `SearchResult.correspondance` |
| `backend/tests/outils_embedder.py` (créé) | Embedder factice ou en panne pour les tests |
| `backend/scripts/mesure_recherche.py`, `corpus_mesure.json` (créés) | Mesure avant/après |
| `briques/memoire/main.py`, `manifest.json`, `test_memoire.py` (modifiés) | `/rappeler` propage `mode` et `correspondance` |
| `docs/sprints/S238-memoire-repli-lexical-resultats.md` (créé) | Résultats chiffrés et preuve LIVE |

---

### Task 1 : Lanceur de tests Docker et épinglage pytest-asyncio

Constat du 2026-10-05 : avec `pytest-asyncio==0.24.0`, 48 tests du backend sur 50 échouent (« attached to a different loop »). L'option `asyncio_default_test_loop_scope` de `pytest.ini` n'existe qu'à partir de 0.26. Avec 0.26.0, les 50 passent.

**Files :**
- Create : `briques/memoire/memory/backend/scripts/en_docker.sh`
- Delete : `briques/memoire/memory/backend/scripts/tests_docker.sh` (brouillon non committé de la session de conception)
- Modify : `briques/memoire/memory/backend/requirements.txt`
- Modify : `briques/memoire/pytest.ini` (commentaire d'en-tête)

**Interfaces :**
- Produces : `scripts/en_docker.sh <commande…>`, à lancer depuis `backend/`. La commande s'exécute dans `/src` (backend monté en lecture seule) avec `TEST_DATABASE_URL` pointant sur une base neuve, puis tout est détruit. Les variables `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY` et `EMBEDDING_MODEL` sont transmises si elles sont définies. `host.docker.internal` est résolu vers l'hôte.

- [ ] **Step 1 : écrire le lanceur**

`briques/memoire/memory/backend/scripts/en_docker.sh` :

```bash
#!/usr/bin/env bash
# S238 — exécute une commande du backend Memory contre un Postgres+pgvector NEUF, dans Docker.
#
# Les tests du backend exigent une vraie base (pgvector, plein texte, trigrammes) : on monte
# un réseau jetable et la même image de base que la production (pgvector/pgvector:0.8.2-pg16),
# puis la commande tourne sous le Python du Dockerfile (3.12). Tout est détruit à la sortie.
#
# Usage (depuis briques/memoire/memory/backend) :
#   scripts/en_docker.sh python -m pytest -q [args pytest…]
#   scripts/en_docker.sh python scripts/mesure_recherche.py
# Transmises au conteneur si définies : LLM_PROVIDER LLM_BASE_URL LLM_API_KEY EMBEDDING_MODEL.
set -euo pipefail

[ $# -gt 0 ] || { echo "usage : $0 <commande…>" >&2; exit 2; }

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUFFIXE="$$"
RESEAU="memoire-essai-$SUFFIXE"
BASE="memoire-essai-db-$SUFFIXE"

nettoyer() {
  docker rm -f "$BASE" >/dev/null 2>&1 || true
  docker network rm "$RESEAU" >/dev/null 2>&1 || true
}
trap nettoyer EXIT

docker network create "$RESEAU" >/dev/null
docker run -d --name "$BASE" --network "$RESEAU" \
  -e POSTGRES_USER=memory -e POSTGRES_PASSWORD=memory -e POSTGRES_DB=memory_test \
  pgvector/pgvector:0.8.2-pg16 >/dev/null

pret=0
for _ in $(seq 1 60); do
  if docker exec "$BASE" pg_isready -U memory -d memory_test >/dev/null 2>&1; then pret=1; break; fi
  sleep 1
done
[ "$pret" = 1 ] || { echo "✗ Postgres de test jamais prêt" >&2; exit 1; }

transmises=()
for v in LLM_PROVIDER LLM_BASE_URL LLM_API_KEY EMBEDDING_MODEL; do
  if [ -n "${!v:-}" ]; then transmises+=(-e "$v=${!v}"); fi
done

docker run --rm --network "$RESEAU" -v "$ICI":/src:ro -w /src \
  --add-host host.docker.internal:host-gateway \
  -e TEST_DATABASE_URL="postgresql+asyncpg://memory:memory@$BASE:5432/memory_test" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  ${transmises[@]+"${transmises[@]}"} \
  python:3.12-slim sh -c '
    pip install -q --no-cache-dir --root-user-action=ignore -r requirements.txt "bcrypt==4.0.1" >/dev/null &&
    exec "$@"' _ "$@"
```

Puis :

```bash
cd briques/memoire/memory/backend
chmod +x scripts/en_docker.sh
rm -f scripts/tests_docker.sh
```

- [ ] **Step 2 : constater l'échec avec la version épinglée actuelle**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q 2>&1 | tail -1`
Expected : `48 failed, 2 passed`.

- [ ] **Step 3 : corriger l'épinglage**

Dans `briques/memoire/memory/backend/requirements.txt`, remplacer la ligne `pytest-asyncio==0.24.0` par :

```
pytest-asyncio==0.26.0
```

- [ ] **Step 4 : vérifier**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q 2>&1 | tail -1`
Expected : `50 passed`.

- [ ] **Step 5 : mettre à jour le commentaire du filet rapide**

Dans `briques/memoire/pytest.ini`, remplacer le paragraphe qui commence par « `testpaths` exclut délibérément » et finit par « pas un préalable au filet. » par :

```ini
# `testpaths` exclut délibérément `memory/backend/tests/` : ce sont des tests d'INTÉGRATION
# qui exigent un vrai Postgres+pgvector. Depuis S238 ils ont leur propre lanceur, qui monte
# une base neuve dans Docker :
#     cd memory/backend && scripts/en_docker.sh python -m pytest -p no:cacheprovider -q
# (leur échec historique venait de pytest-asyncio 0.24, qui ignorait la portée de boucle
# déclarée dans memory/backend/pytest.ini — pas d'un schéma non migré).
```

Remplacer aussi la dernière ligne du commentaire, « Dette assumée et tracée : … restent hors filet. », par :

```ini
# Le filet rapide (scripts/tests_briques.sh) ne monte pas de base : il reste sur ces fichiers.
```

- [ ] **Step 6 : commit**

```bash
git add briques/memoire/memory/backend/scripts/en_docker.sh briques/memoire/memory/backend/requirements.txt briques/memoire/pytest.ini
git commit -m "test(memoire): Docker runner for backend tests, pin pytest-asyncio 0.26"
```

---

### Task 2 : Embedder honnête, embedding différé, revectorisation, 503 sémantique

**Files :**
- Modify : `backend/app/llm/embedder.py` (fichier entier)
- Modify : `backend/app/services/embed_service.py` (fichier entier)
- Modify : `backend/app/scheduler.py`
- Modify : `backend/app/routers/search.py` (route `/semantic`)
- Modify : `backend/app/routers/collections.py:276-279`
- Modify : `backend/app/services/search_service.py:28-30` (garde temporaire, remplacée en Task 6)
- Create : `backend/tests/outils_embedder.py`
- Modify : `backend/tests/conftest.py`
- Test : `backend/tests/test_embedder.py`

**Interfaces :**
- Produces :
  - `app.llm.embedder.EmbeddingIndisponible(Exception)`.
  - `Embedder.embed_text(text: str) -> list[float] | None` : `None` si le texte est vide ou blanc ; lève `EmbeddingIndisponible` en cas d'échec.
  - `EmbedService.embed_node(node_id) -> list[float] | None`.
  - `EmbedService.revectoriser_manquants(limite: int = 50) -> int` : renvoie le nombre de souvenirs vectorisés.
  - `app.scheduler.run_revectorisation()`.
  - Tests : `tests.outils_embedder.vecteur_factice(texte) -> list[float]`, `activer_embedder_factice(monkeypatch)`, `couper_embedder(monkeypatch)`.
  - Fixtures : `embedder_en_panne` (autouse, active par défaut) et `embedder_factice`.

- [ ] **Step 1 : outils d'embedder pour les tests**

`backend/tests/outils_embedder.py` :

```python
"""Embedder simulé pour les tests (S238).

Aucun test ne doit joindre un vrai Gateway. Par défaut l'embedder est EN PANNE (fixture
autouse du conftest) ; un test qui veut des vecteurs active l'embedder factice : un sac de
mots haché sur 384 dimensions, déterministe, avec quelques synonymes pour simuler une
proximité de sens que le lexical ne voit pas (« automobile » ≈ « voiture »).
"""
import hashlib
import math
import re

from app.llm.client import LLMClient

SYNONYMES_FACTICES = {"automobile": "voiture", "vehicule": "voiture", "véhicule": "voiture"}


def vecteur_factice(texte: str) -> list[float]:
    v = [0.0] * 384
    for mot in re.findall(r"\w+", texte.lower()):
        mot = SYNONYMES_FACTICES.get(mot, mot)
        v[int(hashlib.sha256(mot.encode()).hexdigest(), 16) % 384] += 1.0
    norme = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norme for x in v]


def activer_embedder_factice(monkeypatch) -> None:
    async def _embed(self, text: str) -> list[float]:
        return vecteur_factice(text)

    monkeypatch.setattr(LLMClient, "embed", _embed)


def couper_embedder(monkeypatch) -> None:
    async def _panne(self, text: str) -> list[float]:
        raise ConnectionError("Gateway injoignable (simulé)")

    monkeypatch.setattr(LLMClient, "embed", _panne)
```

Dans `backend/tests/conftest.py`, ajouter après l'import `from passlib.hash import bcrypt` :

```python
from tests.outils_embedder import activer_embedder_factice, couper_embedder
```

Puis ajouter après la fixture `test_node` :

```python
# ── Embedder (S238) : en panne par défaut, aucun test ne joint un vrai Gateway ──
@pytest.fixture(autouse=True)
def embedder_en_panne(monkeypatch):
    couper_embedder(monkeypatch)


@pytest.fixture
def embedder_factice(monkeypatch, embedder_en_panne):
    activer_embedder_factice(monkeypatch)
```

Ajouter enfin, après la fixture `auth_headers`, une fixture pour un second utilisateur (servira à l'isolation, Task 6) :

```python
@pytest_asyncio.fixture
async def autres_headers(client):
    uid = uuid.uuid4().hex[:8]
    email = f"autre_{uid}@example.com"
    async with db_module.async_session_factory() as db:
        db.add(User(email=email, display_name="Autre", password_hash=bcrypt.hash("password123")))
        await db.commit()
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
```

- [ ] **Step 2 : écrire les tests qui doivent échouer**

`backend/tests/test_embedder.py` :

```python
import uuid

import pytest
from sqlalchemy import select

from app import database as db_module
from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node
from app.services.embed_service import EmbedService
from tests.outils_embedder import activer_embedder_factice, couper_embedder, vecteur_factice

pytestmark = pytest.mark.asyncio


async def _embedding(node_id: str):
    async with db_module.async_session_factory() as db:
        r = await db.execute(select(Node.embedding).where(Node.id == uuid.UUID(node_id)))
        return r.scalar_one()


async def _creer(client, headers, space_id, titre, contenu=""):
    r = await client.post(
        f"/api/v1/spaces/{space_id}/nodes",
        json={"type": "input", "title": titre, "content_md": contenu},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestEmbedder:
    async def test_panne_leve_au_lieu_d_inventer(self):
        with pytest.raises(EmbeddingIndisponible):
            await Embedder().embed_text("bonjour")

    async def test_texte_vide_renvoie_none(self, embedder_factice):
        assert await Embedder().embed_text("   ") is None

    async def test_factice_renvoie_le_vecteur(self, embedder_factice):
        assert await Embedder().embed_text("bonjour") == vecteur_factice("bonjour")


class TestEmbeddingDiffere:
    async def test_creation_en_panne_enregistre_sans_vecteur(self, client, auth_headers, test_space):
        nid = await _creer(client, auth_headers, test_space["id"], "Note en panne", "contenu")
        assert await _embedding(nid) is None

    async def test_creation_titre_seul_est_vectorisee(self, client, auth_headers, test_space, embedder_factice):
        nid = await _creer(client, auth_headers, test_space["id"], "Titre seul")
        assert await _embedding(nid) is not None

    async def test_modification_en_panne_efface_le_vecteur_perime(self, client, auth_headers, test_space, monkeypatch):
        activer_embedder_factice(monkeypatch)
        nid = await _creer(client, auth_headers, test_space["id"], "Avant", "ancien contenu")
        assert await _embedding(nid) is not None
        couper_embedder(monkeypatch)
        r = await client.put(
            f"/api/v1/spaces/{test_space['id']}/nodes/{nid}",
            json={"content_md": "nouveau contenu"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert await _embedding(nid) is None


class TestRevectorisation:
    async def test_revectorise_les_manquants(self, client, auth_headers, test_space, monkeypatch):
        nid = await _creer(client, auth_headers, test_space["id"], "Différé", "à vectoriser")
        activer_embedder_factice(monkeypatch)
        async with db_module.async_session_factory() as db:
            faits = await EmbedService(db).revectoriser_manquants(limite=500)
        assert faits >= 1
        assert await _embedding(nid) is not None

    async def test_s_arrete_au_premier_echec(self, client, auth_headers, test_space, monkeypatch):
        await _creer(client, auth_headers, test_space["id"], "Un", "a")
        await _creer(client, auth_headers, test_space["id"], "Deux", "b")
        appels = {"n": 0}

        async def _une_seule_reussite(self, text):
            appels["n"] += 1
            if appels["n"] > 1:
                raise ConnectionError("panne au 2e appel")
            return vecteur_factice(text)

        from app.llm.client import LLMClient
        monkeypatch.setattr(LLMClient, "embed", _une_seule_reussite)
        async with db_module.async_session_factory() as db:
            faits = await EmbedService(db).revectoriser_manquants(limite=500)
        assert faits == 1
        assert appels["n"] == 2


class TestSemantique503:
    async def test_semantic_en_panne_repond_503(self, client, auth_headers, test_space):
        r = await client.post(
            f"/api/v1/spaces/{test_space['id']}/search/semantic",
            json={"query": "bonjour"},
            headers=auth_headers,
        )
        assert r.status_code == 503
        assert "indisponible" in r.json()["detail"]
```

Avant d'écrire le test de modification, vérifier dans `backend/app/routers/nodes.py` la méthode HTTP de la route de mise à jour (`PUT` ou `PATCH`) et l'utiliser.

- [ ] **Step 3 : vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_embedder.py 2>&1 | tail -3`
Expected : FAIL, `ImportError: cannot import name 'EmbeddingIndisponible'`.

- [ ] **Step 4 : implémenter**

`backend/app/llm/embedder.py` (fichier entier) :

```python
from app.llm.client import LLMClient


class EmbeddingIndisponible(Exception):
    """L'embedder n'a pas pu vectoriser le texte (Gateway injoignable, modèle absent…).

    Avant S238, l'échec était masqué par un vecteur pseudo-aléatoire constant (graine 42) :
    stocké comme réel à l'écriture, et donnant en recherche des scores tous égaux présentés
    comme un succès. L'échec est désormais signalé ; chaque appelant décide (embedding
    différé, recherche lexicale seule, 503)."""


class Embedder:
    def __init__(self):
        self.client = LLMClient()

    async def embed_text(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None
        try:
            return await self.client.embed(text[:8000])
        except Exception as exc:
            raise EmbeddingIndisponible(str(exc) or type(exc).__name__) from exc

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return [await self.embed_text(text) for text in texts]
```

`backend/app/services/embed_service.py` (fichier entier ; `embed_all_missing`, jamais appelé, est remplacé par `revectoriser_manquants`) :

```python
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node, NodeStatus

journal = logging.getLogger(__name__)


def _texte(node: Node) -> str:
    return f"{node.title}\n{node.content_md or ''}"


class EmbedService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = Embedder()

    async def embed_node(self, node_id: UUID) -> Optional[list[float]]:
        """Vectorise un souvenir. Embedder en panne : le vecteur est remis à NULL (il
        décrirait l'ancien contenu) et la tâche `revectoriser_manquants` le recalculera ;
        l'écriture du souvenir, elle, n'échoue jamais pour autant."""
        result = await self.db.execute(select(Node).where(Node.id == node_id))
        node = result.scalar_one_or_none()
        if not node:
            return None
        try:
            embedding = await self.embedder.embed_text(_texte(node))
        except EmbeddingIndisponible as exc:
            journal.warning("Embedding différé pour le souvenir %s : %s", node_id, exc)
            embedding = None
        node.embedding = embedding
        await self.db.commit()
        return embedding

    async def revectoriser_manquants(self, limite: int = 50) -> int:
        """Vectorise jusqu'à `limite` souvenirs sans vecteur (tous espaces). S'arrête au
        premier échec de l'embedder : inutile d'insister pendant une panne."""
        result = await self.db.execute(
            select(Node)
            .where(
                Node.embedding.is_(None),
                Node.status.in_([NodeStatus.active, NodeStatus.archived]),
                or_(
                    func.length(func.trim(Node.title)) > 0,
                    func.length(func.trim(func.coalesce(Node.content_md, ""))) > 0,
                ),
            )
            .order_by(Node.updated_at.desc())
            .limit(limite)
        )
        faits = 0
        for node in result.scalars().all():
            try:
                embedding = await self.embedder.embed_text(_texte(node))
            except EmbeddingIndisponible as exc:
                journal.warning("Revectorisation interrompue (embedder indisponible) : %s", exc)
                break
            if embedding is not None:
                node.embedding = embedding
                faits += 1
        await self.db.commit()
        return faits
```

Dans `backend/app/scheduler.py`, ajouter l'import `from app.services.embed_service import EmbedService`, la fonction :

```python
async def run_revectorisation():
    """S238 : les souvenirs écrits pendant une panne de l'embedder sont vectorisés ensuite."""
    async with async_session_factory() as session:
        await EmbedService(session).revectoriser_manquants()
```

et, dans `start_scheduler()`, avant `scheduler.start()` :

```python
    scheduler.add_job(
        run_revectorisation,
        IntervalTrigger(minutes=10),
        id="revectorisation",
        replace_existing=True,
    )
```

Dans `backend/app/routers/search.py`, ajouter les imports `from fastapi import HTTPException` et `from app.llm.embedder import EmbeddingIndisponible`, puis remplacer le corps de `semantic_search` par :

```python
    svc = SearchService(db)
    try:
        return await svc.vector_search(space_id, req.query, limit=req.limit, stage_filter=req.stage_filter, type_filter=req.type_filter)
    except EmbeddingIndisponible:
        raise HTTPException(status_code=503, detail="Recherche sémantique indisponible (embedder injoignable).")
```

Dans `backend/app/routers/collections.py`, ajouter l'import `from app.llm.embedder import EmbeddingIndisponible` (à côté de l'import d'`Embedder`) et remplacer :

```python
    embedder = Embedder()
    query_embedding = await embedder.embed_text(q)
    if not query_embedding:
        return []
```

par :

```python
    embedder = Embedder()
    try:
        query_embedding = await embedder.embed_text(q)
    except EmbeddingIndisponible:
        raise HTTPException(status_code=503, detail="Recherche sémantique indisponible (embedder injoignable).")
    if not query_embedding:
        return []
```

Dans `backend/app/services/search_service.py`, méthode `hybrid_search`, remplacer :

```python
        query_embedding = await self.embedder.embed_text(query)
        if not query_embedding:
            return []
```

par la garde temporaire suivante, que la Task 6 supprimera :

```python
        from app.llm.embedder import EmbeddingIndisponible
        try:
            query_embedding = await self.embedder.embed_text(query)
        except EmbeddingIndisponible:
            return []  # temporaire : la Task 6 remplace par la recherche lexicale
        if not query_embedding:
            return []
```

- [ ] **Step 5 : vérifier**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q 2>&1 | tail -1`
Expected : tout vert (50 + 9 nouveaux = `59 passed`).

- [ ] **Step 6 : commit**

```bash
git add briques/memoire/memory/backend/app briques/memoire/memory/backend/tests
git commit -m "feat(memoire): honest embedder, deferred embedding, re-embedding job, 503 on semantic"
```

---

### Task 3 : Migrations de démarrage (schéma lexical et nettoyage graine 42)

**Files :**
- Create : `backend/app/migrations_demarrage.py`
- Modify : `backend/app/main.py` (lifespan, lignes 15-34)
- Modify : `backend/tests/conftest.py` (fixture `setup_db`)
- Modify : `briques/memoire/init-pgvector.sql`
- Test : `backend/tests/test_migrations.py`

**Interfaces :**
- Produces :
  - `app.migrations_demarrage.appliquer_migrations(conn: AsyncConnection) -> None`, à appeler après `create_all`.
  - `vecteur_graine_42() -> list[float]`.
  - Fonction SQL `memoire_unaccent(text)`, colonne `nodes.recherche_tsv`, index `idx_nodes_recherche_tsv` et `idx_nodes_texte_trgm`.
  - Expression normalisée utilisée par les tâches suivantes : `memoire_unaccent(lower(coalesce(n.title, '') || ' ' || coalesce(n.content_md, '')))`.

- [ ] **Step 1 : écrire les tests qui doivent échouer**

`backend/tests/test_migrations.py` :

```python
import uuid

import pytest
from sqlalchemy import select, text

from app import database as db_module
from app.migrations_demarrage import appliquer_migrations, vecteur_graine_42
from app.models.node import IpCraStage, Node, NodeType
from tests.outils_embedder import vecteur_factice

pytestmark = pytest.mark.asyncio


class TestMigrations:
    async def test_idempotente(self):
        async with db_module.engine.begin() as conn:
            await appliquer_migrations(conn)
            await appliquer_migrations(conn)

    async def test_extensions_et_colonne(self):
        async with db_module.engine.begin() as conn:
            ext = set((await conn.execute(text("SELECT extname FROM pg_extension"))).scalars())
            assert {"vector", "unaccent", "pg_trgm"} <= ext
            col = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name='nodes' AND column_name='recherche_tsv'"
            ))
            assert col.scalar() == 1

    async def test_tsv_sans_accents_et_stemme(self, test_space):
        async with db_module.async_session_factory() as db:
            node = Node(space_id=uuid.UUID(test_space["id"]), type=NodeType.input, ipcra_stage=IpCraStage.input,
                        title="Réunion budget", content_md="Les factures fournisseurs")
            db.add(node)
            await db.commit()
            r = await db.execute(text(
                "SELECT recherche_tsv @@ to_tsquery('simple', 'reunion'),"
                "       recherche_tsv @@ to_tsquery('french', 'facture')"
                " FROM nodes WHERE id = :id"), {"id": node.id})
            assert tuple(r.one()) == (True, True)

    async def test_nettoie_la_graine_42_et_seulement_elle(self, test_space):
        sid = uuid.UUID(test_space["id"])
        async with db_module.async_session_factory() as db:
            empoisonne = Node(space_id=sid, type=NodeType.input, ipcra_stage=IpCraStage.input,
                              title="Écrit pendant une panne", content_md="x", embedding=vecteur_graine_42())
            sain = Node(space_id=sid, type=NodeType.input, ipcra_stage=IpCraStage.input,
                        title="Sain", content_md="y", embedding=vecteur_factice("sain"))
            db.add_all([empoisonne, sain])
            await db.commit()
            ids = (empoisonne.id, sain.id)
        async with db_module.engine.begin() as conn:
            await appliquer_migrations(conn)
        async with db_module.async_session_factory() as db:
            vecs = dict((await db.execute(select(Node.id, Node.embedding).where(Node.id.in_(ids)))).all())
        assert vecs[ids[0]] is None
        assert vecs[ids[1]] is not None
```

- [ ] **Step 2 : vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_migrations.py 2>&1 | tail -3`
Expected : FAIL, `ModuleNotFoundError: No module named 'app.migrations_demarrage'`.

- [ ] **Step 3 : implémenter**

`backend/app/migrations_demarrage.py` :

```python
"""Migrations idempotentes jouées au démarrage, après `create_all` (pas d'Alembic ici).

Appelées par le lifespan ET par le conftest des tests : le schéma testé est celui de la
production. `create_all` crée les tables neuves mais n'altère jamais une table existante :
toute colonne, extension ou index ajouté après coup passe par ici.
"""
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Texte normalisé d'un souvenir (alias `n`) : minuscules, sans accents. Partagé par l'index
# trigramme ci-dessous et par les requêtes lexicales — ils doivent rester identiques pour
# que l'index serve.
TEXTE_NORMALISE = "memoire_unaccent(lower(coalesce(n.title, '') || ' ' || coalesce(n.content_md, '')))"

_INSTRUCTIONS = [
    # S109 : position libre sur le canvas graphe.
    "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS canvas_pos JSONB",
    # S110 : drapeau d'historique opt-in (la table node_revisions vient de create_all).
    "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS track_history BOOLEAN NOT NULL DEFAULT FALSE",
    # S112 : journal temporel du graphe, opt-in par espace + soft-delete des liens.
    "ALTER TABLE spaces ADD COLUMN IF NOT EXISTS track_history BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE edges ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    # S238 : recherche lexicale indépendante de l'embedder.
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # unaccent() n'est que STABLE : une colonne générée et un index exigent IMMUTABLE. Le
    # dictionnaire étant nommé explicitement, l'enveloppe peut l'être sans mentir.
    """CREATE OR REPLACE FUNCTION memoire_unaccent(text) RETURNS text
       LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
       AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$""",
    # Titre en `simple` (noms propres et codes intacts, poids A) + titre et contenu en
    # `french` (pluriels, conjugaisons, poids B), le tout sans accents.
    """ALTER TABLE nodes ADD COLUMN IF NOT EXISTS recherche_tsv tsvector GENERATED ALWAYS AS (
         setweight(to_tsvector('simple', memoire_unaccent(coalesce(title, ''))), 'A') ||
         setweight(to_tsvector('french', memoire_unaccent(coalesce(title, '') || ' ' || coalesce(content_md, ''))), 'B')
       ) STORED""",
    "CREATE INDEX IF NOT EXISTS idx_nodes_recherche_tsv ON nodes USING gin (recherche_tsv)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_texte_trgm ON nodes USING gin "
    "((memoire_unaccent(lower(coalesce(title, '') || ' ' || coalesce(content_md, '')))) gin_trgm_ops)",
]


def vecteur_graine_42() -> list[float]:
    """Le faux vecteur que l'ancien Embedder renvoyait quand le Gateway tombait (avant S238)."""
    return np.random.default_rng(42).uniform(-0.1, 0.1, 384).tolist()


async def appliquer_migrations(conn: AsyncConnection) -> None:
    for instruction in _INSTRUCTIONS:
        await conn.execute(text(instruction))
    # Vecteurs graine 42 stockés comme réels pendant une panne : remis à NULL pour que la
    # tâche de revectorisation les recalcule (11 souvenirs sur le HP au 2026-10-05).
    graine = "[" + ",".join(str(v) for v in vecteur_graine_42()) + "]"
    await conn.execute(
        text("UPDATE nodes SET embedding = NULL "
             "WHERE embedding IS NOT NULL AND (embedding <=> CAST(:graine AS vector)) < 1e-6"),
        {"graine": graine},
    )
```

Dans `backend/app/main.py`, ajouter l'import `from app.migrations_demarrage import appliquer_migrations` et remplacer le corps du `async with engine.begin() as conn:` du lifespan (de `await conn.run_sync(Base.metadata.create_all)` jusqu'au dernier `ALTER TABLE edges …`) par :

```python
        await conn.run_sync(Base.metadata.create_all)
        # Colonnes, extensions et index ajoutés après coup (S109→S112, S238) : idempotent.
        await appliquer_migrations(conn)
```

Supprimer l'import `from sqlalchemy import text` de `main.py` s'il n'y sert plus.

Dans `backend/tests/conftest.py`, fixture `setup_db`, après `await conn.run_sync(Base.metadata.create_all)`, ajouter :

```python
        await appliquer_migrations(conn)
```

avec l'import `from app.migrations_demarrage import appliquer_migrations` à côté de `from app.database import Base`.

`briques/memoire/init-pgvector.sql` (fichier entier) :

```sql
-- Extensions requises par le backend Memory, activées à l'init du volume (avant la création
-- des tables). pgvector : colonne Vector(384). unaccent + pg_trgm : recherche lexicale S238
-- (le backend les active aussi au démarrage, pour les volumes déjà initialisés).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

- [ ] **Step 4 : vérifier**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q 2>&1 | tail -1`
Expected : `63 passed`.

- [ ] **Step 5 : commit**

```bash
git add briques/memoire/init-pgvector.sql briques/memoire/memory/backend/app briques/memoire/memory/backend/tests
git commit -m "feat(memoire): startup migrations for lexical schema and seed-42 vector cleanup"
```

---

### Task 4 : Fonctions pures de fusion

**Files :**
- Create : `backend/app/services/recherche_fusion.py`
- Test : `backend/tests/test_recherche_fusion.py`

**Interfaces :**
- Produces :
  - `extraire_references(requete: str) -> list[str]`
  - `motif_reference(reference: str) -> str` : motif ARE PostgreSQL ; le SQL l'applique sous `memoire_unaccent(lower(…))`.
  - `fusion_rrf(classements: list[list[UUID]], k: int = K_RRF) -> dict[UUID, float]`
  - `@dataclass(frozen=True) CorrespondanceExacte(references_trouvees: int, dans_titre: bool)`
  - `@dataclass(frozen=True) Classe(id: UUID, score: float, correspondance: str)`
  - `ordonner(exacts: dict[UUID, CorrespondanceExacte], lexical: list[UUID], vectoriel: list[UUID], limite: int) -> list[Classe]`
  - `K_RRF = 60`

- [ ] **Step 1 : écrire les tests qui doivent échouer**

`backend/tests/test_recherche_fusion.py` :

```python
import uuid

from app.services.recherche_fusion import (
    CorrespondanceExacte, extraire_references, fusion_rrf, motif_reference, ordonner,
)

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


class TestReferences:
    def test_code_avec_chiffre(self):
        assert extraire_references("bilan du S237b") == ["S237b"]

    def test_tirets_email_fichier(self):
        assert extraire_references("INV-2026-042 jean.dupont@exemple.fr docker-compose.yml.") == [
            "INV-2026-042", "jean.dupont@exemple.fr", "docker-compose.yml"]

    def test_guillemets(self):
        assert extraire_references('« réunion   budget » et "plan B" demain') == ["réunion budget", "plan B"]

    def test_mots_ordinaires_ignores(self):
        assert extraire_references("facture du garage") == []

    def test_doublons_insensibles_a_la_casse(self):
        assert extraire_references("S237b s237B") == ["S237b"]

    def test_ponctuation_seule_ignoree(self):
        assert extraire_references("a -- b") == []


class TestMotif:
    def test_echappe_et_borne(self):
        assert motif_reference("v1.2") == r"(^|[^[:alnum:]])v1\.2($|[^[:alnum:]])"

    def test_espaces_souples(self):
        assert motif_reference("réunion budget") == "(^|[^[:alnum:]])réunion[[:space:]]+budget($|[^[:alnum:]])"


class TestFusion:
    def test_rrf(self):
        s = fusion_rrf([[A, B], [B, C]])
        assert s[B] == 1 / 62 + 1 / 61  # fusion_rrf brute, sans epsilon de position
        assert s[B] > s[A] > s[C]

    def test_exacts_en_tete_meme_sans_fusion(self):
        r = ordonner({D: CorrespondanceExacte(1, False)}, [A, B], [B], limite=10)
        assert [c.id for c in r] == [D, B, A]
        assert [c.correspondance for c in r] == ["exacte", "les_deux", "lexicale"]

    def test_plus_de_references_avant_titre(self):
        r = ordonner({A: CorrespondanceExacte(1, True), B: CorrespondanceExacte(2, False)}, [], [], limite=10)
        assert [c.id for c in r] == [B, A]

    def test_titre_avant_contenu(self):
        r = ordonner({A: CorrespondanceExacte(1, False), B: CorrespondanceExacte(1, True)}, [], [], limite=10)
        assert [c.id for c in r] == [B, A]

    def test_vectorielle_seule_et_limite(self):
        r = ordonner({}, [A], [C], limite=1)
        assert len(r) == 1

    def test_scores_strictement_decroissants(self):
        r = ordonner({D: CorrespondanceExacte(1, False)}, [A, B, C], [C, B], limite=10)
        scores = [c.score for c in r]
        assert all(x > y for x, y in zip(scores, scores[1:]))
```

- [ ] **Step 2 : vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_recherche_fusion.py 2>&1 | tail -3`
Expected : FAIL, `ModuleNotFoundError`.

- [ ] **Step 3 : implémenter**

`backend/app/services/recherche_fusion.py` :

```python
"""Fonctions pures de la recherche Mémoire (S238) : références exactes, fusion RRF, ordre.

Aucun accès base ici. Les scores lexicaux (ts_rank_cd) et vectoriels (cosinus) ne sont pas
comparables : on ne les additionne jamais, on fusionne les RANGS (Reciprocal Rank Fusion).
"""
import re
from dataclasses import dataclass
from uuid import UUID

K_RRF = 60

_GUILLEMETS = re.compile(r'"([^"]+)"|«\s*([^»]+?)\s*»|“([^”]+)”')
_CARACTERES_REFERENCE = set("-_./@#")
_BORDS = ".,;:!?()[]{}'\"«»“”"


def _est_reference(jeton: str) -> bool:
    return (
        len(jeton) >= 2
        and any(c.isalnum() for c in jeton)
        and (any(c.isdigit() for c in jeton) or any(c in _CARACTERES_REFERENCE for c in jeton))
    )


def extraire_references(requete: str) -> list[str]:
    """Expressions entre guillemets, puis jetons qui ressemblent à un code (chiffre ou
    `-_./@#`). Dédoublonnées sans tenir compte de la casse, dans l'ordre d'apparition."""
    candidates = []
    for m in _GUILLEMETS.finditer(requete):
        expression = " ".join(next(g for g in m.groups() if g).split())
        if expression:
            candidates.append(expression)
    for jeton in _GUILLEMETS.sub(" ", requete).split():
        jeton = jeton.strip(_BORDS)
        if _est_reference(jeton):
            candidates.append(jeton)
    vues, references = set(), []
    for c in candidates:
        if c.casefold() not in vues:
            vues.add(c.casefold())
            references.append(c)
    return references


def motif_reference(reference: str) -> str:
    """Motif ARE PostgreSQL trouvant `reference` comme mot entier. Les caractères non
    alphanumériques sont échappés ; les espaces d'une expression acceptent tout blanc. Le SQL
    applique memoire_unaccent(lower(…)) au motif comme au texte (seuls des caractères non
    alphanumériques sont précédés d'une barre oblique : la normalisation ne change rien au
    sens du motif)."""
    morceaux = [re.sub(r"([^\w])", r"\\\1", m) for m in reference.split()]
    return "(^|[^[:alnum:]])" + "[[:space:]]+".join(morceaux) + "($|[^[:alnum:]])"


def fusion_rrf(classements: list[list[UUID]], k: int = K_RRF) -> dict[UUID, float]:
    scores: dict[UUID, float] = {}
    for classement in classements:
        for rang, ident in enumerate(classement, start=1):
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k + rang)
    return scores


@dataclass(frozen=True)
class CorrespondanceExacte:
    references_trouvees: int
    dans_titre: bool


@dataclass(frozen=True)
class Classe:
    id: UUID
    score: float
    correspondance: str  # exacte | lexicale | vectorielle | les_deux


def ordonner(
    exacts: dict[UUID, CorrespondanceExacte],
    lexical: list[UUID],
    vectoriel: list[UUID],
    limite: int,
) -> list[Classe]:
    """Références exactes d'abord (plus de références trouvées, puis titre avant contenu,
    puis rang de fusion), ensuite le reste par score RRF décroissant.

    Un score de fusion vaut au plus 2/(K_RRF+1) < 0,04 : le palier exact
    (1 + nombre de références + 0,5 si dans le titre) reste toujours au-dessus, et l'ordre
    par score décroissant reproduit exactement l'ordre voulu."""
    fusion = fusion_rrf([lexical, vectoriel])
    ens_lex, ens_vec = set(lexical), set(vectoriel)

    def correspondance(i: UUID) -> str:
        if i in exacts:
            return "exacte"
        if i in ens_lex and i in ens_vec:
            return "les_deux"
        return "lexicale" if i in ens_lex else "vectorielle"

    scores = {}
    for i in set(fusion) | set(exacts):
        s = fusion.get(i, 0.0)
        if i in exacts:
            s += 1.0 + exacts[i].references_trouvees + (0.5 if exacts[i].dans_titre else 0.0)
        scores[i] = s
    ordre = sorted(scores, key=lambda i: (-scores[i], str(i)))[:limite]
    # Deux souvenirs à rangs croisés (1er ici, 2e là, et inversement) ont le même score RRF :
    # un epsilon de position rend les scores strictement décroissants sans changer l'ordre.
    n = len(ordre)
    return [Classe(i, scores[i] + (n - pos) * 1e-9, correspondance(i)) for pos, i in enumerate(ordre)]
```

- [ ] **Step 4 : vérifier**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_recherche_fusion.py 2>&1 | tail -1`
Expected : `14 passed`.

- [ ] **Step 5 : commit**

```bash
git add briques/memoire/memory/backend/app/services/recherche_fusion.py briques/memoire/memory/backend/tests/test_recherche_fusion.py
git commit -m "feat(memoire): pure search functions — references, RRF fusion, final ordering"
```

---

### Task 5 : Branches de recherche (conditions, lexicale, vectorielle)

**Files :**
- Create : `backend/app/services/recherche_conditions.py`
- Create : `backend/app/services/recherche_lexicale.py`
- Create : `backend/app/services/recherche_vectorielle.py`
- Test : `backend/tests/test_recherche_branches.py`

**Interfaces :**
- Consumes : `motif_reference` et `CorrespondanceExacte` (Task 4), `TEXTE_NORMALISE` (Task 3), colonne `recherche_tsv` (Task 3).
- Produces :
  - `Filtres(space_id: UUID, type: str | None = None, etape: str | None = None, tier: str | None = None)` (dataclass figée)
  - `conditions_sql(f: Filtres) -> tuple[str, dict]`
  - `classement_plein_texte(db, requete: str, filtres: Filtres, limite: int) -> list[UUID]`
  - `classement_trigramme(db, requete: str, filtres: Filtres, limite: int) -> list[UUID]`
  - `correspondances_exactes(db, references: list[str], filtres: Filtres, limite: int) -> dict[UUID, CorrespondanceExacte]`
  - `classement_vectoriel(db, vecteur: list[float], filtres: Filtres, limite: int) -> list[UUID]`
  - Constantes : `SEUIL_TRIGRAMME = 0.3`, `SIMILARITE_MINIMALE = 0.25`, `TERMES_MAX = 32`.

- [ ] **Step 1 : écrire les tests qui doivent échouer**

`backend/tests/test_recherche_branches.py` :

```python
import uuid

import pytest

from app import database as db_module
from app.models.node import IpCraStage, Node, NodeStatus, NodeType, StorageTier
from app.services.recherche_conditions import Filtres
from app.services.recherche_lexicale import (
    classement_plein_texte, classement_trigramme, correspondances_exactes,
)
from app.services.recherche_vectorielle import classement_vectoriel
from tests.outils_embedder import vecteur_factice

pytestmark = pytest.mark.asyncio


async def _souvenirs(space_id, *specs):
    """specs : (titre, contenu, options) → ids dans l'ordre."""
    async with db_module.async_session_factory() as db:
        nodes = []
        for titre, contenu, opts in specs:
            n = Node(space_id=space_id, type=opts.get("type", NodeType.input),
                     ipcra_stage=opts.get("etape", IpCraStage.input),
                     storage_tier=opts.get("tier", StorageTier.hot),
                     status=opts.get("status", NodeStatus.active),
                     title=titre, content_md=contenu,
                     embedding=vecteur_factice(f"{titre}\n{contenu}") if opts.get("vecteur", True) else None)
            db.add(n)
            nodes.append(n)
        await db.commit()
        return [n.id for n in nodes]


async def _deux_espaces(client, auth_headers):
    ids = []
    for nom in ("Espace A", "Espace B"):
        r = await client.post("/api/v1/spaces", json={"name": nom}, headers=auth_headers)
        ids.append(uuid.UUID(r.json()["id"]))
    return ids


class TestPleinTexte:
    async def test_accents_pluriels_et_sans_vecteur(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        reunion, factures = await _souvenirs(a, ("Réunion budget", "", {"vecteur": False}),
                                             ("Fournisseurs", "Les factures du trimestre", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "reunion", Filtres(a), 10) == [reunion]
            assert await classement_plein_texte(db, "facture", Filtres(a), 10) == [factures]

    async def test_titre_classe_avant_contenu(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        contenu, titre = await _souvenirs(a, ("Divers", "parle de Kubernetes", {}),
                                          ("Kubernetes", "notes", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "kubernetes", Filtres(a), 10) == [titre, contenu]

    async def test_operateurs_tsquery_ignores(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        await _souvenirs(a, ("Le", "de la", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "&|!:*", Filtres(a), 10) == []


class TestTrigramme:
    async def test_faute_de_frappe(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        (factures,) = await _souvenirs(a, ("Fournisseurs", "Les factures du trimestre", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "facutre", Filtres(a), 10) == []
            assert await classement_trigramme(db, "facutre", Filtres(a), 10) == [factures]
            assert await classement_trigramme(db, "automobile", Filtres(a), 10) == []


class TestExactes:
    async def test_mot_entier_titre_et_compte(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        contenu, titre, voisin, deux = await _souvenirs(
            a,
            ("Compte rendu", "Sprint S237b terminé", {}),
            ("S237b résultats", "", {}),
            ("Plan", "Sprint S237 seulement", {}),
            ("Bilan", "S237b et INV-2026-042", {}),
        )
        async with db_module.async_session_factory() as db:
            r = await correspondances_exactes(db, ["S237b", "INV-2026-042"], Filtres(a), 10)
        assert voisin not in r
        assert r[deux].references_trouvees == 2
        assert r[titre].dans_titre and not r[contenu].dans_titre

    async def test_expression_et_accents(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        (n,) = await _souvenirs(a, ("Note", "la Réunion\n  Budget de mars", {}))
        async with db_module.async_session_factory() as db:
            r = await correspondances_exactes(db, ["reunion budget"], Filtres(a), 10)
        assert n in r


class TestVectoriel:
    async def test_synonyme_et_plancher(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        voiture, autre = await _souvenirs(a, ("Achat voiture", "", {}), ("Recette", "gâteau", {}))
        async with db_module.async_session_factory() as db:
            r = await classement_vectoriel(db, vecteur_factice("automobile"), Filtres(a), 10)
        assert r == [voiture]


class TestIsolationEtFiltres:
    async def test_aucune_branche_ne_sort_de_l_espace(self, client, auth_headers):
        a, b = await _deux_espaces(client, auth_headers)
        (dans_a,) = await _souvenirs(a, ("Projet Zéphyr Z-42", "", {}))
        await _souvenirs(b, ("Projet Zéphyr Z-42", "", {}))
        async with db_module.async_session_factory() as db:
            f = Filtres(a)
            assert await classement_plein_texte(db, "zephyr", f, 10) == [dans_a]
            assert await classement_trigramme(db, "zepyhr", f, 10) == [dans_a]
            assert list(await correspondances_exactes(db, ["Z-42"], f, 10)) == [dans_a]
            assert await classement_vectoriel(db, vecteur_factice("Projet Zéphyr Z-42"), f, 10) == [dans_a]

    async def test_filtres_et_statut(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        bon, mauvais_type, mauvais_tier, retire = await _souvenirs(
            a,
            ("Alpha", "", {"type": NodeType.projet, "etape": IpCraStage.projet, "tier": StorageTier.archive}),
            ("Alpha", "", {"type": NodeType.input, "etape": IpCraStage.projet, "tier": StorageTier.archive}),
            ("Alpha", "", {"type": NodeType.projet, "etape": IpCraStage.projet, "tier": StorageTier.hot}),
            ("Alpha", "", {"type": NodeType.projet, "etape": IpCraStage.projet, "tier": StorageTier.archive,
                           "status": NodeStatus.pending_removal}),
        )
        f = Filtres(a, type="projet", etape="projet", tier="archive")
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "alpha", f, 10) == [bon]
            assert list(await correspondances_exactes(db, ["Alpha"], f, 10)) == [bon]
            assert await classement_vectoriel(db, vecteur_factice("Alpha"), f, 10) == [bon]
```

- [ ] **Step 2 : vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_recherche_branches.py 2>&1 | tail -3`
Expected : FAIL, `ModuleNotFoundError: No module named 'app.services.recherche_conditions'`.

- [ ] **Step 3 : implémenter**

`backend/app/services/recherche_conditions.py` :

```python
"""Clause WHERE commune à TOUTES les branches de recherche (alias de table `n`).

Seul endroit où se décide quels souvenirs sont visibles : l'espace (le contrôle d'accès à
l'espace est fait en amont par `check_space_access`), le statut et les filtres. Aucune
branche ne construit sa propre clause : aucune ne peut oublier l'espace.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class Filtres:
    space_id: UUID
    type: Optional[str] = None
    etape: Optional[str] = None
    tier: Optional[str] = None


def conditions_sql(f: Filtres) -> tuple[str, dict]:
    conditions = ["n.space_id = :space_id", "n.status IN ('active', 'archived')"]
    params: dict = {"space_id": f.space_id}
    if f.type:
        conditions.append("n.type = :filtre_type")
        params["filtre_type"] = f.type
    if f.etape:
        conditions.append("n.ipcra_stage = :filtre_etape")
        params["filtre_etape"] = f.etape
    if f.tier:
        conditions.append("n.storage_tier = :filtre_tier")
        params["filtre_tier"] = f.tier
    return " AND ".join(conditions), params
```

`backend/app/services/recherche_lexicale.py` :

```python
"""Branche lexicale de la recherche Mémoire (S238) : indépendante de l'embedder.

Couvre tous les souvenirs visibles, qu'ils aient un vecteur ou non.
"""
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrations_demarrage import TEXTE_NORMALISE
from app.services.recherche_conditions import Filtres, conditions_sql
from app.services.recherche_fusion import CorrespondanceExacte, motif_reference

SEUIL_TRIGRAMME = 0.3
TERMES_MAX = 32
_TITRE_NORMALISE = "memoire_unaccent(lower(coalesce(n.title, '')))"


def termes(requete: str) -> list[str]:
    """Mots de la requête (lettres et chiffres seulement : aucun opérateur tsquery ne passe)."""
    return re.findall(r"[^\W_]+", requete.lower())[:TERMES_MAX]


async def classement_plein_texte(db: AsyncSession, requete: str, filtres: Filtres, limite: int) -> list[UUID]:
    """OU sur les termes, en `simple` et en `french`, classé par ts_rank_cd (plus de termes
    trouvés et titre de poids A = mieux classé)."""
    mots = termes(requete)
    if not mots:
        return []
    where, params = conditions_sql(filtres)
    morceaux = []
    for i, mot in enumerate(mots):
        params[f"t{i}"] = mot
        morceaux.append(
            f"plainto_tsquery('simple', memoire_unaccent(:t{i})) || plainto_tsquery('french', memoire_unaccent(:t{i}))"
        )
    params["limite"] = limite
    sql = text(f"""
        WITH q AS (SELECT ({' || '.join(morceaux)}) AS requete)
        SELECT n.id FROM nodes n, q
        WHERE {where} AND n.recherche_tsv @@ q.requete
        ORDER BY ts_rank_cd(n.recherche_tsv, q.requete) DESC, n.updated_at DESC, n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


async def classement_trigramme(db: AsyncSession, requete: str, filtres: Filtres, limite: int) -> list[UUID]:
    """Filet pour les fautes de frappe, utilisé quand le plein texte ne trouve rien."""
    if not requete.strip():
        return []
    where, params = conditions_sql(filtres)
    params.update(q=requete.strip(), seuil=SEUIL_TRIGRAMME, limite=limite)
    similarite = f"word_similarity(memoire_unaccent(lower(:q)), {TEXTE_NORMALISE})"
    sql = text(f"""
        SELECT n.id FROM nodes n
        WHERE {where} AND {similarite} >= :seuil
        ORDER BY {similarite} DESC, n.updated_at DESC, n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


async def correspondances_exactes(
    db: AsyncSession, references: list[str], filtres: Filtres, limite: int
) -> dict[UUID, CorrespondanceExacte]:
    """Souvenirs contenant littéralement au moins une référence (mot entier, sans casse ni
    accents), avec le nombre de références trouvées et la présence dans le titre."""
    if not references:
        return {}
    where, params = conditions_sql(filtres)
    comptes, titres = [], []
    for i, reference in enumerate(references):
        params[f"r{i}"] = motif_reference(reference)
        motif = f"memoire_unaccent(lower(:r{i}))"
        comptes.append(f"(CASE WHEN {TEXTE_NORMALISE} ~ {motif} THEN 1 ELSE 0 END)")
        titres.append(f"{_TITRE_NORMALISE} ~ {motif}")
    params["limite"] = limite
    sql = text(f"""
        SELECT id, trouvees, dans_titre FROM (
            SELECT n.id, n.updated_at, ({' + '.join(comptes)}) AS trouvees, ({' OR '.join(titres)}) AS dans_titre
            FROM nodes n WHERE {where}
        ) x
        WHERE trouvees > 0
        ORDER BY trouvees DESC, dans_titre DESC, updated_at DESC, id
        LIMIT :limite
    """)
    return {r[0]: CorrespondanceExacte(int(r[1]), bool(r[2])) for r in (await db.execute(sql, params)).all()}
```

`backend/app/services/recherche_vectorielle.py` :

```python
"""Branche vectorielle de la recherche Mémoire (S238) : seulement si la requête a un vecteur."""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recherche_conditions import Filtres, conditions_sql

# Sous ce cosinus, un souvenir n'est pas « proche » : sans plancher, la branche renverrait
# toujours ses N plus proches voisins, même sans rapport, et la fusion les remonterait.
SIMILARITE_MINIMALE = 0.25


async def classement_vectoriel(db: AsyncSession, vecteur: list[float], filtres: Filtres, limite: int) -> list[UUID]:
    where, params = conditions_sql(filtres)
    params.update(
        embedding="[" + ",".join(str(v) for v in vecteur) + "]",
        distance_max=1 - SIMILARITE_MINIMALE,
        limite=limite,
    )
    sql = text(f"""
        SELECT n.id FROM nodes n
        WHERE {where} AND n.embedding IS NOT NULL
          AND (n.embedding <=> CAST(:embedding AS vector)) <= :distance_max
        ORDER BY n.embedding <=> CAST(:embedding AS vector), n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]
```

- [ ] **Step 4 : vérifier**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_recherche_branches.py 2>&1 | tail -1`
Expected : `9 passed`.

Si `test_faute_de_frappe` échoue sur « automobile », mesurer `word_similarity` réel avant de toucher au seuil : le prototype du 2026-10-05 donnait 0,38 pour « facutre » et 0,09 pour « automobile ». Si `test_titre_classe_avant_contenu` échoue, vérifier les poids A/B de la colonne et ne pas changer l'ordre attendu.

- [ ] **Step 5 : commit**

```bash
git add briques/memoire/memory/backend/app/services/recherche_*.py briques/memoire/memory/backend/tests/test_recherche_branches.py
git commit -m "feat(memoire): exact, full-text, trigram and vector search branches sharing one WHERE"
```

---

### Task 6 : Orchestration, contrat HTTP et en-tête de mode

**Files :**
- Modify : `backend/app/services/search_service.py` (fichier entier)
- Modify : `backend/app/schemas/search.py` (`SearchResult`)
- Modify : `backend/app/routers/search.py` (route `""`)
- Test : `backend/tests/test_recherche.py`

**Interfaces :**
- Consumes : Tasks 2, 4 et 5.
- Produces :
  - `ResultatRecherche(mode: str, resultats: list[SearchResult])` (dataclass).
  - `SearchService.hybrid_search(space_id, query, type_filter=None, stage_filter=None, tier_filter=None, limit=20) -> ResultatRecherche`.
  - `SearchService.vector_search(...)`, inchangé sauf `correspondance="vectorielle"`.
  - `GET /api/v1/spaces/{id}/search?q=&type=&stage=&tier=&limit=` renvoie `list[SearchResult]` avec l'en-tête `X-Memoire-Mode`.
  - `SearchResult.correspondance: Optional[str] = None`.

- [ ] **Step 1 : écrire les tests qui doivent échouer**

`backend/tests/test_recherche.py` :

```python
import pytest

from tests.outils_embedder import activer_embedder_factice

pytestmark = pytest.mark.asyncio


async def _creer(client, headers, space_id, titre, contenu="", type_="input"):
    r = await client.post(f"/api/v1/spaces/{space_id}/nodes",
                          json={"type": type_, "title": titre, "content_md": contenu}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _chercher(client, headers, space_id, q, **params):
    r = await client.get(f"/api/v1/spaces/{space_id}/search", params={"q": q, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return r.headers["X-Memoire-Mode"], r.json()


class TestRecherche:
    async def test_reference_exacte_en_tete(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        contenu = await _creer(client, auth_headers, sid, "Compte rendu", "Sprint S237b terminé")
        titre = await _creer(client, auth_headers, sid, "S237b résultats")
        await _creer(client, auth_headers, sid, "Plan S237", "S237 seulement")
        mode, res = await _chercher(client, auth_headers, sid, "S237b")
        assert mode == "hybride"
        assert [r["id"] for r in res[:2]] == [titre, contenu]
        assert {r["correspondance"] for r in res[:2]} == {"exacte"}

    async def test_embedder_en_panne_reste_utilisable(self, client, auth_headers, test_space):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Réunion budget", "factures fournisseurs")
        mode, res = await _chercher(client, auth_headers, sid, "reunion")
        assert mode == "lexical"
        assert [r["id"] for r in res] == [nid]
        assert res[0]["correspondance"] == "lexicale"

    async def test_souvenir_sans_vecteur_trouve_en_hybride(self, client, auth_headers, test_space, monkeypatch):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Contrat Durand", "signé")  # embedder en panne
        activer_embedder_factice(monkeypatch)
        mode, res = await _chercher(client, auth_headers, sid, "durand")
        assert mode == "hybride"
        assert nid in [r["id"] for r in res]

    async def test_proximite_de_sens(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Achat voiture")
        _, res = await _chercher(client, auth_headers, sid, "automobile")
        assert [r["id"] for r in res] == [nid]
        assert res[0]["correspondance"] == "vectorielle"

    async def test_faute_de_frappe(self, client, auth_headers, test_space):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Fournisseurs", "Les factures du trimestre")
        _, res = await _chercher(client, auth_headers, sid, "facutre")
        assert [r["id"] for r in res] == [nid]

    async def test_filtre_type(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        projet = await _creer(client, auth_headers, sid, "Gamma", type_="projet")
        await _creer(client, auth_headers, sid, "Gamma", type_="input")
        _, res = await _chercher(client, auth_headers, sid, "gamma", type="projet")
        assert [r["id"] for r in res] == [projet]

    async def test_requete_vide(self, client, auth_headers, test_space):
        _, res = await _chercher(client, auth_headers, test_space["id"], "")
        assert res == []

    async def test_scores_decroissants(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        for t in ("Delta un", "Delta deux", "Delta trois S-9"):
            await _creer(client, auth_headers, sid, t)
        _, res = await _chercher(client, auth_headers, sid, "delta S-9")
        scores = [r["score"] for r in res]
        assert scores == sorted(scores, reverse=True) and len(set(scores)) == len(scores)


class TestIsolation:
    @pytest.mark.parametrize("embedder", ["panne", "factice"])
    async def test_aucune_fuite_entre_utilisateurs(self, client, auth_headers, autres_headers, monkeypatch, embedder):
        if embedder == "factice":
            activer_embedder_factice(monkeypatch)
        a = (await client.post("/api/v1/spaces", json={"name": "A"}, headers=auth_headers)).json()["id"]
        b = (await client.post("/api/v1/spaces", json={"name": "B"}, headers=autres_headers)).json()["id"]
        mien = await _creer(client, auth_headers, a, "Dossier Zéphyr Z-42", "confidentiel")
        await _creer(client, autres_headers, b, "Dossier Zéphyr Z-42", "confidentiel")
        for q in ("zephyr", "Z-42", "zepyhr", '"dossier zéphyr"'):
            _, res = await _chercher(client, auth_headers, a, q)
            assert [r["id"] for r in res] == [mien], q
        r = await client.get(f"/api/v1/spaces/{b}/search", params={"q": "zephyr"}, headers=auth_headers)
        assert r.status_code in (403, 404)
```

- [ ] **Step 2 : vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_recherche.py 2>&1 | tail -3`
Expected : FAIL (`KeyError: 'x-memoire-mode'`).

- [ ] **Step 3 : implémenter**

Dans `backend/app/schemas/search.py`, ajouter à `SearchResult` le champ suivant, après `score: float` :

```python
    # S238 : pourquoi ce souvenir est sorti — exacte | lexicale | vectorielle | les_deux.
    correspondance: Optional[str] = None
```

`backend/app/services/search_service.py` (fichier entier) :

```python
"""Recherche Mémoire (S238) : références exactes, branche lexicale, branche vectorielle.

L'embedder peut être en panne : la recherche reste alors lexicale (mode « lexical ») au lieu
de renvoyer du bruit ou rien. Les classements sont fusionnés par rangs (RRF), jamais en
additionnant des scores de natures différentes ; les références exactes passent devant.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node
from app.schemas.search import SearchResult
from app.services.recherche_conditions import Filtres
from app.services.recherche_fusion import extraire_references, ordonner
from app.services.recherche_lexicale import (
    classement_plein_texte, classement_trigramme, correspondances_exactes,
)
from app.services.recherche_vectorielle import classement_vectoriel

CANDIDATS_MIN = 50


@dataclass
class ResultatRecherche:
    mode: str  # hybride | lexical
    resultats: list[SearchResult]


def _valeur(v, defaut=None):
    return v.value if hasattr(v, "value") else (v if v is not None else defaut)


class SearchService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = Embedder()

    async def hybrid_search(
        self,
        space_id: UUID,
        query: str,
        type_filter: Optional[str] = None,
        stage_filter: Optional[str] = None,
        tier_filter: Optional[str] = None,
        limit: int = 20,
    ) -> ResultatRecherche:
        if not query or not query.strip():
            return ResultatRecherche("hybride", [])
        filtres = Filtres(space_id, type_filter, stage_filter, tier_filter)
        candidats = max(limit, CANDIDATS_MIN)

        exacts = await correspondances_exactes(self.db, extraire_references(query), filtres, candidats)
        lexical = await classement_plein_texte(self.db, query, filtres, candidats)
        if not lexical:
            lexical = await classement_trigramme(self.db, query, filtres, candidats)

        mode, vectoriel = "hybride", []
        try:
            vecteur = await self.embedder.embed_text(query)
        except EmbeddingIndisponible:
            mode = "lexical"
        else:
            if vecteur:
                vectoriel = await classement_vectoriel(self.db, vecteur, filtres, candidats)

        classes = ordonner(exacts, lexical, vectoriel, limit)
        return ResultatRecherche(mode, await self._hydrater(space_id, classes))

    async def _hydrater(self, space_id: UUID, classes) -> list[SearchResult]:
        if not classes:
            return []
        rows = await self.db.execute(
            select(Node.id, Node.title, Node.content_md, Node.type, Node.storage_tier, Node.happened_at)
            .where(Node.space_id == space_id, Node.id.in_([c.id for c in classes]))
        )
        par_id = {r[0]: r for r in rows.all()}
        return [
            SearchResult(
                id=c.id,
                title=par_id[c.id][1],
                content_md=(par_id[c.id][2] or "")[:300],
                type=_valeur(par_id[c.id][3]),
                storage_tier=_valeur(par_id[c.id][4], "hot"),
                happened_at=par_id[c.id][5],
                score=c.score,
                correspondance=c.correspondance,
            )
            for c in classes
            if c.id in par_id
        ]

    async def vector_search(
        self,
        space_id: UUID,
        query: str,
        limit: int = 10,
        stage_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> list[SearchResult]:
        """Recherche purement sémantique (/semantic). Lève EmbeddingIndisponible en panne."""
        query_embedding = await self.embedder.embed_text(query)
        if not query_embedding:
            return []

        embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        conditions = ["n.space_id = :space_id", "n.status IN ('active', 'archived')"]
        params = {"space_id": space_id, "limit": limit, "embedding": embedding_literal}
        if type_filter:
            conditions.append("n.type = :type_filter")
            params["type_filter"] = type_filter
        if stage_filter:
            conditions.append("n.ipcra_stage = :stage_filter")
            params["stage_filter"] = stage_filter

        sql = text(f"""
            SELECT n.id, n.title, n.content_md, n.type, n.storage_tier, n.happened_at,
                   1 - (n.embedding <=> CAST(:embedding AS vector)) AS score
            FROM nodes n
            WHERE {" AND ".join(conditions)}
              AND n.embedding IS NOT NULL
            ORDER BY n.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)
        rows = (await self.db.execute(sql, params)).all()
        return [
            SearchResult(
                id=row[0],
                title=row[1],
                content_md=(row[2] or "")[:300],
                type=_valeur(row[3]),
                storage_tier=_valeur(row[4], "hot"),
                happened_at=row[5],
                score=float(row[6]) if row[6] else 0.0,
                correspondance="vectorielle",
            )
            for row in rows
        ]
```

Dans `backend/app/routers/search.py`, ajouter `Response` à l'import `fastapi`, puis remplacer la route `""` par :

```python
@router.get("", response_model=list[SearchResult])
async def search(
    space_id: UUID,
    response: Response,
    q: str = Query(""),
    type: str = Query(None),
    stage: str = Query(None),
    tier: str = Query(None),
    limit: int = Query(20),
    db: AsyncSession = Depends(get_db),
):
    svc = SearchService(db)
    resultat = await svc.hybrid_search(space_id, q, type_filter=type, stage_filter=stage, tier_filter=tier, limit=limit)
    # « lexical » = embedder injoignable : résultats par les mots seulement (S238).
    response.headers["X-Memoire-Mode"] = resultat.mode
    return resultat.resultats
```

- [ ] **Step 4 : vérifier toute la suite**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q 2>&1 | tail -1`
Expected : `96 passed` (63 + 14 + 9 + 10).

- [ ] **Step 5 : commit**

```bash
git add briques/memoire/memory/backend/app briques/memoire/memory/backend/tests/test_recherche.py
git commit -m "feat(memoire): hybrid search with lexical fallback, RRF fusion and mode header"
```

---

### Task 7 : Adaptateur `/rappeler` (mode et correspondance) et manifeste

**Files :**
- Modify : `briques/memoire/main.py` (`rappeler`, lignes 475-503 ; `VERSION`)
- Modify : `briques/memoire/manifest.json` (description de `memoire_rappeler`, `version`)
- Test : `briques/memoire/test_memoire.py`

**Interfaces :**
- Consumes : en-tête `X-Memoire-Mode` et champ `correspondance` (Task 6).
- Produces : `GET /rappeler` → `{"requete", "mode", "total", "souvenirs": [{id, titre, extrait, type, score, correspondance}]}`. `mode` vaut `"hybride"` par défaut si l'en-tête est absent (backend plus ancien).

- [ ] **Step 1 : écrire les tests qui doivent échouer**

Ajouter à `briques/memoire/test_memoire.py`, après `test_rappeler_remonte_le_score` :

```python
@pytest.mark.asyncio
@respx.mock
async def test_rappeler_propage_mode_et_correspondance():
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/search").mock(
        return_value=httpx.Response(
            200,
            headers={"X-Memoire-Mode": "lexical"},
            json=[{"id": "a", "title": "S237b", "content_md": "", "type": "input",
                   "score": 2.5, "correspondance": "exacte"}],
        )
    )
    body = (await _appel("GET", "/rappeler", params={"q": "S237b"})).json()
    assert body["mode"] == "lexical"
    assert body["souvenirs"][0]["correspondance"] == "exacte"


@pytest.mark.asyncio
@respx.mock
async def test_rappeler_mode_par_defaut_sans_en_tete():
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/search").mock(return_value=httpx.Response(200, json=[]))
    body = (await _appel("GET", "/rappeler", params={"q": "x"})).json()
    assert body["mode"] == "hybride"
```

- [ ] **Step 2 : vérifier l'échec**

Run (racine du dépôt) : `scripts/tests_briques.sh memoire 2>&1 | tail -6`
Expected : 2 échecs (`KeyError: 'mode'`).

- [ ] **Step 3 : implémenter**

Dans `briques/memoire/main.py`, fonction `rappeler`, remplacer le bloc qui va de `        resultats = r.json()` jusqu'au `return` final par :

```python
        resultats = r.json()
        # S238 : « lexical » = embedder du backend injoignable, résultats par les mots seuls.
        mode = r.headers.get("X-Memoire-Mode", "hybride")
    souvenirs = [
        {
            "id": x.get("id"),
            "titre": x.get("title"),
            "extrait": (x.get("content_md") or "")[:280],
            "type": x.get("type"),
            "score": x.get("score", 0),
            "correspondance": x.get("correspondance"),
        }
        for x in resultats
    ]
    return {"requete": q, "mode": mode, "total": len(souvenirs), "souvenirs": souvenirs}
```

Toujours dans `main.py`, passer `VERSION = "0.3.0"` à `VERSION = "0.4.0"`.

Dans `briques/memoire/manifest.json`, passer `"version": "0.2.0"` à `"version": "0.3.0"` et remplacer la description de `memoire_rappeler` par :

```json
"description": "Cherche dans la mémoire de la solution (références exactes en tête — codes, numéros, e-mails, expressions entre guillemets —, puis mots et sens). 'espace' = 'solution' (usine, entreprises, projets), 'perso' (préférences/faits sur l'utilisateur), ou 'veille' (résumés de la famille de briques veille, isolé par personne). La réponse indique 'mode' : 'lexical' signifie que la recherche par le sens est momentanément indisponible (seuls les mots ont été cherchés). Lecture seule."
```

- [ ] **Step 4 : vérifier**

Run (racine) : `scripts/tests_briques.sh memoire 2>&1 | tail -4`
Expected : `61 passed`, « Aucune régression ».

Run (racine) : `grep -rn "manifest" core/test_*contrat* 2>/dev/null | head -3`. Si un test de contrat entre manifeste et route existe (S210), le lancer : `scripts/tests_briques.sh noyau` ou la commande indiquée dans son en-tête. Il doit rester vert.

- [ ] **Step 5 : commit**

```bash
git add briques/memoire/main.py briques/memoire/manifest.json briques/memoire/test_memoire.py
git commit -m "feat(memoire): /rappeler exposes search mode and match kind"
```

---

### Task 8 : Mesure avant/après

**Files :**
- Create : `backend/scripts/corpus_mesure.json`
- Create : `backend/scripts/mesure_recherche.py`
- Create : `docs/sprints/S238-memoire-repli-lexical-resultats.md` (section « Mesure »)

**Interfaces :**
- Consumes : `SearchService.hybrid_search` (Task 6), `appliquer_migrations` (Task 3), `vecteur_graine_42` (Task 3), `scripts/en_docker.sh` (Task 1).
- Produces : un rapport Markdown sur la sortie standard. Pour chaque algorithme (`ancien`, `nouveau`) et chaque état de l'embedder (`actif`, `coupé`) : rappel@5, MRR, latence p50/p95 en ms, ensemble puis par catégorie.

- [ ] **Step 1 : corpus**

`backend/scripts/corpus_mesure.json` (40 souvenirs synthétiques, 25 requêtes annotées ; aucune donnée réelle) :

```json
{
  "souvenirs": [
    {"cle": "s237b", "titre": "S237b résultats", "contenu": "Remplacement de MinIO par SeaweedFS, déploiement sur le HP validé."},
    {"cle": "s237", "titre": "S237 reconstruction Ansible", "contenu": "Reconstruction complète sur VM vierge, RTO observé 55 minutes."},
    {"cle": "cr_sprint", "titre": "Compte rendu de sprint", "contenu": "Le sprint S237b est terminé ; reste le rejeu sur la VM 106."},
    {"cle": "inv042", "titre": "Facture fournisseur", "contenu": "Facture INV-2026-042 de la société Durand, échéance au 30 novembre."},
    {"cle": "inv043", "titre": "Facture fournisseur", "contenu": "Facture INV-2026-043 du cabinet Lemoine, réglée par virement."},
    {"cle": "relance", "titre": "Relance impayé", "contenu": "Relancer le client Martin pour la facture en retard de paiement."},
    {"cle": "compose", "titre": "Configuration du déploiement", "contenu": "Le fichier docker-compose.yml de la brique mémoire épingle l'image pgvector."},
    {"cle": "caddy", "titre": "Piège Caddy", "contenu": "Après un git pull, redémarrer le conteneur mesh_caddy, un simple reload ne suffit pas."},
    {"cle": "email_marina", "titre": "Contact Marina", "contenu": "Adresse de contact : marina.garinat@exemple.fr pour le calendrier familial."},
    {"cle": "email_jean", "titre": "Contact comptable", "contenu": "Écrire à jean.dupont@exemple.fr pour la clôture des comptes."},
    {"cle": "dossier", "titre": "Dossier client 2024-117", "contenu": "Litige commercial, audience prévue au tribunal de commerce."},
    {"cle": "reunion", "titre": "Réunion budget", "contenu": "Arbitrages du budget annuel avec la direction financière."},
    {"cle": "reunion_eq", "titre": "Réunion d'équipe", "contenu": "Point hebdomadaire : priorités, congés et recrutement."},
    {"cle": "paie", "titre": "Bulletins de paie", "contenu": "Génération des bulletins de salaire du mois et déclaration sociale nominative."},
    {"cle": "urssaf", "titre": "Cotisations sociales", "contenu": "Échéancier des cotisations URSSAF du trimestre."},
    {"cle": "voiture", "titre": "Achat d'une voiture de service", "contenu": "Comparer location longue durée et achat pour le véhicule du cabinet."},
    {"cle": "assurance", "titre": "Assurance responsabilité civile", "contenu": "Renouvellement du contrat d'assurance professionnelle."},
    {"cle": "bail", "titre": "Bail commercial", "contenu": "Révision triennale du loyer des locaux, indice ILC."},
    {"cle": "rgpd", "titre": "Registre RGPD", "contenu": "Mise à jour du registre des traitements de données personnelles."},
    {"cle": "sauvegarde", "titre": "Sauvegarde USB", "contenu": "Duplicati chiffre les exports cohérents vers la clé USB toutes les 12 heures."},
    {"cle": "kuma", "titre": "Supervision", "contenu": "Uptime Kuma envoie une alerte Telegram quand une brique tombe."},
    {"cle": "grafana", "titre": "Tableau Grafana", "contenu": "Métriques Prometheus du processeur, de la mémoire et du disque de l'hôte."},
    {"cle": "keycloak", "titre": "Connexion Keycloak", "contenu": "Le royaume workplace authentifie les membres du cercle privé."},
    {"cle": "netbird", "titre": "Réseau maillé NetBird", "contenu": "Le Mac et la VM sont enrôlés ; reste le téléphone."},
    {"cle": "recette", "titre": "Recette de la tarte aux pommes", "contenu": "Pâte brisée, pommes, sucre et cannelle, 40 minutes au four."},
    {"cle": "voyage", "titre": "Voyage à Lisbonne", "contenu": "Vol réservé, hôtel près de l'Alfama, visite de Belém."},
    {"cle": "medecin", "titre": "Rendez-vous médical", "contenu": "Consultation chez le généraliste mardi à 9 heures."},
    {"cle": "anniv", "titre": "Anniversaire de Léa", "contenu": "Organiser la fête samedi, commander le gâteau."},
    {"cle": "jardin", "titre": "Potager", "contenu": "Semer les tomates en avril, arroser le soir."},
    {"cle": "lecture", "titre": "Livres à lire", "contenu": "Les Misérables, L'Étranger et un essai sur l'économie."},
    {"cle": "studio", "titre": "Studio audio-séries", "contenu": "Écriture du tome deux de la saga familiale, chapitre sur l'exil."},
    {"cle": "personnage", "titre": "Personnage Aria", "contenu": "Voix calme et grave, rôle de narratrice."},
    {"cle": "world", "titre": "World Engine", "contenu": "Le génome cosmique transmet les traits aux lignées descendantes."},
    {"cle": "forge", "titre": "Gate de la Forge", "contenu": "Toute action risquée exige une validation humaine explicite."},
    {"cle": "veille", "titre": "Veille cosmétique", "contenu": "Cinq sources actives surveillent les nouveautés du secteur."},
    {"cle": "prospect", "titre": "Prospection géographique", "contenu": "Liste d'entreprises de plomberie autour de Lyon pour démarchage."},
    {"cle": "stripe", "titre": "Paiements Stripe Connect", "contenu": "Chaque restaurant reçoit ses paiements sur son propre compte connecté."},
    {"cle": "restaurant", "titre": "Commande par QR code", "contenu": "Le client scanne le QR de la table et paie depuis son téléphone."},
    {"cle": "transcription", "titre": "Transcription locale", "contenu": "Whisper transcrit les messages vocaux sans envoyer l'audio à l'extérieur."},
    {"cle": "telephonie", "titre": "Standard téléphonique", "contenu": "Les appels entrants sont routés vers la messagerie après 19 heures."}
  ],
  "requetes": [
    {"q": "S237b", "categorie": "reference", "attendus": ["s237b", "cr_sprint"]},
    {"q": "INV-2026-042", "categorie": "reference", "attendus": ["inv042"]},
    {"q": "docker-compose.yml", "categorie": "reference", "attendus": ["compose"]},
    {"q": "jean.dupont@exemple.fr", "categorie": "reference", "attendus": ["email_jean"]},
    {"q": "dossier 2024-117", "categorie": "reference", "attendus": ["dossier"]},
    {"q": "\"mesh_caddy\"", "categorie": "reference", "attendus": ["caddy"]},
    {"q": "Durand", "categorie": "nom", "attendus": ["inv042"]},
    {"q": "Marina", "categorie": "nom", "attendus": ["email_marina"]},
    {"q": "Keycloak", "categorie": "nom", "attendus": ["keycloak"]},
    {"q": "Lisbonne", "categorie": "nom", "attendus": ["voyage"]},
    {"q": "Aria", "categorie": "nom", "attendus": ["personnage"]},
    {"q": "URSSAF", "categorie": "metier", "attendus": ["urssaf"]},
    {"q": "bulletins de paie", "categorie": "metier", "attendus": ["paie"]},
    {"q": "factures fournisseurs", "categorie": "metier", "attendus": ["inv042", "inv043"]},
    {"q": "registre des traitements", "categorie": "metier", "attendus": ["rgpd"]},
    {"q": "révision du loyer", "categorie": "metier", "attendus": ["bail"]},
    {"q": "reunion budget", "categorie": "metier", "attendus": ["reunion"]},
    {"q": "client qui ne paie pas", "categorie": "paraphrase", "attendus": ["relance"]},
    {"q": "automobile pour l'entreprise", "categorie": "paraphrase", "attendus": ["voiture"]},
    {"q": "être prévenu quand un service est en panne", "categorie": "paraphrase", "attendus": ["kuma"]},
    {"q": "dessert aux fruits", "categorie": "paraphrase", "attendus": ["recette"]},
    {"q": "facutre durand", "categorie": "faute", "attendus": ["inv042"]},
    {"q": "supervison", "categorie": "faute", "attendus": ["kuma"]},
    {"q": "assurence", "categorie": "faute", "attendus": ["assurance"]},
    {"q": "Lisbone", "categorie": "faute", "attendus": ["voyage"]}
  ]
}
```

- [ ] **Step 2 : script de mesure**

`backend/scripts/mesure_recherche.py` :

```python
"""Mesure S238 : ancien algorithme vs nouveau, embedder actif puis coupé.

Charge un corpus synthétique (corpus_mesure.json) dans un espace neuf de la base
TEST_DATABASE_URL, puis rejoue les requêtes annotées. Métriques : rappel@5 (part des
attendus présents dans les 5 premiers), MRR (1/rang du premier attendu), latence p50/p95.

« Ancien » = la requête SQL d'avant S238, recopiée ici telle quelle, avec le comportement
d'avant de l'embedder : en panne, il renvoyait le vecteur constant graine 42.
« Embedder actif » exige un vrai modèle (LLM_BASE_URL, LLM_API_KEY, EMBEDDING_MODEL) :
le script refuse de tourner sans, plutôt que de mesurer un faux embedder.

Usage (depuis backend/) : scripts/en_docker.sh python scripts/mesure_recherche.py
"""
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.config  # noqa: E402

app.config.settings.database_url = os.environ["TEST_DATABASE_URL"]

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.llm.embedder import Embedder  # noqa: E402
from app.migrations_demarrage import appliquer_migrations, vecteur_graine_42  # noqa: E402
from app.models.node import IpCraStage, Node, NodeType  # noqa: E402
from app.models.user import Space, User  # noqa: E402
from app.services.search_service import SearchService  # noqa: E402

CORPUS = json.loads((Path(__file__).parent / "corpus_mesure.json").read_text())
REPETITIONS = 5


async def ancien(db: AsyncSession, space_id, q: str, vecteur: list[float], limit: int = 20) -> list[uuid.UUID]:
    """Requête d'avant S238 (search_service.hybrid_search au commit f232d8d)."""
    params = {"space_id": space_id, "limit": limit, "embedding": "[" + ",".join(map(str, vecteur)) + "]"}
    mots = q.strip().split()
    conditions = " OR ".join(f"(n.title ILIKE :w{i} OR n.content_md ILIKE :w{i})" for i in range(len(mots)))
    for i, w in enumerate(mots):
        params[f"w{i}"] = f"%{w}%"
    bonus = f"+ CASE WHEN {conditions} THEN 0.3 ELSE 0 END" if mots else ""
    sql = text(f"""
        SELECT n.id, (1 - (n.embedding <=> CAST(:embedding AS vector))) {bonus} AS score
        FROM nodes n
        WHERE n.space_id = :space_id AND n.status IN ('active', 'archived') AND n.embedding IS NOT NULL
        ORDER BY score DESC LIMIT :limit
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


def metriques(classement: list, attendus: set) -> tuple[float, float]:
    top5 = classement[:5]
    rappel = len(attendus & set(top5)) / len(attendus)
    rr = next((1 / (i + 1) for i, x in enumerate(classement) if x in attendus), 0.0)
    return rappel, rr


async def preparer(fabrique) -> tuple[uuid.UUID, dict]:
    async with fabrique() as db:
        user = User(email=f"mesure_{uuid.uuid4().hex[:8]}@exemple.fr", display_name="Mesure", password_hash="x")
        db.add(user)
        await db.flush()
        space = Space(name="Mesure S238", owner_id=user.id)
        db.add(space)
        await db.flush()
        emb = Embedder()
        cles = {}
        for s in CORPUS["souvenirs"]:
            n = Node(space_id=space.id, type=NodeType.input, ipcra_stage=IpCraStage.input,
                     title=s["titre"], content_md=s["contenu"],
                     embedding=await emb.embed_text(f"{s['titre']}\n{s['contenu']}"))
            db.add(n)
            await db.flush()
            cles[n.id] = s["cle"]
        await db.commit()
        return space.id, cles


async def mesurer(fabrique, space_id, cles, algo: str, embedder_actif: bool) -> dict:
    par_categorie: dict[str, list[tuple[float, float]]] = {}
    latences = []
    for r in CORPUS["requetes"]:
        attendus = set(r["attendus"])
        for _ in range(REPETITIONS):
            async with fabrique() as db:
                debut = time.perf_counter()
                if algo == "ancien":
                    vecteur = await Embedder().embed_text(r["q"]) if embedder_actif else vecteur_graine_42()
                    ids = await ancien(db, space_id, r["q"], vecteur)
                else:
                    ids = [x.id for x in (await SearchService(db).hybrid_search(space_id, r["q"])).resultats]
                latences.append((time.perf_counter() - debut) * 1000)
        par_categorie.setdefault(r["categorie"], []).append(metriques([cles[i] for i in ids], attendus))
    tout = [m for ms in par_categorie.values() for m in ms]
    return {
        "rappel5": statistics.mean(m[0] for m in tout),
        "mrr": statistics.mean(m[1] for m in tout),
        "p50": statistics.median(latences),
        "p95": statistics.quantiles(latences, n=20)[18],
        "categories": {c: (statistics.mean(m[0] for m in ms), statistics.mean(m[1] for m in ms))
                       for c, ms in par_categorie.items()},
    }


async def principal() -> None:
    if not os.environ.get("LLM_BASE_URL"):
        sys.exit("LLM_BASE_URL absent : la mesure « embedder actif » exige un vrai modèle d'embedding.")
    moteur = create_async_engine(os.environ["TEST_DATABASE_URL"])
    fabrique = async_sessionmaker(moteur, class_=AsyncSession, expire_on_commit=False)
    async with moteur.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await appliquer_migrations(conn)
    space_id, cles = await preparer(fabrique)

    resultats = {}
    for actif in (True, False):
        if not actif:
            async def _panne(self, text):
                raise ConnectionError("embedder coupé pour la mesure")
            LLMClient.embed = _panne
        for algo in ("ancien", "nouveau"):
            resultats[(algo, actif)] = await mesurer(fabrique, space_id, cles, algo, actif)

    categories = sorted({r["categorie"] for r in CORPUS["requetes"]})
    print(f"Corpus : {len(CORPUS['souvenirs'])} souvenirs, {len(CORPUS['requetes'])} requêtes, "
          f"{REPETITIONS} répétitions. Modèle : {app.config.settings.embedding_model}.\n")
    print("| Algorithme | Embedder | Rappel@5 | MRR | p50 (ms) | p95 (ms) | " + " | ".join(categories) + " |")
    print("|---|---|---|---|---|---|" + "---|" * len(categories))
    for (algo, actif), m in resultats.items():
        cats = " | ".join(f"{m['categories'][c][0]:.2f} / {m['categories'][c][1]:.2f}" for c in categories)
        print(f"| {algo} | {'actif' if actif else 'coupé'} | {m['rappel5']:.2f} | {m['mrr']:.2f} | "
              f"{m['p50']:.1f} | {m['p95']:.1f} | {cats} |")
    print("\nCellules par catégorie : rappel@5 / MRR.")
    await moteur.dispose()


if __name__ == "__main__":
    asyncio.run(principal())
```

Avant de lancer le script, vérifier les champs obligatoires de `Space` et `User` dans `backend/app/models/user.py` (`owner_id` ou équivalent, `password_hash`) et ajuster `preparer` en conséquence. Ne pas créer de `SpaceUser` : la mesure appelle le service directement, sans HTTP.

- [ ] **Step 3 : lancer la mesure sur le HP (vrai embedder)**

Le modèle `embedding/all-minilm` est servi par le Gateway du HP. Pousser la branche, puis, sur le HP :

```bash
git push -u origin sprint/s238-memoire-repli-lexical
ssh debian@192.168.1.89 'cd ~/workplace && git fetch -q && git checkout -q sprint/s238-memoire-repli-lexical && git pull -q \
  && cd briques/memoire/memory/backend \
  && LLM_PROVIDER=openai LLM_BASE_URL=http://host.docker.internal:4001/v1 EMBEDDING_MODEL=embedding/all-minilm \
     LLM_API_KEY="$(grep -E "^LLM_API_KEY=" ~/workplace/.env | cut -d= -f2-)" \
     scripts/en_docker.sh python scripts/mesure_recherche.py'
```

Expected : un tableau de 4 lignes (`ancien`/`nouveau` × `actif`/`coupé`). Critères d'acceptation :
- en mode coupé, le nouvel algorithme a un rappel@5 ≥ 0,7 sur les catégories `reference`, `nom` et `metier` ;
- en mode coupé, l'ancien algorithme a un MRR proche du hasard ;
- `reference` atteint un MRR de 1,00 avec le nouvel algorithme dans les deux modes ;
- en mode actif, le rappel global du nouvel algorithme est ≥ à celui de l'ancien.

Si un critère n'est pas atteint, consigner l'écart tel quel dans le rapport. Ne pas retoucher le corpus pour faire passer la mesure.

Si `LLM_API_KEY` n'est pas dans `~/workplace/.env` sous ce nom, lire le `docker-compose.yml` de la brique mémoire pour savoir d'où vient la clé, et la passer de la même façon. Ne jamais l'afficher.

Remettre ensuite le HP sur `main` : `ssh debian@192.168.1.89 'cd ~/workplace && git checkout -q main'`.

- [ ] **Step 4 : rapport**

Créer `docs/sprints/S238-memoire-repli-lexical-resultats.md` :

```markdown
# S238 — Résultats : recherche Mémoire avec repli lexical

Date : <date de la mesure>. Branche : `sprint/s238-memoire-repli-lexical`.
Conception : [spec](../superpowers/specs/2026-10-05-S238-memoire-repli-lexical-design.md) ; plan : [plan](../superpowers/plans/2026-10-05-S238-memoire-repli-lexical.md).

## Mesure avant/après (corpus synthétique)

<tableau copié tel quel depuis la sortie du script>

Lecture : <3 à 5 phrases factuelles — gains par catégorie, régressions éventuelles, latence>.

## Tests

<nombre exact de tests backend et adaptateur verts, commande utilisée>
```

Remplacer chaque `<…>` par la valeur réelle avant de committer.

- [ ] **Step 5 : commit**

```bash
git add briques/memoire/memory/backend/scripts docs/sprints/S238-memoire-repli-lexical-resultats.md
git commit -m "test(memoire): before/after search measurement on a synthetic corpus"
```

---

### Task 9 : Revue finale, déploiement HP, preuve LIVE et clôture

Cette tâche n'écrit pas de code applicatif. Elle est menée par l'agent principal, pas par un sous-agent.

- [ ] **Step 1 : revue finale de toute la branche** (skill `requesting-code-review` sur `main...sprint/s238-memoire-repli-lexical`). Points d'attention à transmettre :
  - isolation entre espaces dans chaque branche SQL ;
  - injection SQL (seuls des noms de paramètres sont interpolés dans les requêtes) ;
  - idempotence des migrations sur une base existante ;
  - comportement de `CREATE OR REPLACE FUNCTION` quand une colonne générée en dépend ;
  - revectorisation (pas de boucle infinie sur un texte vide) ;
  - compatibilité du contrat `/rappeler` avec Forge et le Cœur.

  Corriger, puis relancer les deux suites.

- [ ] **Step 2 : sauvegarde de la base avant déploiement.** Sur le HP :

```bash
ssh debian@192.168.1.89 'docker exec memoire-memoire-db-1 pg_dump -U memory -d memory -Fc > ~/s238-memoire-avant.dump && ls -la ~/s238-memoire-avant.dump'
```

- [ ] **Step 3 : déployer** (skill `hpworkplace`). Sur le HP, à partir de la branche fusionnée ou de la branche de sprint selon la décision de l'utilisateur, reconstruire `memoire-backend` et `memoire` avec `--build`. Le backend lit `init-pgvector.sql` seulement à l'initialisation d'un volume neuf : sur le volume existant, ce sont les migrations de démarrage qui posent les extensions. Vérifier :

```bash
ssh debian@192.168.1.89 'docker exec memoire-memoire-db-1 psql -U memory -d memory -Atc "
  select string_agg(extname, \",\") from pg_extension;
  select count(*) from information_schema.columns where table_name=\x27nodes\x27 and column_name=\x27recherche_tsv\x27;
  select count(*), count(embedding) from nodes;"'
```

Attendu :
- les extensions `vector`, `unaccent` et `pg_trgm` sont présentes, et la colonne existe ;
- `count(embedding)` vaut 66 − 11 = 55 juste après le démarrage, si aucune revectorisation n'a encore tourné.

- [ ] **Step 4 : preuve en mode lexical.** Couper l'accès au Gateway pour le backend mémoire seulement : recréer temporairement le conteneur avec `LLM_BASE_URL=http://127.0.0.1:9/v1`, sans toucher au `.env`. Appeler ensuite, avec la clé `MEMOIRE_KEY` lue sur le HP mais jamais affichée, `/rappeler?q=<un terme présent dans un souvenir>`. Attendu : `mode: "lexical"` et au moins un résultat. Restaurer ensuite la configuration normale (`docker compose up -d memoire-backend`).

- [ ] **Step 5 : preuve de revectorisation.** Attendre au plus 15 minutes après le retour du Gateway (la tâche tourne toutes les 10 minutes), puis vérifier :
  - `select count(*) from nodes where embedding is null and length(trim(title)) > 0` vaut 0 ;
  - le compte des vecteurs graine 42 vaut 0, en relançant la requête de doublons de la conception ;
  - `/rappeler?q=<terme>` renvoie `mode: "hybride"`.

- [ ] **Step 6 : latence réelle.** Lancer 20 appels `/rappeler` sur des termes variés et noter p50/p95. Ajouter au rapport une section « Preuve LIVE HP » avec uniquement des chiffres agrégés (comptes, modes observés, latences), aucun contenu de souvenir.

- [ ] **Step 7 : documentation et clôture.**
  - Dans `docs/sprints/S235-S239-infrastructure-supervision-recherche.md`, ajouter sous `## S238` une ligne « Statut : … » avec un lien vers le rapport, et mettre à jour la ligne de statut en tête du fichier.
  - Mettre à jour la mémoire `memory-projet-et-brique.md` : le repli « seed-42 » n'existe plus.
  - Créer la mémoire du sprint et sa ligne dans `MEMORY.md`.
  - Committer, puis proposer la fusion dans `main` (skill `finishing-a-development-branch`).
```
