# S241 — Recherche unifiée Forge + Ingestion + Mémoire : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une seule recherche (outil `chercher_documents` de l'assistant + onglet « 🔎 Recherche » du tableau de bord) qui interroge la Forge (documents + base de connaissances, hybride), la brique Ingestion (plein texte) et la Mémoire (S238), fusionne par rang, tolère les fautes de frappe, met les références exactes en tête, n'expose jamais les documents d'un autre utilisateur de la Forge et signale toute source en panne.

**Architecture :** fédération sans nouveau moteur. Chaque brique cherche dans sa propre base, qui fait foi, avec l'identité de l'appelant ; le Cœur fusionne les classements (RRF k=60, exacts en tête). Forge : PostgreSQL (plein texte + trigrammes + références exactes) + Qdrant **filtré par `user_id`**, résultats Qdrant recoupés avec PostgreSQL, réconciliation périodique PostgreSQL → Qdrant. Ingestion : SQLite FTS5 tenu à jour dans la même transaction que chaque écriture.

**Tech Stack :** Python 3.12 (Forge, Cœur) / 3.11 (Ingestion), FastAPI 0.115, SQLAlchemy 2 async + asyncpg, PostgreSQL 16.14 (`unaccent`, `pg_trgm`), qdrant-client 1.12.1 / Qdrant v1.12.4, SQLite FTS5 (`unicode61`, `trigram`), httpx 0.28, pytest + pytest-asyncio, Docker.

Spec : `docs/superpowers/specs/2026-10-06-S241-recherche-unifiee-design.md`. Branche : `sprint/s241-recherche-unifiee` (déjà créée, spec committée).

## Global Constraints

- Tout le code, les commentaires, les messages et les noms sont **en français**, comme le reste du dépôt.
- RRF : `K_RRF = 60`. Exacts toujours devant. Jamais d'addition de scores de natures différentes.
- Seuil trigramme PostgreSQL : `0.3` (`word_similarity`). Seuil trigramme Ingestion : `0.4` (part des trigrammes d'un mot retrouvés).
- Plafond du texte indexé : `200_000` caractères (Forge et Ingestion).
- Extraits : `280` caractères maximum.
- Limite de résultats : défaut `10`, bornée à `[1, 50]` partout.
- Délai par source côté Cœur : `8.0` s.
- Réconciliation Forge : toutes les `600` s, lots de `50`, arrêt au premier échec de l'embedder ; désactivable par `FORGE_RECONCILIATION=0`.
- **Aucune commande ne doit afficher un `.env`** (ni `docker compose config`, ni `cat .env`, ni `env`). Incident S240.
- Tests Forge **d'intégration** : uniquement via `briques/forge/forge/core/scripts/en_docker.sh` (Postgres 16.14 + Qdrant v1.12.4 neufs). Ils sont marqués `integration` et **sautés** hors de ce lanceur, pour que le filet `scripts/tests_briques.sh` reste vert.
- Ne jamais faire confiance à un comptage de tests rapporté : relancer soi-même (mémoire « comptages de tests des sous-agents peu fiables »).
- Commits : un par tâche minimum, message en français au format `type(S241): …`, terminé par :
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015j5THpT5yUyTQvEJwZtGmo
  ```

## Carte des fichiers

| Fichier | Rôle |
|---|---|
| `briques/forge/forge/core/scripts/en_docker.sh` (créé) | Lanceur de tests/scripts contre Postgres + Qdrant neufs |
| `briques/forge/forge/core/app/recherche_schema.py` (créé) | Tables cherchables, expressions normalisées, migrations S241 (source unique des expressions indexées) |
| `briques/forge/forge/core/scripts/init_db.py` (modifié) | `appliquer_schema(conn)` = `create_all` + S227 + S241 |
| `briques/forge/forge/core/app/recherche_fusion.py` (créé) | Fonctions pures : références, RRF, ordre (copie adaptée de S238) |
| `briques/forge/forge/core/app/memory.py` (modifié) | Filtre `user_id` obligatoire, `chercher_fragments`, `indexer_source`, `collection_active` |
| `briques/forge/forge/core/app/routers/{rag,chat,ws}.py`, `app/react_executor.py` (modifiés) | Passent l'utilisateur à `get_context` |
| `briques/forge/forge/core/app/recherche_documents.py` (créé) | Branches SQL (exacte, plein texte, trigrammes), recoupement, fiches |
| `briques/forge/forge/core/app/recherche_service.py` (créé) | Orchestration hybride Forge, mode réduit |
| `briques/forge/forge/core/app/routers/recherche.py` (créé) | `GET /api/recherche/hybride` |
| `briques/forge/forge/core/app/reconciliation.py` (créé) | Réconciliation PostgreSQL → Qdrant + boucle |
| `briques/forge/forge/core/app/recherche_reindexer.py` (créé) | Commande d'exploitation de reconstruction |
| `briques/forge/forge/core/tests/s241_outils.py` (créé) | Fixtures d'intégration (base, Qdrant, embedder factice) |
| `briques/forge/main.py` (modifié) | `GET /documents/chercher` (adaptateur) |
| `briques/ingestion/recherche.py` (créé) | FTS5 : normalisation, indexation, recherche |
| `briques/ingestion/stockage.py`, `main.py` (modifiés) | Index tenu à jour à chaque écriture, `GET /recherche` |
| `core/recherche_unifiee.py` (créé) | Fan-out, délais, fusion, sources indisponibles |
| `core/routers/recherche.py` (créé), `core/main.py` (modifié) | `GET /recherche` (session obligatoire) |
| `core/outils.py`, `core/outils_domaines/documents.py`, `core/assistant.py` (modifiés) | `chercher_documents` avec `q` → recherche unifiée |
| `core/dashboard.html` (modifié) | Onglet « 🔎 Recherche » |
| `core/test_cerveau_admin.py` (modifié) | `("GET", "/recherche")` ajouté à `ROUTES_SESSION` |
| `briques/forge/forge/core/scripts/mesure_recherche_s241.py` + `.json` (créés) | Mesure du rappel@5 |
| `docs/sprints/S241-recherche-unifiee-resultats.md` (créé) | Résultats, mesure, preuve LIVE |

---

### Task 1 : Forge — lanceur Docker et schéma de recherche

**Files:**
- Create: `briques/forge/forge/core/scripts/en_docker.sh`
- Create: `briques/forge/forge/core/app/recherche_schema.py`
- Modify: `briques/forge/forge/core/scripts/init_db.py`
- Create: `briques/forge/forge/core/tests/s241_outils.py`
- Test: `briques/forge/forge/core/tests/test_s241_schema.py`

**Interfaces:**
- Produces:
  - `app.recherche_schema.PLAFOND_TEXTE_INDEXE: int = 200_000`
  - `app.recherche_schema.TableRecherche(source: str, table: str, titre: str, corps: tuple[str, ...])` (dataclass figée) ; `TABLES: dict[str, TableRecherche]` avec les clés `"document"` et `"kb"`
  - `app.recherche_schema.texte_normalise(t: TableRecherche, alias: str = "") -> str` et `titre_normalise(t, alias="") -> str` (fragments SQL)
  - `app.recherche_schema.MIGRATIONS_S241: tuple[str, ...]`
  - `scripts.init_db.appliquer_schema(conn: AsyncConnection) -> None`
  - `tests.s241_outils` : marqueur `integration`, fixtures `base`, `embedder_factice`, `embedder_coupe`, fonctions `vecteur_factice(texte) -> list[float]`, `ajouter_document(user_id, nom, contenu) -> UUID`, `ajouter_article(user_id, titre, contenu, tags=None) -> UUID`

- [ ] **Step 1 : Écrire le lanceur**

Créer `briques/forge/forge/core/scripts/en_docker.sh` :

```bash
#!/usr/bin/env bash
# S241 — exécute une commande de forge/core contre un Postgres 16.14 et un Qdrant v1.12.4 NEUFS.
#
# Les tests d'intégration de la recherche exigent une vraie base (plein texte, trigrammes,
# colonnes générées) et un vrai Qdrant (filtres de payload) : un mock aurait caché exactement
# la fuite que S241 corrige. Mêmes images que la production (briques/forge/docker-compose.yml),
# Python du Dockerfile (3.12). Tout est détruit à la sortie.
#
# Usage (depuis briques/forge/forge/core) :
#   scripts/en_docker.sh python -m pytest -p no:cacheprovider -q [args pytest…]
#   scripts/en_docker.sh python -m scripts.mesure_recherche_s241
# Transmises au conteneur si définies : GATEWAY_BASE_URL GATEWAY_API_KEY LOCAL_EMBED_MODEL.
set -euo pipefail

[ $# -gt 0 ] || { echo "usage : $0 <commande…>" >&2; exit 2; }

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RACINE="$(cd "$ICI/../../../.." && pwd)"
SUFFIXE="$$"
RESEAU="forge-essai-$SUFFIXE"
BASE="forge-essai-db-$SUFFIXE"
QDRANT="forge-essai-qdrant-$SUFFIXE"

nettoyer() {
  docker rm -f "$BASE" "$QDRANT" >/dev/null 2>&1 || true
  docker network rm "$RESEAU" >/dev/null 2>&1 || true
}
trap nettoyer EXIT

docker network create "$RESEAU" >/dev/null
docker run -d --name "$BASE" --network "$RESEAU" \
  -e POSTGRES_USER=forge -e POSTGRES_PASSWORD=forge -e POSTGRES_DB=forge_test \
  postgres:16.14 >/dev/null
docker run -d --name "$QDRANT" --network "$RESEAU" qdrant/qdrant:v1.12.4 >/dev/null

pret=0
for _ in $(seq 1 60); do
  # Par TCP : pendant l'initialisation, l'image démarre un serveur provisoire sur la socket Unix.
  if docker exec "$BASE" pg_isready -h 127.0.0.1 -U forge -d forge_test >/dev/null 2>&1; then pret=1; break; fi
  sleep 1
done
[ "$pret" = 1 ] || { echo "✗ Postgres de test jamais prêt" >&2; exit 1; }

transmises=()
for v in GATEWAY_BASE_URL GATEWAY_API_KEY LOCAL_EMBED_MODEL; do
  if [ -n "${!v:-}" ]; then transmises+=(-e "$v=${!v}"); fi
done

docker run --rm --network "$RESEAU" -v "$RACINE":/monorepo:ro \
  -w /monorepo/briques/forge/forge/core \
  --add-host host.docker.internal:host-gateway \
  -e DATABASE_URL="postgresql+asyncpg://forge:forge@$BASE:5432/forge_test" \
  -e QDRANT_URL="http://$QDRANT:6333" \
  -e FORGE_TEST_INTEGRATION=1 -e FORGE_RECONCILIATION=0 \
  -e PYTHONPATH="/monorepo:/monorepo/briques/forge/shared" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e VAULT_SECRET=test-secret-0123456789 -e GATEWAY_KEY=test \
  ${transmises[@]+"${transmises[@]}"} \
  python:3.12-slim sh -c '
    pip install -q --no-cache-dir --root-user-action=ignore -r requirements.txt -r requirements-dev.txt >/dev/null &&
    python -c "
import os, time, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen(os.environ[\"QDRANT_URL\"] + \"/readyz\", timeout=2)
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit(\"✗ Qdrant de test jamais prêt\")
" &&
    exec "$@"' _ "$@"
```

Puis : `chmod +x briques/forge/forge/core/scripts/en_docker.sh`.

- [ ] **Step 2 : Écrire le module de schéma**

Créer `briques/forge/forge/core/app/recherche_schema.py` :

```python
"""Schéma de la recherche documentaire Forge (S241) : tables cherchables et migrations.

Source UNIQUE des expressions SQL indexées : l'index trigramme doit porter exactement la
même expression que les requêtes, sinon le planificateur ne le reconnaît pas. Les branches
SQL (`app/recherche_documents.py`) et les migrations (`scripts/init_db.py`) importent d'ici.

Pas d'Alembic dans ce projet : chaque instruction est idempotente et rejouée à chaque
démarrage par le service `forge-migrate` (`python -m scripts.init_db`).
"""
from __future__ import annotations

from dataclasses import dataclass

# to_tsvector refuse au-delà de 1 Mo de lexèmes : au-delà du plafond, le texte reste stocké
# mais n'est plus trouvable par la recherche lexicale (même plafond que la Mémoire, S238).
PLAFOND_TEXTE_INDEXE = 200_000


@dataclass(frozen=True)
class TableRecherche:
    source: str               # identifiant exposé : "document" | "kb"
    table: str                # table PostgreSQL
    titre: str                # colonne du titre
    corps: tuple[str, ...]    # colonnes du corps, dans l'ordre d'indexation


TABLES: dict[str, TableRecherche] = {
    "document": TableRecherche("document", "documents", "nom", ("contenu",)),
    "kb": TableRecherche("kb", "kb_articles", "titre", ("tags", "contenu")),
}


def _concat(t: TableRecherche, alias: str) -> str:
    colonnes = (t.titre, *t.corps)
    return " || ' ' || ".join(f"coalesce({alias}{c}, '')" for c in colonnes)


def texte_normalise(t: TableRecherche, alias: str = "") -> str:
    """Titre + corps, minuscules, sans accents, plafonné."""
    return f"forge_unaccent(lower(left({_concat(t, alias)}, {PLAFOND_TEXTE_INDEXE})))"


def titre_normalise(t: TableRecherche, alias: str = "") -> str:
    return f"forge_unaccent(lower(left(coalesce({alias}{t.titre}, ''), {PLAFOND_TEXTE_INDEXE})))"


def _tsv(t: TableRecherche) -> str:
    # Titre en `simple` (noms propres et codes intacts, poids A) + titre et corps en `french`
    # (pluriels, conjugaisons, poids B), le tout sans accents.
    return (
        f"setweight(to_tsvector('simple', forge_unaccent(left(coalesce({t.titre}, ''), "
        f"{PLAFOND_TEXTE_INDEXE}))), 'A') || "
        f"setweight(to_tsvector('french', forge_unaccent(left({_concat(t, '')}, "
        f"{PLAFOND_TEXTE_INDEXE}))), 'B')"
    )


def _migrations_table(t: TableRecherche) -> tuple[str, ...]:
    return (
        f"ALTER TABLE {t.table} ADD COLUMN IF NOT EXISTS recherche_tsv tsvector "
        f"GENERATED ALWAYS AS ({_tsv(t)}) STORED",
        f"CREATE INDEX IF NOT EXISTS idx_{t.table}_recherche_tsv ON {t.table} USING gin (recherche_tsv)",
        f"CREATE INDEX IF NOT EXISTS idx_{t.table}_texte_trgm ON {t.table} "
        f"USING gin (({texte_normalise(t)}) gin_trgm_ops)",
    )


MIGRATIONS_S241: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # unaccent() n'est que STABLE : une colonne générée et un index exigent IMMUTABLE. Le
    # dictionnaire étant nommé explicitement, l'enveloppe peut l'être sans mentir.
    """CREATE OR REPLACE FUNCTION forge_unaccent(text) RETURNS text
       LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
       AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$""",
    *_migrations_table(TABLES["document"]),
    *_migrations_table(TABLES["kb"]),
)
```

- [ ] **Step 3 : Exposer `appliquer_schema` dans `init_db.py`**

Dans `briques/forge/forge/core/scripts/init_db.py`, ajouter l'import après `from app.models import Base` :

```python
from app.recherche_schema import MIGRATIONS_S241
```

et remplacer la fonction `main()` par :

```python
async def appliquer_schema(conn) -> None:
    """Schéma complet et idempotent : tables absentes, colonnes S227, recherche S241.

    Appelée par `main()` (service `forge-migrate`) ET par les tests d'intégration : le
    schéma testé est celui de la production."""
    await conn.run_sync(Base.metadata.create_all)  # checkfirst=True par défaut
    for statement in (*MIGRATIONS_S227, *MIGRATIONS_S241):
        await conn.execute(text(statement))


async def main() -> None:
    log.info("→ init_db : création du schéma Forge (%d tables) si absent…", len(Base.metadata.tables))
    async with engine.begin() as conn:
        await appliquer_schema(conn)
    await engine.dispose()
    log.info("✓ init_db : schéma présent (%d tables mappées).", len(Base.metadata.tables))
```

Ajouter à la docstring du module, après le paragraphe sur S227, la ligne :
`S241 : extensions unaccent/pg_trgm, colonnes générées recherche_tsv et index de recherche (app/recherche_schema.py).`

- [ ] **Step 4 : Écrire les fixtures d'intégration**

Créer `briques/forge/forge/core/tests/s241_outils.py` :

```python
"""Outils de test S241 : base et Qdrant RÉELS (lanceur scripts/en_docker.sh), embedder factice.

Les tests qui s'en servent portent le marqueur `integration` : hors du lanceur (variable
FORGE_TEST_INTEGRATION absente), ils sont sautés et le filet scripts/tests_briques.sh reste vert.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

integration = pytest.mark.skipif(
    not os.environ.get("FORGE_TEST_INTEGRATION"),
    reason="test d'intégration : lancer via scripts/en_docker.sh (Postgres + Qdrant réels)",
)

DIMENSION = 384


def vecteur_factice(texte: str) -> list[float]:
    """Sac de mots haché en 384 dimensions, normalisé : déterministe, sans réseau. Deux textes
    qui partagent des mots sont proches ; ce n'est PAS de la sémantique (mesurée à part)."""
    v = [0.0] * DIMENSION
    for mot in re.findall(r"\w+", texte.lower()):
        v[int(hashlib.md5(mot.encode()).hexdigest(), 16) % DIMENSION] += 1.0
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        v[0], n = 1.0, 1.0
    return [x / n for x in v]


@pytest_asyncio.fixture
async def base():
    """Schéma S241 appliqué, tables documentaires vides, collection Qdrant locale supprimée."""
    from app import db, memory
    from scripts.init_db import appliquer_schema

    async with db.engine.begin() as conn:
        await appliquer_schema(conn)
        await conn.execute(text("TRUNCATE documents, kb_articles CASCADE"))
    memory._qdrant = None
    client = memory._client()
    if await client.collection_exists("forge_local"):
        await client.delete_collection("forge_local")
    yield
    # Pool et client liés à la boucle du test : on les ferme pour que le test suivant (nouvelle
    # boucle) ne réutilise pas une connexion d'une boucle morte.
    await db.engine.dispose()
    if memory._qdrant is not None:
        await memory._qdrant.close()
        memory._qdrant = None


@pytest.fixture
def embedder_factice(monkeypatch):
    from app import memory

    async def _faux(textes, provider):
        return [vecteur_factice(t) for t in textes]

    monkeypatch.setattr(memory, "_embed_batch", _faux)
    monkeypatch.setattr(memory, "available_providers", lambda: ["local"])
    monkeypatch.setattr(memory, "resolve_provider", lambda preferred=None: "local")


@pytest.fixture
def embedder_coupe(monkeypatch):
    from app import memory

    async def _panne(textes, provider):
        raise RuntimeError("gateway injoignable")

    monkeypatch.setattr(memory, "_embed_batch", _panne)
    monkeypatch.setattr(memory, "available_providers", lambda: ["local"])
    monkeypatch.setattr(memory, "resolve_provider", lambda preferred=None: "local")


async def ajouter_document(user_id: str, nom: str, contenu: str) -> uuid.UUID:
    from app.db import SessionLocal
    from app.models import Documents

    async with SessionLocal() as s:
        d = Documents(user_id=user_id, nom=nom, contenu=contenu, taille=len(contenu))
        s.add(d)
        await s.commit()
        await s.refresh(d)
        return d.id


async def ajouter_article(user_id: str, titre: str, contenu: str, tags: str = "[]") -> uuid.UUID:
    from app.db import SessionLocal
    from app.models import KbArticles

    async with SessionLocal() as s:
        a = KbArticles(user_id=user_id, titre=titre, contenu=contenu, tags=tags)
        s.add(a)
        await s.commit()
        await s.refresh(a)
        return a.id
```

- [ ] **Step 5 : Écrire les tests du schéma (en échec)**

Créer `briques/forge/forge/core/tests/test_s241_schema.py` :

```python
"""S241 — schéma de recherche : idempotent, sans accents, sans casse."""
from sqlalchemy import text

from tests.s241_outils import ajouter_article, ajouter_document, base, integration  # noqa: F401

pytestmark = integration


async def test_schema_rejouable(base):
    from app.db import engine
    from scripts.init_db import appliquer_schema

    async with engine.begin() as conn:
        await appliquer_schema(conn)  # deuxième passage : aucune erreur
        n = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name IN ('documents', 'kb_articles') AND column_name = 'recherche_tsv'"
        ))).scalar_one()
    assert n == 2


async def test_plein_texte_sans_accents_ni_casse(base):
    from app.db import engine

    await ajouter_document("u1", "Évaluation énergétique", "Rapport de la maison Durand.")
    await ajouter_article("u1", "Procédure", "Relancer les CLIENTS en retard.", '["relances"]')
    async with engine.connect() as conn:
        docs = (await conn.execute(text(
            "SELECT count(*) FROM documents "
            "WHERE recherche_tsv @@ plainto_tsquery('simple', forge_unaccent('evaluation'))"
        ))).scalar_one()
        kb = (await conn.execute(text(
            "SELECT count(*) FROM kb_articles "
            "WHERE recherche_tsv @@ plainto_tsquery('simple', forge_unaccent('relances'))"
        ))).scalar_one()
    assert docs == 1
    assert kb == 1  # les tags sont indexés
```

- [ ] **Step 6 : Lancer, vérifier l'échec**

Docker Desktop doit tourner (`open -a Docker`).
Run : `cd briques/forge/forge/core && scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_schema.py`
Attendu : avant les étapes 2-3, échec d'import (`app.recherche_schema` ou `appliquer_schema` introuvable). Si les étapes 2-3 sont déjà faites, les 2 tests passent : vérifier alors l'échec en commentant temporairement `*MIGRATIONS_S241` dans `appliquer_schema` (colonne absente → `test_schema_rejouable` échoue), puis rétablir.

- [ ] **Step 7 : Lancer, vérifier le succès**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_schema.py`
Attendu : `2 passed`.

Run aussi (filet, hors lanceur, les tests d'intégration doivent être SAUTÉS) : `cd /Users/garinat_t/Desktop/Workplace && scripts/tests_briques.sh forge 2>&1 | tail -5`
Attendu : forge au vert, avec des `skipped`.

- [ ] **Step 8 : Commit**

```bash
git add briques/forge/forge/core/scripts/en_docker.sh briques/forge/forge/core/app/recherche_schema.py \
  briques/forge/forge/core/scripts/init_db.py briques/forge/forge/core/tests/s241_outils.py \
  briques/forge/forge/core/tests/test_s241_schema.py
git commit -m "feat(S241): schéma de recherche Forge (plein texte, trigrammes) et lanceur Postgres+Qdrant"
```

---

### Task 2 : Forge — fonctions pures de fusion

**Files:**
- Create: `briques/forge/forge/core/app/recherche_fusion.py`
- Test: `briques/forge/forge/core/tests/test_s241_fusion.py`

**Interfaces:**
- Produces (`app.recherche_fusion`) :
  - `K_RRF = 60`
  - `Cle = tuple[str, UUID]` — `("document" | "kb", id)`
  - `extraire_references(requete: str) -> list[str]`
  - `motif_reference(reference_normalisee: str) -> str` (motif ARE PostgreSQL)
  - `fusion_rrf(classements: list[list[Cle]], k: int = K_RRF) -> dict[Cle, float]`
  - `CorrespondanceExacte(references_trouvees: int, dans_titre: bool)` (dataclass figée)
  - `Classe(cle: Cle, score: float, correspondance: str)` — `correspondance ∈ {"exacte", "lexicale", "vectorielle", "les_deux"}`
  - `ordonner(exacts: dict[Cle, CorrespondanceExacte], lexical: list[Cle], vectoriel: list[Cle], limite: int) -> list[Classe]`

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/forge/forge/core/tests/test_s241_fusion.py` :

```python
"""S241 — fonctions pures de la recherche Forge (aucune base)."""
from uuid import uuid4

from app.recherche_fusion import (
    CorrespondanceExacte, extraire_references, fusion_rrf, motif_reference, ordonner,
)


def test_extraire_references_codes_et_guillemets():
    refs = extraire_references('facture FAC-2026-0042 pour « contrat cadre », écrire à a@b.fr')
    assert refs == ["contrat cadre", "FAC-2026-0042", "a@b.fr"]


def test_extraire_references_ignore_les_mots_simples():
    assert extraire_references("devis toiture maison") == []


def test_motif_reference_echappe_et_limite_aux_mots():
    m = motif_reference("fac-2026.1")
    assert m == r"(^|[^[:alnum:]])fac-2026\.1($|[^[:alnum:]])"


def test_fusion_rrf_additionne_les_rangs():
    a, b = ("document", uuid4()), ("kb", uuid4())
    s = fusion_rrf([[a, b], [b]])
    assert s[b] > s[a]


def test_ordonner_exacts_devant_puis_rrf():
    exact, lex, vec = ("document", uuid4()), ("document", uuid4()), ("kb", uuid4())
    classes = ordonner({exact: CorrespondanceExacte(1, False)}, [lex, exact], [vec, lex], 10)
    assert [c.cle for c in classes] == [exact, lex, vec]
    assert [c.correspondance for c in classes] == ["exacte", "les_deux", "vectorielle"]
    assert all(classes[i].score > classes[i + 1].score for i in range(len(classes) - 1))


def test_ordonner_respecte_la_limite():
    cles = [("document", uuid4()) for _ in range(5)]
    assert len(ordonner({}, cles, [], 2)) == 2
    assert ordonner({}, cles, [], 0) == []
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `cd briques/forge/forge/core && scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_fusion.py`
Attendu : `ModuleNotFoundError: No module named 'app.recherche_fusion'`.

- [ ] **Step 3 : Implémenter**

Créer `briques/forge/forge/core/app/recherche_fusion.py` (copie adaptée de `briques/memoire/memory/backend/app/services/recherche_fusion.py`, S238 — les briques ne partagent pas de code ; seule différence : les identifiants sont des clés `(source, id)` car documents et articles vivent dans deux tables) :

```python
"""Fonctions pures de la recherche documentaire Forge (S241) : références exactes, RRF, ordre.

Copie adaptée de la Mémoire (S238, briques/memoire/memory/backend/app/services/recherche_fusion.py) :
les briques ne partagent pas de code. Différence : un résultat est identifié par une clé
(source, id), documents et articles vivant dans deux tables.

Les scores lexicaux (ts_rank_cd) et vectoriels (cosinus) ne sont pas comparables : on ne les
additionne jamais, on fusionne les RANGS (Reciprocal Rank Fusion).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

K_RRF = 60
LONGUEUR_REFERENCE_MAX = 100
REFERENCES_MAX = 10

Cle = tuple[str, UUID]

_GUILLEMETS = re.compile(r'"([^"]+)"|«\s*([^»]+?)\s*»|“([^”]+)”')
_CARACTERES_REFERENCE = set("-_./@#")
_BORDS = ".,;:!?()[]{}'\"«»“”…"


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
        if expression and len(expression) <= LONGUEUR_REFERENCE_MAX:
            candidates.append(expression)
    for jeton in _GUILLEMETS.sub(" ", requete).split():
        jeton = jeton.strip(_BORDS)
        if _est_reference(jeton) and len(jeton) <= LONGUEUR_REFERENCE_MAX:
            candidates.append(jeton)
    vues, references = set(), []
    for c in candidates:
        if c.casefold() not in vues:
            vues.add(c.casefold())
            references.append(c)
    return references[:REFERENCES_MAX]


def motif_reference(reference: str) -> str:
    """Motif ARE PostgreSQL trouvant `reference` comme mot entier. `reference` doit être DÉJÀ
    normalisée en SQL (forge_unaccent(lower(...))) : normaliser après l'échappement pourrait
    produire des métacaractères (unaccent développe ⁇ en ??). Seuls les métacaractères ARE
    ASCII sont échappés ; les espaces d'une expression acceptent tout blanc."""
    morceaux = [re.sub(r"([\\^$.|?*+()\[\]{}])", r"\\\1", m) for m in reference.split()]
    return "(^|[^[:alnum:]])" + "[[:space:]]+".join(morceaux) + "($|[^[:alnum:]])"


def fusion_rrf(classements: list[list[Cle]], k: int = K_RRF) -> dict[Cle, float]:
    scores: dict[Cle, float] = {}
    for classement in classements:
        for rang, cle in enumerate(classement, start=1):
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (k + rang)
    return scores


@dataclass(frozen=True)
class CorrespondanceExacte:
    references_trouvees: int
    dans_titre: bool


@dataclass(frozen=True)
class Classe:
    cle: Cle
    score: float
    correspondance: str  # exacte | lexicale | vectorielle | les_deux


def ordonner(
    exacts: dict[Cle, CorrespondanceExacte],
    lexical: list[Cle],
    vectoriel: list[Cle],
    limite: int,
) -> list[Classe]:
    """Références exactes d'abord (plus de références trouvées, puis titre avant contenu, puis
    rang de fusion), ensuite le reste par score RRF décroissant.

    Un score de fusion vaut au plus 2/(K_RRF+1) < 0,04 : le palier exact
    (1 + nombre de références + 0,5 si dans le titre) reste toujours au-dessus."""
    if limite < 1:
        return []
    fusion = fusion_rrf([lexical, vectoriel])
    ens_lex, ens_vec = set(lexical), set(vectoriel)

    def correspondance(c: Cle) -> str:
        if c in exacts:
            return "exacte"
        if c in ens_lex and c in ens_vec:
            return "les_deux"
        return "lexicale" if c in ens_lex else "vectorielle"

    scores = {}
    for c in set(fusion) | set(exacts):
        s = fusion.get(c, 0.0)
        if c in exacts:
            s += 1.0 + exacts[c].references_trouvees + (0.5 if exacts[c].dans_titre else 0.0)
        scores[c] = s
    ordre = sorted(scores, key=lambda c: (-scores[c], c[0], str(c[1])))[:limite]
    # Rangs croisés → scores RRF égaux : un epsilon de position rend la suite strictement
    # décroissante sans changer l'ordre.
    n = len(ordre)
    return [Classe(c, scores[c] + (n - pos) * 1e-9, correspondance(c)) for pos, c in enumerate(ordre)]
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_fusion.py`
Attendu : `6 passed`.

- [ ] **Step 5 : Commit**

```bash
git add briques/forge/forge/core/app/recherche_fusion.py briques/forge/forge/core/tests/test_s241_fusion.py
git commit -m "feat(S241): fusion RRF et références exactes de la recherche Forge"
```

---

### Task 3 : Forge — le RAG ne lit plus les documents des autres (faille)

**Files:**
- Modify: `briques/forge/forge/core/app/memory.py`
- Modify: `briques/forge/forge/core/app/routers/rag.py`, `app/routers/chat.py`, `app/routers/ws.py`, `app/react_executor.py`
- Test: `briques/forge/forge/core/tests/test_s241_rag_isolation.py`

**Interfaces:**
- Consumes : fixtures de `tests.s241_outils` (Task 1).
- Produces (`app.memory`) :
  - `class RechercheVectorielleIndisponible(Exception)`
  - `SOURCES_INDEXEES: tuple[str, ...] = ("document", "kb_article")`
  - `collection_active() -> tuple[str, str]` → `(provider, nom_collection)`
  - `Fragment(source_type: str, source_id: str, texte: str, score: float)` (dataclass figée)
  - `async chercher_fragments(question: str, user_id: str, limite: int = 30) -> list[Fragment]` — lève `RechercheVectorielleIndisponible`
  - `async indexer_source(texte: str, source_id: str, source_type: str, user_id: str, titre: str) -> int` — lève `RechercheVectorielleIndisponible`
  - `async get_context(question, _session_id, *, user_id: str, limit=5, min_score=0.65, pole_id=None, provider=None) -> str` (**`user_id` désormais obligatoire, nommé**)
  - `app.react_executor.get_context(query: str, session_id: str, user_id: str) -> str`

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/forge/forge/core/tests/test_s241_rag_isolation.py` :

```python
"""S241 — faille : `_qdrant_search` ne filtrait que pole_id, jamais user_id.

`GET /api/rag/search`, le chat et le ReAct renvoyaient donc les passages des documents de
TOUS les utilisateurs. Ces tests tournent sur un Qdrant réel : un mock n'aurait pas vu que
le filtre manquait."""
import inspect

import pytest

from app import memory
from tests.s241_outils import base, embedder_coupe, embedder_factice, integration  # noqa: F401

TEXTE = "Contrat de maintenance de la chaudière du client Durand, renouvelé chaque année."


def test_get_context_exige_l_utilisateur():
    parametre = inspect.signature(memory.get_context).parameters["user_id"]
    assert parametre.kind is inspect.Parameter.KEYWORD_ONLY
    assert parametre.default is inspect.Parameter.empty


@integration
async def test_get_context_ne_renvoie_que_les_passages_de_l_utilisateur(base, embedder_factice, monkeypatch):
    monkeypatch.setattr(memory, "mem_prefetch", lambda *a, **k: _vide())
    await memory.indexer_source(TEXTE, "11111111-1111-1111-1111-111111111111", "document", "alice", "Contrat")
    assert "chaudière" in await memory.get_context(TEXTE, "s", user_id="alice")
    assert await memory.get_context(TEXTE, "s", user_id="bob") == ""


@integration
async def test_chercher_fragments_filtre_par_utilisateur(base, embedder_factice):
    await memory.indexer_source(TEXTE, "11111111-1111-1111-1111-111111111111", "document", "alice", "Contrat")
    assert [f.source_id for f in await memory.chercher_fragments(TEXTE, "alice")] \
        == ["11111111-1111-1111-1111-111111111111"]
    assert await memory.chercher_fragments(TEXTE, "bob") == []


@integration
async def test_chercher_fragments_signale_la_panne(base, embedder_coupe):
    with pytest.raises(memory.RechercheVectorielleIndisponible):
        await memory.chercher_fragments(TEXTE, "alice")


@integration
async def test_indexer_source_remplace_les_anciens_fragments(base, embedder_factice):
    sid = "22222222-2222-2222-2222-222222222222"
    await memory.indexer_source(TEXTE, sid, "kb_article", "alice", "v1")
    await memory.indexer_source("Nouvelle version : contrat résilié en mars, plus aucune visite.", sid,
                                "kb_article", "alice", "v2")
    fragments = await memory.chercher_fragments("contrat résilié", "alice")
    assert {f.texte for f in fragments} == {"Nouvelle version : contrat résilié en mars, plus aucune visite."}


async def _vide():
    return []
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_rag_isolation.py`
Attendu : `KeyError: 'user_id'` (signature) et `AttributeError: ... 'indexer_source'`.

- [ ] **Step 3 : Implémenter dans `memory.py`**

Dans `briques/forge/forge/core/app/memory.py` :

a) ajouter `from dataclasses import dataclass` aux imports ;

b) juste après `CHUNK_OVERLAP = 64`, ajouter :

```python
# Types de sources vectorisées par la Forge (routers documents et kb) — rien d'autre n'écrit
# dans Qdrant. La réconciliation S241 ne touche qu'à ces types.
SOURCES_INDEXEES = ("document", "kb_article")


class RechercheVectorielleIndisponible(Exception):
    """Embedder ou Qdrant injoignable : la recherche par le sens n'a pas pu être faite (S241).
    Jamais remplacée par une liste vide silencieuse : l'appelant passe en mode lexical et le dit."""


@dataclass(frozen=True)
class Fragment:
    source_type: str
    source_id: str
    texte: str
    score: float
```

c) après `resolve_provider`, ajouter :

```python
def collection_active() -> tuple[str, str]:
    """(provider, collection) utilisés par la recherche et la réconciliation S241."""
    provider = resolve_provider(None)
    return provider, COLLECTIONS[provider]["name"]


def _filtre_utilisateur(user_id: str, pole_id: str | None = None) -> qm.Filter:
    conditions = [qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))]
    if pole_id:
        conditions.append(qm.FieldCondition(key="pole_id", match=qm.MatchValue(value=pole_id)))
    return qm.Filter(must=conditions)
```

d) après `delete_by_source`, ajouter :

```python
async def indexer_source(texte: str, source_id: str, source_type: str, user_id: str, titre: str) -> int:
    """(Re)vectorise UNE source dans la collection active (réconciliation S241).

    Contrairement à `ingest` (best-effort, tous providers, écrit aussi dans la brique
    Mémoire), lève `RechercheVectorielleIndisponible` sur toute panne et n'écrit QUE dans
    Qdrant. Les anciens fragments de la source sont supprimés d'abord."""
    provider, nom = collection_active()
    morceaux = chunk_text(texte)
    try:
        client = _client()
        await _ensure_collection(nom, COLLECTIONS[provider]["size"])
        await client.delete(nom, points_selector=qm.FilterSelector(filter=qm.Filter(
            must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
        )))
        if not morceaux:
            return 0
        vecteurs = await _embed_batch(morceaux, provider)
        horodatage = datetime.datetime.utcnow().isoformat() + "Z"
        await client.upsert(nom, points=[
            qm.PointStruct(
                id=str(uuidlib.uuid4()),
                vector=vecteurs[i],
                payload={
                    "text": morceau, "source_id": source_id, "source_type": source_type,
                    "user_id": user_id, "pole_id": None, "title": titre or "",
                    "timestamp": horodatage, "provider": provider,
                },
            )
            for i, morceau in enumerate(morceaux)
        ])
    except Exception as e:  # noqa: BLE001 — toute panne embedder/Qdrant est signalée
        raise RechercheVectorielleIndisponible(str(e)[:200]) from e
    return len(morceaux)


async def chercher_fragments(question: str, user_id: str, limite: int = 30) -> list[Fragment]:
    """Fragments les plus proches de `question`, de CET utilisateur seulement (S241)."""
    if not user_id:
        raise ValueError("user_id requis : jamais de recherche vectorielle sans propriétaire")
    provider, nom = collection_active()
    try:
        vecteur, _ = await embed_one(question, provider)
        client = _client()
        if not await client.collection_exists(nom):
            return []
        resultats = await client.search(
            nom, query_vector=vecteur, limit=limite, with_payload=True,
            query_filter=_filtre_utilisateur(user_id),
        )
    except Exception as e:  # noqa: BLE001
        raise RechercheVectorielleIndisponible(str(e)[:200]) from e
    fragments = []
    for r in resultats:
        p = r.payload or {}
        fragments.append(Fragment(str(p.get("source_type") or ""), str(p.get("source_id") or ""),
                                  str(p.get("text") or ""), float(r.score)))
    return fragments
```

e) remplacer `_qdrant_search` et `get_context` par :

```python
async def _qdrant_search(question: str, limit: int, min_score: float, user_id: str,
                         pole_id: str | None, provider: str | None) -> str:
    try:
        prov = resolve_provider(provider)
        vector, collection = await embed_one(question, prov)
        # S241 : filtre user_id OBLIGATOIRE — avant, seul pole_id filtrait et chacun lisait
        # les passages des documents de tous les utilisateurs.
        results = await _client().search(
            collection, query_vector=vector, limit=limit, with_payload=True,
            query_filter=_filtre_utilisateur(user_id, pole_id),
        )
        relevant = [r for r in results if r.score > min_score]
        if not relevant:
            return ""

        def _rank(r):
            ts = (r.payload or {}).get("timestamp") or 0
            try:
                t = datetime.datetime.fromisoformat(str(ts).replace("Z", "")).timestamp() if ts else 0
            except (ValueError, TypeError):
                t = 0
            return r.score * 0.7 + (t / 1e12) * 0.3

        relevant.sort(key=_rank, reverse=True)
        return "\n\n---\n\n".join(
            f"[{(r.payload or {}).get('title') or (r.payload or {}).get('source_type') or 'doc'}]\n"
            f"{(r.payload or {}).get('text')}"
            for r in relevant
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[forge:retriever] RAG failed: %s", str(e)[:120])
        return ""


async def get_context(question: str, _session_id: str, *, user_id: str, limit: int = 5,
                      min_score: float = 0.65, pole_id: str | None = None,
                      provider: str | None = None) -> str:
    """Recherche sémantique Qdrant (documents de `user_id` seulement, S241) + enrichissement
    brique Mémoire Workplace opt-in. Sans utilisateur, aucun passage Qdrant."""
    rag = await _qdrant_search(question, limit, min_score, user_id, pole_id, provider) if user_id else ""
    hits = await mem_prefetch(question, 3)
    return rag + mem_format_context(hits)
```

- [ ] **Step 4 : Mettre à jour les appelants**

`app/routers/rag.py` — remplacer l'appel par :

```python
    passages = await get_context(
        q, _session_id=f"rag-search:{user.sub}", user_id=user.sub, limit=limite, min_score=seuil
    )
```

`app/routers/chat.py` — `_save_and_prepare` prend l'utilisateur :

```python
async def _save_and_prepare(body: Message, user_id: str):
    context = await get_context(body.content, body.sessionId, user_id=user_id)
```

et les deux appels deviennent `await _save_and_prepare(body, user.sub)` (routes `chat` et `chat_stream`).

`app/routers/ws.py:198` :

```python
            rag = await get_context(content, session_id, user_id=user_id)
```

`app/react_executor.py` — le relais prend l'utilisateur :

```python
async def get_context(query: str, session_id: str, user_id: str) -> str:
    """RAG best-effort via le module mémoire (S129), limité aux documents de `user_id` (S241)."""
    from app.memory import get_context as _mem_get_context

    return await _mem_get_context(query, session_id, user_id=user_id)
```

ligne 94 : `return (await get_context(args.get("query", ""), session_id, user_id)) or "Nothing found."`
ligne 163 : `rag = await get_context(input_text, session_id, user_id)`

Puis vérifier qu'aucun autre appelant ne reste : `grep -rn "get_context(" briques/forge/forge/core/app briques/forge/forge/core/tests` — chaque appel doit passer l'utilisateur. Si un test existant remplace `react_executor.get_context` ou `memory.get_context` par une fonction à deux paramètres, l'adapter à la nouvelle signature (ajouter `user_id` / `*, user_id=None`).

- [ ] **Step 5 : Lancer, vérifier le succès**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_rag_isolation.py`
Attendu : `5 passed`.

Run (toute la suite Forge core, pour les appelants) : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q`
Attendu : aucun échec (noter le compte exact dans le message de commit).

- [ ] **Step 6 : Commit**

```bash
git add briques/forge/forge/core/app/memory.py briques/forge/forge/core/app/routers/rag.py \
  briques/forge/forge/core/app/routers/chat.py briques/forge/forge/core/app/routers/ws.py \
  briques/forge/forge/core/app/react_executor.py briques/forge/forge/core/tests/test_s241_rag_isolation.py
git commit -m "fix(S241): le RAG Forge ne renvoie plus les passages des documents d'un autre utilisateur"
```

---

### Task 4 : Forge — branches SQL de la recherche

**Files:**
- Create: `briques/forge/forge/core/app/recherche_documents.py`
- Test: `briques/forge/forge/core/tests/test_s241_branches.py`

**Interfaces:**
- Consumes : `app.recherche_schema.TABLES`, `texte_normalise`, `titre_normalise` (Task 1) ; `app.recherche_fusion.Cle`, `CorrespondanceExacte`, `motif_reference` (Task 2).
- Produces (`app.recherche_documents`) :
  - `SEUIL_TRIGRAMME = 0.3`, `LONGUEUR_EXTRAIT = 280`
  - `termes(requete: str) -> list[str]`
  - `extrait_autour(texte: str, mots: list[str], longueur: int = LONGUEUR_EXTRAIT) -> str` (pure)
  - `async plein_texte(s, requete, user_id, sources, limite) -> list[Cle]`
  - `async trigrammes(s, requete, user_id, sources, limite) -> list[Cle]`
  - `async exacts(s, references, user_id, sources, limite) -> dict[Cle, CorrespondanceExacte]`
  - `async existants(s, cles: list[Cle], user_id) -> set[Cle]`
  - `Fiche(titre: str, texte: str)` ; `async fiches(s, cles: list[Cle], user_id) -> dict[Cle, Fiche]`
  - (`s` = `AsyncSession`, `sources` = `frozenset[str]` ⊂ `{"document", "kb"}`)

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/forge/forge/core/tests/test_s241_branches.py` :

```python
"""S241 — branches SQL : chaque branche ne voit QUE les lignes de l'utilisateur."""
from app import recherche_documents as rd
from app.db import SessionLocal
from tests.s241_outils import ajouter_article, ajouter_document, base, integration  # noqa: F401

TOUT = frozenset({"document", "kb"})


def test_extrait_autour_centre_sur_le_premier_mot():
    texte = "x" * 500 + " chaudière " + "y" * 500
    extrait = rd.extrait_autour(texte, ["chaudiere"], 100)
    assert "chaudière" in extrait and len(extrait) <= 102  # + « … » éventuels


def test_extrait_autour_sans_mot_trouve_prend_le_debut():
    assert rd.extrait_autour("abc def", ["zzz"], 3) == "abc…"


@integration
async def test_plein_texte_isole_et_couvre_les_deux_tables(base):
    d = await ajouter_document("alice", "Devis toiture", "Réfection de la toiture, 12 000 €.")
    k = await ajouter_article("alice", "Toiture : procédure", "Vérifier les tuiles.")
    await ajouter_document("bob", "Devis toiture Bob", "Toiture de Bob.")
    async with SessionLocal() as s:
        cles = await rd.plein_texte(s, "toiture", "alice", TOUT, 10)
        assert set(cles) == {("document", d), ("kb", k)}
        assert await rd.plein_texte(s, "toiture", "alice", frozenset({"kb"}), 10) == [("kb", k)]


@integration
async def test_trigrammes_rattrapent_la_faute_de_frappe(base):
    d = await ajouter_document("alice", "Contrat", "Contrat de maintenance annuelle.")
    async with SessionLocal() as s:
        assert await rd.plein_texte(s, "maintenence", "alice", TOUT, 10) == []
        assert await rd.trigrammes(s, "maintenence", "alice", TOUT, 10) == [("document", d)]
        assert await rd.trigrammes(s, "maintenence", "bob", TOUT, 10) == []


@integration
async def test_exacts_trouvent_la_reference_et_signalent_le_titre(base):
    titre = await ajouter_document("alice", "FAC-2026-0042", "Facture de mars.")
    corps = await ajouter_document("alice", "Relance", "Rappel : FAC-2026-0042 impayée.")
    await ajouter_document("alice", "Autre", "FAC-2026-00421 n'est pas la même.")
    async with SessionLocal() as s:
        trouves = await rd.exacts(s, ["FAC-2026-0042"], "alice", TOUT, 10)
        assert set(trouves) == {("document", titre), ("document", corps)}
        assert trouves[("document", titre)].dans_titre is True
        assert trouves[("document", corps)].dans_titre is False
        assert await rd.exacts(s, ["FAC-2026-0042"], "bob", TOUT, 10) == {}


@integration
async def test_existants_et_fiches_recoupent_par_utilisateur(base):
    a = await ajouter_document("alice", "A", "texte A")
    b = await ajouter_document("bob", "B", "texte B")
    async with SessionLocal() as s:
        assert await rd.existants(s, [("document", a), ("document", b)], "alice") == {("document", a)}
        fiches = await rd.fiches(s, [("document", a), ("document", b)], "alice")
        assert set(fiches) == {("document", a)} and fiches[("document", a)].titre == "A"
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_branches.py`
Attendu : `ModuleNotFoundError: No module named 'app.recherche_documents'`.

- [ ] **Step 3 : Implémenter**

Créer `briques/forge/forge/core/app/recherche_documents.py` :

```python
"""Branches SQL de la recherche documentaire Forge (S241) : exacte, plein texte, trigrammes.

Toute requête porte `user_id = :moi` DANS le SQL : aucune ligne d'un autre utilisateur ne
peut sortir d'une branche, quelle que soit la requête. Les noms de tables et de colonnes
viennent de `recherche_schema.TABLES` (constantes), jamais de l'appelant.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.recherche_fusion import Cle, CorrespondanceExacte, motif_reference
from app.recherche_schema import TABLES, TableRecherche, texte_normalise, titre_normalise

SEUIL_TRIGRAMME = 0.3
TERMES_MAX = 32
LONGUEUR_EXTRAIT = 280
_TEXTE_FICHE_MAX = 20_000


def termes(requete: str) -> list[str]:
    """Mots de la requête (lettres et chiffres seulement : aucun opérateur tsquery ne passe)."""
    return re.findall(r"[^\W_]+", requete.lower())[:TERMES_MAX]


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower()) if not unicodedata.combining(c))


def extrait_autour(texte: str, mots: list[str], longueur: int = LONGUEUR_EXTRAIT) -> str:
    """Fenêtre de `longueur` caractères centrée sur le premier mot trouvé (sans casse ni
    accents), sinon le début du texte. « … » marque une coupe."""
    texte = " ".join((texte or "").split())
    if len(texte) <= longueur:
        return texte
    normalise = _sans_accents(texte)
    positions = [p for p in (normalise.find(_sans_accents(m)) for m in mots) if p >= 0]
    debut = max(0, min(positions) - longueur // 3) if positions else 0
    debut = min(debut, max(0, len(texte) - longueur))
    morceau = texte[debut:debut + longueur]
    return ("…" if debut > 0 else "") + morceau + ("…" if debut + longueur < len(texte) else "")


def _tables(sources: frozenset[str]) -> list[TableRecherche]:
    return [TABLES[s] for s in ("document", "kb") if s in sources]


async def plein_texte(s: AsyncSession, requete: str, user_id: str, sources: frozenset[str],
                      limite: int) -> list[Cle]:
    """OU sur les termes, en `simple` et en `french`, classé par ts_rank_cd."""
    mots, tables = termes(requete), _tables(sources)
    if not mots or not tables:
        return []
    params: dict = {"moi": user_id, "limite": limite}
    morceaux = []
    for i, mot in enumerate(mots):
        params[f"t{i}"] = mot
        morceaux.append(f"plainto_tsquery('simple', forge_unaccent(:t{i})) || "
                        f"plainto_tsquery('french', forge_unaccent(:t{i}))")
    unions = " UNION ALL ".join(
        f"SELECT '{t.source}' AS source, x.id, ts_rank_cd(x.recherche_tsv, q.r) AS rang, "
        f"x.created_at AS date FROM {t.table} x, q WHERE x.user_id = :moi AND x.recherche_tsv @@ q.r"
        for t in tables
    )
    sql = text(f"WITH q AS (SELECT ({' || '.join(morceaux)}) AS r) "
               f"SELECT source, id FROM ({unions}) u ORDER BY rang DESC, date DESC, id LIMIT :limite")
    return [(r[0], r[1]) for r in (await s.execute(sql, params)).all()]


async def trigrammes(s: AsyncSession, requete: str, user_id: str, sources: frozenset[str],
                     limite: int) -> list[Cle]:
    """Filet pour les fautes de frappe, utilisé quand le plein texte ne trouve rien."""
    tables = _tables(sources)
    if not requete.strip() or not tables:
        return []
    params = {"moi": user_id, "q": requete.strip(), "seuil": SEUIL_TRIGRAMME, "limite": limite}
    unions = []
    for t in tables:
        similarite = f"word_similarity(forge_unaccent(lower(:q)), {texte_normalise(t, 'x.')})"
        unions.append(f"SELECT '{t.source}' AS source, x.id, {similarite} AS rang, x.created_at AS date "
                      f"FROM {t.table} x WHERE x.user_id = :moi AND {similarite} >= :seuil")
    sql = text(f"SELECT source, id FROM ({' UNION ALL '.join(unions)}) u "
               f"ORDER BY rang DESC, date DESC, id LIMIT :limite")
    return [(r[0], r[1]) for r in (await s.execute(sql, params)).all()]


async def _references_normalisees(s: AsyncSession, references: list[str]) -> list[str]:
    """Références passées par la MÊME normalisation que le texte, dans l'ordre d'origine."""
    sql = text("SELECT forge_unaccent(lower(r)) FROM unnest(CAST(:refs AS text[])) "
               "WITH ORDINALITY AS t(r, i) ORDER BY i")
    return [r[0] for r in (await s.execute(sql, {"refs": references})).all()]


async def exacts(s: AsyncSession, references: list[str], user_id: str, sources: frozenset[str],
                 limite: int) -> dict[Cle, CorrespondanceExacte]:
    """Documents contenant littéralement au moins une référence (mot entier, sans casse ni
    accents), avec le nombre de références trouvées et leur présence dans le titre."""
    tables = _tables(sources)
    if not references or not tables:
        return {}
    normalisees = [r for r in await _references_normalisees(s, references) if r and r.strip()]
    if not normalisees:
        return {}
    params: dict = {"moi": user_id, "limite": limite}
    for i, reference in enumerate(normalisees):
        params[f"r{i}"] = motif_reference(reference)
    unions = []
    for t in tables:
        comptes = " + ".join(f"(CASE WHEN {texte_normalise(t, 'x.')} ~ :r{i} THEN 1 ELSE 0 END)"
                             for i in range(len(normalisees)))
        titres = " OR ".join(f"{titre_normalise(t, 'x.')} ~ :r{i}" for i in range(len(normalisees)))
        unions.append(f"SELECT '{t.source}' AS source, x.id, x.created_at AS date, ({comptes}) AS trouvees, "
                      f"({titres}) AS dans_titre FROM {t.table} x WHERE x.user_id = :moi")
    sql = text(f"SELECT source, id, trouvees, dans_titre FROM ({' UNION ALL '.join(unions)}) u "
               f"WHERE trouvees > 0 ORDER BY trouvees DESC, dans_titre DESC, date DESC, id LIMIT :limite")
    return {(r[0], r[1]): CorrespondanceExacte(int(r[2]), bool(r[3]))
            for r in (await s.execute(sql, params)).all()}


async def existants(s: AsyncSession, cles: list[Cle], user_id: str) -> set[Cle]:
    """Recoupement : parmi `cles`, celles qui existent encore ET appartiennent à `user_id`.
    Écarte les fragments Qdrant orphelins (document supprimé) ou mal attribués."""
    trouvees: set[Cle] = set()
    for t in TABLES.values():
        ids = [i for (source, i) in cles if source == t.source]
        if not ids:
            continue
        lignes = await s.execute(
            text(f"SELECT id FROM {t.table} WHERE user_id = :moi AND id = ANY(CAST(:ids AS uuid[]))"),
            {"moi": user_id, "ids": [str(i) for i in ids]},
        )
        trouvees |= {(t.source, r[0]) for r in lignes.all()}
    return trouvees


@dataclass(frozen=True)
class Fiche:
    titre: str
    texte: str


async def fiches(s: AsyncSession, cles: list[Cle], user_id: str) -> dict[Cle, Fiche]:
    """Titre et début du contenu des résultats à afficher (toujours filtré par `user_id`)."""
    resultat: dict[Cle, Fiche] = {}
    for t in TABLES.values():
        ids = [i for (source, i) in cles if source == t.source]
        if not ids:
            continue
        lignes = await s.execute(
            text(f"SELECT id, {t.titre}, left(coalesce(contenu, ''), {_TEXTE_FICHE_MAX}) FROM {t.table} "
                 f"WHERE user_id = :moi AND id = ANY(CAST(:ids AS uuid[]))"),
            {"moi": user_id, "ids": [str(i) for i in ids]},
        )
        for r in lignes.all():
            resultat[(t.source, r[0])] = Fiche(r[1] or "", r[2] or "")
    return resultat
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_branches.py`
Attendu : `6 passed`.

- [ ] **Step 5 : Commit**

```bash
git add briques/forge/forge/core/app/recherche_documents.py briques/forge/forge/core/tests/test_s241_branches.py
git commit -m "feat(S241): branches exacte, plein texte et trigrammes de la recherche Forge, isolées par utilisateur"
```

---

### Task 5 : Forge — service hybride et route `/api/recherche/hybride`

**Files:**
- Create: `briques/forge/forge/core/app/recherche_service.py`
- Create: `briques/forge/forge/core/app/routers/recherche.py`
- Modify: `briques/forge/forge/core/app/main.py` (import + `mount_both`)
- Test: `briques/forge/forge/core/tests/test_s241_recherche.py`

**Interfaces:**
- Consumes : Tasks 2, 3, 4.
- Produces :
  - `app.recherche_service.SOURCES: frozenset[str] = frozenset({"document", "kb"})`
  - `async app.recherche_service.rechercher(requete: str, user_id: str, limite: int = 10, sources: frozenset[str] = SOURCES) -> dict` → `{"mode": "hybride" | "lexical", "resultats": [{"id": str, "source": "document" | "kb", "titre": str, "extrait": str, "rang": int, "exact": bool}]}`
  - Route `GET /api/recherche/hybride?q=&limite=&sources=` (et `/v1/api/...`), protégée par `get_current_user`, même réponse.

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/forge/forge/core/tests/test_s241_recherche.py` :

```python
"""S241 — recherche hybride Forge de bout en bout (Postgres + Qdrant réels, embedder factice)."""
import pytest_asyncio
from sqlalchemy import text

from app import memory
from app.auth import UserContext, get_current_user
from tests.s241_outils import (  # noqa: F401
    ajouter_article, ajouter_document, base, embedder_coupe, embedder_factice, integration,
)

pytestmark = integration


@pytest_asyncio.fixture
async def alice(app):
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        sub="alice", nom="Alice", avatar_emoji="🦊", org_id=None)
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def _chercher(client, q, **params):
    r = await client.get("/api/recherche/hybride", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


async def test_reference_exacte_en_tete(base, embedder_factice, alice, client):
    cible = await ajouter_document("alice", "Relance", "Rappel : la facture FAC-2026-0042 reste impayée.")
    await ajouter_document("alice", "Facture", "Facture de mars, réglée.")
    rep = await _chercher(client, "facture FAC-2026-0042")
    assert rep["resultats"][0]["id"] == str(cible) and rep["resultats"][0]["exact"] is True


async def test_faute_de_frappe(base, embedder_factice, alice, client):
    cible = await ajouter_article("alice", "Maintenance", "Contrat de maintenance annuelle de la chaudière.")
    rep = await _chercher(client, "maintenence")
    assert [r["id"] for r in rep["resultats"]] == [str(cible)]
    assert rep["resultats"][0]["source"] == "kb"


async def test_aucune_fuite_dans_aucune_branche(base, embedder_factice, alice, client):
    texte = "Plan de financement confidentiel FIN-77 pour le rachat."
    secret = await ajouter_document("bob", "Secret de Bob", texte)
    await memory.indexer_source(texte, str(secret), "document", "bob", "Secret de Bob")
    # Fragment de Bob volontairement mal attribué à Alice dans Qdrant : le recoupement
    # PostgreSQL (user_id) doit l'écarter.
    await memory.indexer_source(texte, str(secret), "document", "alice", "Secret de Bob")
    for q in ("financement confidentiel", "FIN-77", "finnancement"):
        assert (await _chercher(client, q))["resultats"] == [], q


async def test_document_supprime_introuvable_meme_si_qdrant_garde_ses_fragments(base, embedder_factice, alice, client):
    from app.db import engine
    texte = "Compte rendu de chantier, toiture terminée."
    doc = await ajouter_document("alice", "CR chantier", texte)
    await memory.indexer_source(texte, str(doc), "document", "alice", "CR chantier")
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM documents WHERE id = :i"), {"i": doc})
    assert (await _chercher(client, "compte rendu chantier"))["resultats"] == []


async def test_branche_vectorielle_regroupe_et_donne_l_extrait(base, alice, client, monkeypatch):
    doc = await ajouter_document("alice", "Note", "Aucun mot de la requête ici.")

    async def _fragments(question, user_id, limite=30):
        return [memory.Fragment("document", str(doc), "passage pertinent A", 0.9),
                memory.Fragment("document", str(doc), "passage B", 0.8)]

    monkeypatch.setattr(memory, "chercher_fragments", _fragments)
    rep = await _chercher(client, "question sémantique")
    assert rep["mode"] == "hybride"
    assert [(r["id"], r["extrait"]) for r in rep["resultats"]] == [(str(doc), "passage pertinent A")]


async def test_embedder_coupe_mode_lexical(base, embedder_coupe, alice, client):
    cible = await ajouter_document("alice", "Devis toiture", "Réfection complète.")
    rep = await _chercher(client, "toiture")
    assert rep["mode"] == "lexical" and [r["id"] for r in rep["resultats"]] == [str(cible)]


async def test_filtre_sources_et_requete_vide(base, embedder_factice, alice, client):
    await ajouter_document("alice", "Toiture", "doc")
    k = await ajouter_article("alice", "Toiture", "article")
    assert [r["id"] for r in (await _chercher(client, "toiture", sources="kb"))["resultats"]] == [str(k)]
    assert (await _chercher(client, "  "))["resultats"] == []


async def test_sans_authentification_refuse(base, client):
    r = await client.get("/api/recherche/hybride", params={"q": "x"})
    assert r.status_code in (401, 403)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_recherche.py`
Attendu : réponses 404 (route absente) → assertions en échec.

- [ ] **Step 3 : Implémenter le service**

Créer `briques/forge/forge/core/app/recherche_service.py` :

```python
"""Recherche hybride des documents et de la base de connaissances Forge (S241).

PostgreSQL fait foi, Qdrant n'est qu'un index : les fragments vectoriels sont RECOUPÉS avec
PostgreSQL (existence + propriétaire) avant toute fusion. Embedder ou Qdrant en panne → mode
« lexical », annoncé, jamais une liste vide présentée comme un succès.
"""
from __future__ import annotations

from uuid import UUID

from app import memory
from app import recherche_documents as rd
from app.db import SessionLocal
from app.recherche_fusion import Cle, extraire_references, ordonner

SOURCES: frozenset[str] = frozenset({"document", "kb"})
_TYPE_VERS_SOURCE = {"document": "document", "kb_article": "kb"}


def _borner(limite: int) -> int:
    return min(max(int(limite), 1), 50)


async def _branche_vectorielle(requete: str, user_id: str, sources: frozenset[str],
                               candidats: int) -> tuple[str, list[Cle], dict[Cle, str]]:
    """(mode, clés par meilleur fragment, extrait du meilleur fragment par clé)."""
    try:
        fragments = await memory.chercher_fragments(requete, user_id, limite=candidats * 3)
    except memory.RechercheVectorielleIndisponible:
        return "lexical", [], {}
    cles: list[Cle] = []
    extraits: dict[Cle, str] = {}
    for f in sorted(fragments, key=lambda f: -f.score):
        source = _TYPE_VERS_SOURCE.get(f.source_type)
        if source not in sources:
            continue
        try:
            cle = (source, UUID(f.source_id))
        except ValueError:
            continue
        if cle not in extraits:
            extraits[cle] = f.texte
            cles.append(cle)
    return "hybride", cles, extraits


async def rechercher(requete: str, user_id: str, limite: int = 10,
                     sources: frozenset[str] = SOURCES) -> dict:
    requete = (requete or "").strip()
    sources = frozenset(sources) & SOURCES
    if not requete or not sources:
        return {"mode": "hybride", "resultats": []}
    limite = _borner(limite)
    candidats = limite * 3

    async with SessionLocal() as s:
        exacts = await rd.exacts(s, extraire_references(requete), user_id, sources, candidats)
        lexical = await rd.plein_texte(s, requete, user_id, sources, candidats)
        if not lexical:
            lexical = await rd.trigrammes(s, requete, user_id, sources, candidats)

    mode, vectoriel, extraits_vect = await _branche_vectorielle(requete, user_id, sources, candidats)

    async with SessionLocal() as s:
        if vectoriel:
            presents = await rd.existants(s, vectoriel, user_id)
            vectoriel = [c for c in vectoriel if c in presents]
        classes = ordonner(exacts, lexical, vectoriel, limite)
        fiches = await rd.fiches(s, [c.cle for c in classes], user_id)

    mots = rd.termes(requete)
    resultats = []
    for c in classes:
        fiche = fiches.get(c.cle)
        if fiche is None:  # supprimé entre les deux lectures
            continue
        if c.correspondance == "vectorielle":
            extrait = rd.extrait_autour(extraits_vect.get(c.cle, ""), mots)
        else:
            extrait = rd.extrait_autour(fiche.texte, mots)
        resultats.append({"id": str(c.cle[1]), "source": c.cle[0], "titre": fiche.titre,
                          "extrait": extrait, "rang": len(resultats) + 1,
                          "exact": c.correspondance == "exacte"})
    return {"mode": mode, "resultats": resultats}
```

- [ ] **Step 4 : Implémenter la route**

Créer `briques/forge/forge/core/app/routers/recherche.py` :

```python
"""Router recherche documentaire hybride (S241). Monté /api, protégé.

Documents + base de connaissances de l'utilisateur courant : références exactes en tête,
plein texte et fautes de frappe (PostgreSQL), sens (Qdrant filtré par utilisateur), fusion RRF.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import UserContext, get_current_user
from app.recherche_service import SOURCES, rechercher

router = APIRouter()


@router.get("/recherche/hybride", dependencies=[Depends(get_current_user)])
async def recherche_hybride(q: str = "", limite: int = 10, sources: str | None = None,
                            user: UserContext = Depends(get_current_user)):
    """`sources` : liste séparée par des virgules parmi `document`, `kb` (défaut : les deux)."""
    choisies = (frozenset(x.strip() for x in sources.split(",") if x.strip()) & SOURCES
                if sources else SOURCES)
    return await rechercher(q, user.sub, limite, choisies)
```

Dans `briques/forge/forge/core/app/main.py`, à côté de l'import de `rag_router` (ligne ~55) :

```python
from app.routers.recherche import router as recherche_router  # S241 — recherche documentaire hybride
```

et à côté de `mount_both(rag_router, "/api")` (ligne ~207) :

```python
mount_both(recherche_router, "/api")  # S241 — GET /api/recherche/hybride
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_recherche.py`
Attendu : `8 passed`. Si `test_sans_authentification_refuse` reçoit autre chose que 401/403, lire `get_current_user` (`app/auth.py`) et ajuster l'assertion au code réellement renvoyé pour un appel sans jeton — mais jamais 200.

- [ ] **Step 6 : Commit**

```bash
git add briques/forge/forge/core/app/recherche_service.py briques/forge/forge/core/app/routers/recherche.py \
  briques/forge/forge/core/app/main.py briques/forge/forge/core/tests/test_s241_recherche.py
git commit -m "feat(S241): recherche hybride Forge (exacts, lexical, sens recoupé), mode lexical en panne"
```

---

### Task 6 : Forge — réconciliation PostgreSQL → Qdrant et reconstruction

**Files:**
- Create: `briques/forge/forge/core/app/reconciliation.py`
- Create: `briques/forge/forge/core/app/recherche_reindexer.py`
- Modify: `briques/forge/forge/core/app/main.py` (lifespan)
- Test: `briques/forge/forge/core/tests/test_s241_reconciliation.py`

**Interfaces:**
- Consumes : `memory.collection_active`, `memory.indexer_source`, `memory.delete_by_source`, `memory.chunk_text`, `memory.SOURCES_INDEXEES`, `memory.RechercheVectorielleIndisponible`, `memory.chercher_fragments` (Task 3).
- Produces :
  - `app.reconciliation.INTERVALLE = 600`, `LOT = 50`
  - `async app.reconciliation.reconcilier_index(lot: int = LOT) -> dict` → `{"revectorises": int, "orphelins_supprimes": int, "restants": int, "arret_sur_echec": bool}`
  - `async app.reconciliation.boucle_reconciliation(intervalle: float = INTERVALLE) -> None`
  - `async app.recherche_reindexer.principal(user_id: str | None = None) -> int` (code de sortie) ; `python -m app.recherche_reindexer [--user ID]`

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/forge/forge/core/tests/test_s241_reconciliation.py` :

```python
"""S241 — réconciliation : PostgreSQL fait foi, Qdrant se reconstruit."""
from sqlalchemy import text

from app import memory, recherche_reindexer
from app.reconciliation import reconcilier_index
from tests.s241_outils import (  # noqa: F401
    ajouter_article, ajouter_document, base, embedder_coupe, embedder_factice, integration,
)

pytestmark = integration
TEXTE = "Procès-verbal de réception des travaux de toiture, signé sans réserve."


async def _ids(user_id, q=TEXTE):
    return {f.source_id for f in await memory.chercher_fragments(q, user_id)}


async def test_rattrape_un_document_jamais_vectorise(base, embedder_factice):
    doc = await ajouter_document("alice", "PV", TEXTE)
    assert await _ids("alice") == set()
    bilan = await reconcilier_index()
    assert bilan["revectorises"] == 1 and bilan["restants"] == 0 and not bilan["arret_sur_echec"]
    assert await _ids("alice") == {str(doc)}


async def test_supprime_les_orphelins(base, embedder_factice):
    await memory.indexer_source(TEXTE, "33333333-3333-3333-3333-333333333333", "document", "alice", "fantôme")
    bilan = await reconcilier_index()
    assert bilan["orphelins_supprimes"] == 1
    assert await _ids("alice") == set()


async def test_corrige_un_fragment_mal_attribue(base, embedder_factice):
    doc = await ajouter_article("alice", "PV", TEXTE)
    await memory.indexer_source(TEXTE, str(doc), "kb_article", "bob", "PV")
    await reconcilier_index()
    assert await _ids("bob") == set() and await _ids("alice") == {str(doc)}


async def test_texte_trop_court_jamais_retente(base, embedder_factice):
    await ajouter_document("alice", "court", "ok")  # aucun fragment (< 20 caractères)
    assert (await reconcilier_index())["revectorises"] == 0


async def test_s_arrete_au_premier_echec(base, embedder_coupe):
    await ajouter_document("alice", "A", TEXTE)
    await ajouter_document("alice", "B", TEXTE + " Copie.")
    bilan = await reconcilier_index()
    assert bilan["arret_sur_echec"] is True and bilan["revectorises"] == 0 and bilan["restants"] == 2


async def test_respecte_la_taille_du_lot(base, embedder_factice):
    for i in range(3):
        await ajouter_document("alice", f"D{i}", f"{TEXTE} Exemplaire numéro {i}.")
    bilan = await reconcilier_index(lot=2)
    assert bilan["revectorises"] == 2 and bilan["restants"] == 1


async def test_reindexer_reconstruit_tout(base, embedder_factice):
    from app.db import engine
    doc = await ajouter_document("alice", "PV", TEXTE)
    await reconcilier_index()
    client = memory._client()
    await client.delete_collection("forge_local")
    assert await recherche_reindexer.principal() == 0
    assert await _ids("alice") == {str(doc)}
    async with engine.connect() as conn:  # rien n'a touché PostgreSQL
        assert (await conn.execute(text("SELECT count(*) FROM documents"))).scalar_one() == 1
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_reconciliation.py`
Attendu : `ModuleNotFoundError: No module named 'app.reconciliation'`.

- [ ] **Step 3 : Implémenter la réconciliation**

Créer `briques/forge/forge/core/app/reconciliation.py` :

```python
"""Réconciliation PostgreSQL → Qdrant (S241).

PostgreSQL fait foi ; Qdrant n'est qu'un index reconstructible. Les ingestions des routers
documents/kb partent en tâche de fond et ne sont jamais relancées en cas d'échec : cette
tâche, toutes les 10 minutes, revectorise ce qui manque ou est mal attribué et supprime les
fragments orphelins. Elle s'arrête au premier échec de l'embedder (reprise au passage suivant).
"""
from __future__ import annotations

import asyncio
import logging

from qdrant_client.http import models as qm
from sqlalchemy import text

from app import memory
from app.db import SessionLocal

logger = logging.getLogger(__name__)

INTERVALLE = 600
LOT = 50
# type de source Qdrant → (table, colonne du titre)
_TABLES = {"document": ("documents", "nom"), "kb_article": ("kb_articles", "titre")}


async def _points_indexes(nom: str) -> dict[str, set[str]]:
    """source_id → ensemble des user_id portés par ses fragments (types indexés seulement)."""
    client = memory._client()
    if not await client.collection_exists(nom):
        return {}
    filtre = qm.Filter(must=[qm.FieldCondition(
        key="source_type", match=qm.MatchAny(any=list(memory.SOURCES_INDEXEES)))])
    indexes: dict[str, set[str]] = {}
    decalage = None
    while True:
        points, decalage = await client.scroll(
            nom, scroll_filter=filtre, limit=256, offset=decalage,
            with_payload=["source_id", "user_id"], with_vectors=False,
        )
        for p in points:
            charge = p.payload or {}
            indexes.setdefault(str(charge.get("source_id")), set()).add(str(charge.get("user_id")))
        if decalage is None:
            return indexes


async def _sources() -> dict[str, tuple[str, str, str, str]]:
    """source_id → (source_type, user_id, titre, contenu) depuis PostgreSQL."""
    sources = {}
    async with SessionLocal() as s:
        for source_type, (table, titre) in _TABLES.items():
            lignes = await s.execute(text(f"SELECT id, user_id, {titre}, coalesce(contenu, '') FROM {table}"))
            for r in lignes.all():
                sources[str(r[0])] = (source_type, r[1], r[2] or "", r[3])
    return sources


async def reconcilier_index(lot: int = LOT) -> dict:
    _, nom = memory.collection_active()
    bilan = {"revectorises": 0, "orphelins_supprimes": 0, "restants": 0, "arret_sur_echec": False}
    try:
        indexes = await _points_indexes(nom)
    except Exception as e:  # noqa: BLE001 — Qdrant injoignable : on réessaiera
        logger.warning("[forge:reconciliation] Qdrant injoignable : %s", str(e)[:160])
        bilan["arret_sur_echec"] = True
        return bilan
    sources = await _sources()

    for source_id in [sid for sid in indexes if sid not in sources]:
        await memory.delete_by_source(source_id)
        bilan["orphelins_supprimes"] += 1

    a_faire = [sid for sid, (_, user_id, _, contenu) in sources.items()
               if memory.chunk_text(contenu) and indexes.get(sid) != {user_id}]
    for source_id in a_faire[:lot]:
        source_type, user_id, titre, contenu = sources[source_id]
        try:
            await memory.indexer_source(contenu, source_id, source_type, user_id, titre)
        except memory.RechercheVectorielleIndisponible as e:
            logger.warning("[forge:reconciliation] embedder indisponible, arrêt : %s", str(e)[:160])
            bilan["arret_sur_echec"] = True
            break
        bilan["revectorises"] += 1
    bilan["restants"] = len(a_faire) - bilan["revectorises"]
    logger.info("[forge:reconciliation] %s", bilan)
    return bilan


async def boucle_reconciliation(intervalle: float = INTERVALLE) -> None:
    while True:
        try:
            await reconcilier_index()
        except Exception as e:  # noqa: BLE001 — la boucle ne meurt jamais
            logger.warning("[forge:reconciliation] passage en échec : %s", str(e)[:160])
        await asyncio.sleep(intervalle)
```

- [ ] **Step 4 : Implémenter la commande de reconstruction**

Créer `briques/forge/forge/core/app/recherche_reindexer.py` :

```python
"""Reconstruction de l'index vectoriel de la recherche (S241) — commande d'exploitation.

La Forge n'a pas de rôle admin : pas de route HTTP. Usage dans le conteneur :
    docker exec forge-forge-1 python -m app.recherche_reindexer [--user <id>]
Vide les fragments (d'un utilisateur, ou tous les types indexés) de la collection active,
puis enchaîne la réconciliation jusqu'au bout. PostgreSQL n'est jamais modifié.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from qdrant_client.http import models as qm

from app import memory
from app.reconciliation import reconcilier_index


async def principal(user_id: str | None = None) -> int:
    _, nom = memory.collection_active()
    client = memory._client()
    if await client.collection_exists(nom):
        champ, valeur = (("user_id", qm.MatchValue(value=user_id)) if user_id
                         else ("source_type", qm.MatchAny(any=list(memory.SOURCES_INDEXEES))))
        await client.delete(nom, points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key=champ, match=valeur)])))
    total = 0
    while True:
        bilan = await reconcilier_index()
        total += bilan["revectorises"]
        if bilan["arret_sur_echec"]:
            print(f"✗ arrêt : embedder ou Qdrant indisponible ({total} source(s) revectorisée(s))")
            return 1
        if bilan["restants"] == 0:
            print(f"✓ {total} source(s) revectorisée(s) dans {nom}")
            return 0


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--user", default=None, help="ne reconstruire que cet utilisateur")
    sys.exit(asyncio.run(principal(analyseur.parse_args().user)))
```

- [ ] **Step 5 : Démarrer la boucle avec la Forge**

Dans `briques/forge/forge/core/app/main.py`, remplacer `lifespan` par (ajouter `import asyncio` et `import os` en tête s'ils manquent) :

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "[forge:core] up — backend forge UNIQUE (Bun supprimé S136), port=%s",
        settings.CORE_PY_PORT,
    )
    # S241 — réconciliation PostgreSQL → Qdrant (désactivable : FORGE_RECONCILIATION=0).
    from app.reconciliation import boucle_reconciliation
    tache = (asyncio.create_task(boucle_reconciliation())
             if os.environ.get("FORGE_RECONCILIATION", "1") != "0" else None)
    yield
    if tache is not None:
        tache.cancel()
    await db_dispose()
```

- [ ] **Step 6 : Lancer, vérifier le succès**

Run : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q tests/test_s241_reconciliation.py`
Attendu : `7 passed`.

Run (suite complète Forge core) : `scripts/en_docker.sh python -m pytest -p no:cacheprovider -q`
Attendu : aucun échec.

- [ ] **Step 7 : Commit**

```bash
git add briques/forge/forge/core/app/reconciliation.py briques/forge/forge/core/app/recherche_reindexer.py \
  briques/forge/forge/core/app/main.py briques/forge/forge/core/tests/test_s241_reconciliation.py
git commit -m "feat(S241): réconciliation PostgreSQL→Qdrant reprenable et commande de reconstruction"
```

---

### Task 7 : Adaptateur Forge — `GET /documents/chercher`

**Files:**
- Modify: `briques/forge/main.py` (après `rag_chercher`, ligne ~346)
- Test: `briques/forge/test_recherche_s241.py`

**Interfaces:**
- Consumes : route core `GET /api/recherche/hybride` (Task 5) ; `_appel_protege`, `_json_ou_erreur`, `_client`, `_JETON_UTILISATEUR` (existants dans `briques/forge/main.py`).
- Produces : `GET /documents/chercher?q=&limite=&sources=` → `{"mode": str, "resultats": list, "identite": "utilisateur" | "service"}`. **Pas** de capacité au manifeste (raison dans la spec).

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/forge/test_recherche_s241.py` :

```python
"""S241 — proxy de recherche de l'adaptateur Forge (aucun réseau)."""
import pytest
from fastapi.testclient import TestClient

import main


class _Reponse:
    status_code = 200

    def json(self):
        return {"mode": "lexical", "resultats": [{"id": "d1", "source": "document"}]}


@pytest.fixture
def appels(monkeypatch):
    vus = []

    async def _faux(client, methode, chemin, **kw):
        vus.append((methode, chemin, kw.get("params"), main._JETON_UTILISATEUR.get()))
        return _Reponse()

    monkeypatch.setattr(main, "_appel_protege", _faux)
    return vus


def test_relaie_vers_la_recherche_hybride(appels):
    r = TestClient(main.app).get("/documents/chercher", params={"q": " toiture ", "limite": 500})
    assert r.status_code == 200
    assert r.json() == {"mode": "lexical", "resultats": [{"id": "d1", "source": "document"}],
                        "identite": "service"}
    assert appels == [("GET", "/api/recherche/hybride", {"q": "toiture", "limite": 50}, None)]


def test_identite_utilisateur_quand_un_jeton_est_fourni(appels):
    r = TestClient(main.app).get("/documents/chercher", params={"q": "x", "sources": "kb"},
                                 headers={"X-Forge-User-Token": "Bearer JWT-A"})
    assert r.json()["identite"] == "utilisateur"
    assert appels[0][2] == {"q": "x", "limite": 10, "sources": "kb"} and appels[0][3] == "JWT-A"


def test_requete_vide_refusee(appels):
    assert TestClient(main.app).get("/documents/chercher", params={"q": "  "}).status_code == 422
    assert appels == []
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `cd /Users/garinat_t/Desktop/Workplace && scripts/tests_briques.sh forge 2>&1 | tail -15`
Attendu : les 3 tests de `test_recherche_s241.py` échouent (404).

- [ ] **Step 3 : Implémenter**

Dans `briques/forge/main.py`, juste après la fonction `rag_chercher` :

```python
@app.get("/documents/chercher", summary="Recherche hybride dans les documents et la base de connaissances (S241)")
async def documents_chercher(q: str = "", limite: int = 10, sources: str | None = None):
    """Proxy authentifié → `GET /api/recherche/hybride`. Lecture seule.

    Volontairement ABSENT du manifeste : l'assistant a déjà `forge_rag_chercher` (Forge seule)
    et `chercher_documents` (toutes sources, via le Cœur) — une troisième capacité jumelle
    brouillerait son choix. `identite` dit au Cœur si la Forge a cherché pour l'utilisateur
    réel (jeton propagé) ou sous l'identité de service unique (résultats partagés)."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(422, "Paramètre requis : 'q' (les termes recherchés).")
    params: dict = {"q": q, "limite": min(max(limite, 1), 50)}
    if sources:
        params["sources"] = sources
    async with await _client(timeout=20) as client:
        r = await _appel_protege(client, "GET", "/api/recherche/hybride", params=params)
    data = _json_ou_erreur(r)
    return {
        "mode": data.get("mode", "hybride"),
        "resultats": data.get("resultats", []),
        "identite": "utilisateur" if _JETON_UTILISATEUR.get() else "service",
    }
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `scripts/tests_briques.sh forge 2>&1 | tail -15`
Attendu : forge au vert, les 3 nouveaux tests passent. Vérifier aussi le filet du contrat manifeste ↔ route : `cd /Users/garinat_t/Desktop/Workplace && python3 -m pytest -q tests/test_contrat_capacites.py`. Attendu : vert.

- [ ] **Step 5 : Commit**

```bash
git add briques/forge/main.py briques/forge/test_recherche_s241.py
git commit -m "feat(S241): adaptateur Forge, route de recherche hybride avec identité signalée"
```

---

### Task 8 : Ingestion — index FTS5 et `GET /recherche`

**Files:**
- Create: `briques/ingestion/recherche.py`
- Modify: `briques/ingestion/stockage.py`
- Modify: `briques/ingestion/main.py`
- Test: `briques/ingestion/test_recherche_s241.py`

**Interfaces:**
- Produces :
  - `recherche.normaliser(texte: str) -> str`
  - `recherche.creer_tables(con)`, `indexer(con, doc_id)`, `desindexer(con, doc_id)`, `reconstruire_index(con) -> int`, `index_desynchronise(con) -> bool`
  - `recherche.chercher(con, requete: str, limite: int = 10) -> list[dict]` → `[{"id", "source": "ingestion", "titre", "extrait", "rang", "exact"}]`
  - `stockage.chercher(requete: str, limite: int = 10) -> list[dict]`
  - Route `GET /recherche?q=&limite=` (clé de service) → `{"mode": "lexical", "resultats": [...]}`

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `briques/ingestion/test_recherche_s241.py` :

```python
"""S241 — recherche plein texte de la brique ingestion (SQLite FTS5)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    stockage.initialiser()
    from main import app
    with TestClient(app) as c:
        yield c


def _importer(client, nom, texte):
    return client.post("/documents/import", json={"nom": nom, "texte_extrait": texte}).json()["id"]


def _ids(client, q):
    r = client.get("/recherche", params={"q": q})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "lexical"
    return [x["id"] for x in r.json()["resultats"]]


def test_tokeniseur_trigram_disponible():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")


def test_sans_accents_ni_casse(client):
    d = _importer(client, "Évaluation", "Rapport ÉNERGÉTIQUE de la maison.")
    assert _ids(client, "energetique") == [d]
    assert _ids(client, "EVALUATION") == [d]


def test_faute_de_frappe(client):
    d = _importer(client, "Devis", "Réfection de la toiture.")
    _importer(client, "Autre", "Plomberie de la cuisine.")
    assert _ids(client, "toiturre") == [d]


def test_reference_exacte_en_tete(client):
    cible = _importer(client, "Relance", "La facture FAC-2026-0042 reste impayée.")
    _importer(client, "Factures", "Facture facture facture de mars, FAC-2026-00421.")
    r = client.get("/recherche", params={"q": "facture FAC-2026-0042"}).json()["resultats"]
    assert r[0]["id"] == cible and r[0]["exact"] is True
    assert all(x["exact"] is False for x in r[1:])


def test_classement_indexe_et_suppression_propagee(client):
    import stockage
    d = _importer(client, "Doc", "Texte neutre sans mot-clé.")
    client.patch(f"/documents/{d}/classement", json={"projet": "Chantier Martin", "tags": ["urgent"]})
    assert _ids(client, "martin") == [d]
    assert stockage.supprimer(d) is True
    assert _ids(client, "martin") == []


def test_reconstruction_de_l_index(client):
    import stockage
    d = _importer(client, "Contrat", "Contrat de maintenance annuelle.")
    with stockage._conn() as con:
        con.execute("DELETE FROM documents_recherche")
        con.execute("DELETE FROM documents_trigrammes")
    assert _ids(client, "maintenance") == []
    stockage.initialiser()  # détecte la désynchronisation et reconstruit
    assert _ids(client, "maintenance") == [d]


def test_requete_vide_refusee(client):
    assert client.get("/recherche", params={"q": " "}).status_code == 422
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `cd /Users/garinat_t/Desktop/Workplace && scripts/tests_briques.sh ingestion 2>&1 | tail -15`
Attendu : échecs (route `/recherche` absente → 404).

- [ ] **Step 3 : Implémenter le module de recherche**

Créer `briques/ingestion/recherche.py` :

```python
"""Recherche plein texte de la brique ingestion (S241) — SQLite FTS5, sans dépendance.

Deux tables FTS5, tenues à jour DANS LA MÊME TRANSACTION que chaque écriture de
`stockage.py` : `documents_recherche` (mots, tokeniseur unicode61) et `documents_trigrammes`
(trigrammes, filet des fautes de frappe). Le texte y est déjà normalisé (minuscules, sans
accents) : la requête suit la même normalisation.

Ordre des résultats : références exactes (codes, numéros, expressions entre guillemets),
puis plein texte (bm25), puis — seulement si le plein texte ne trouve rien — trigrammes.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata

PLAFOND = 200_000
SEUIL_TRIGRAMMES = 0.4
LONGUEUR_EXTRAIT = 280
TERMES_MAX = 32
LIMITE_MAX = 50

_GUILLEMETS = re.compile(r'"([^"]+)"|«\s*([^»]+?)\s*»|“([^”]+)”')
_CARACTERES_REFERENCE = set("-_./@#")
_BORDS = ".,;:!?()[]{}'\"«»“”…"


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def creer_tables(con: sqlite3.Connection) -> None:
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_recherche USING fts5("
                "doc_id UNINDEXED, nom, texte, tokenize='unicode61 remove_diacritics 2')")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_trigrammes USING fts5("
                "doc_id UNINDEXED, texte, tokenize='trigram')")


def _texte_indexe(ligne) -> tuple[str, str]:
    meta = json.loads(ligne["metadonnees"] or "{}")
    c = meta.get("classement") or {}
    morceaux = [ligne["texte_extrait"] or "", c.get("categorie") or "", " ".join(c.get("tags") or []),
                c.get("projet") or "", c.get("resume") or "", c.get("entreprise_nom") or ""]
    return normaliser(ligne["nom"] or ""), normaliser(" ".join(m for m in morceaux if m))[:PLAFOND]


def desindexer(con: sqlite3.Connection, doc_id: str) -> None:
    con.execute("DELETE FROM documents_recherche WHERE doc_id = ?", (doc_id,))
    con.execute("DELETE FROM documents_trigrammes WHERE doc_id = ?", (doc_id,))


def indexer(con: sqlite3.Connection, doc_id: str) -> None:
    desindexer(con, doc_id)
    ligne = con.execute("SELECT nom, texte_extrait, metadonnees FROM documents WHERE id = ?",
                        (doc_id,)).fetchone()
    if ligne is None:
        return
    nom, texte = _texte_indexe(ligne)
    con.execute("INSERT INTO documents_recherche (doc_id, nom, texte) VALUES (?, ?, ?)", (doc_id, nom, texte))
    con.execute("INSERT INTO documents_trigrammes (doc_id, texte) VALUES (?, ?)", (doc_id, f"{nom} {texte}"))


def reconstruire_index(con: sqlite3.Connection) -> int:
    con.execute("DELETE FROM documents_recherche")
    con.execute("DELETE FROM documents_trigrammes")
    ids = [r[0] for r in con.execute("SELECT id FROM documents").fetchall()]
    for doc_id in ids:
        indexer(con, doc_id)
    return len(ids)


def index_desynchronise(con: sqlite3.Connection) -> bool:
    n = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("documents", "documents_recherche", "documents_trigrammes")]
    return not (n[0] == n[1] == n[2])


# ── Recherche ───────────────────────────────────────────────────────────────────

def _est_reference(jeton: str) -> bool:
    return (len(jeton) >= 2 and any(c.isalnum() for c in jeton)
            and (any(c.isdigit() for c in jeton) or any(c in _CARACTERES_REFERENCE for c in jeton)))


def extraire_references(requete: str) -> list[str]:
    """Mêmes règles que la Mémoire (S238) et la Forge (S241)."""
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
    return references[:10]


def _motif(reference_normalisee: str) -> str:
    morceaux = [re.escape(m) for m in reference_normalisee.split()]
    return r"(?<![a-z0-9])" + r"\s+".join(morceaux) + r"(?![a-z0-9])"


def _regexp(motif: str, texte: str | None) -> bool:
    return texte is not None and re.search(motif, texte) is not None


def _termes(requete: str) -> list[str]:
    return re.findall(r"[^\W_]+", normaliser(requete))[:TERMES_MAX]


def _expression_fts(jetons: list[str]) -> str:
    return " OR ".join('"' + j.replace('"', '""') + '"' for j in jetons)


def _trigrammes_de(mot: str) -> set[str]:
    return {mot[i:i + 3] for i in range(len(mot) - 2)}


def _exacts(con, requete: str) -> list[str]:
    trouves: dict[str, tuple[int, bool]] = {}
    for reference in (normaliser(r) for r in extraire_references(requete)):
        motif = _motif(reference)
        for doc_id, nom in con.execute(
            "SELECT doc_id, nom FROM documents_recherche WHERE (nom || ' ' || texte) REGEXP ?", (motif,)
        ).fetchall():
            n, titre = trouves.get(doc_id, (0, False))
            trouves[doc_id] = (n + 1, titre or re.search(motif, nom) is not None)
    return sorted(trouves, key=lambda d: (-trouves[d][0], not trouves[d][1], d))


def _plein_texte(con, mots: list[str], limite: int) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT doc_id FROM documents_recherche WHERE documents_recherche MATCH ? "
        "ORDER BY bm25(documents_recherche, 0.0, 5.0, 1.0), doc_id LIMIT ?",
        (_expression_fts(mots), limite)).fetchall()]


def _par_trigrammes(con, mots: list[str], limite: int) -> list[str]:
    longs = [m for m in mots if len(m) >= 3]
    if not longs:
        return []
    tous = sorted(set().union(*(_trigrammes_de(m) for m in longs)))
    candidats = con.execute(
        "SELECT doc_id, texte FROM documents_trigrammes WHERE documents_trigrammes MATCH ? "
        "ORDER BY bm25(documents_trigrammes) LIMIT ?", (_expression_fts(tous), limite * 4)).fetchall()
    gardes = []
    for doc_id, texte in candidats:
        # Part des trigrammes du mot le mieux retrouvé (proche de word_similarity, S238).
        part = max(sum(1 for t in _trigrammes_de(m) if t in texte) / len(_trigrammes_de(m)) for m in longs)
        if part >= SEUIL_TRIGRAMMES:
            gardes.append((part, doc_id))
    gardes.sort(key=lambda x: (-x[0], x[1]))
    return [d for _, d in gardes][:limite]


def _extrait(texte: str, mots: list[str]) -> str:
    texte = " ".join((texte or "").split())
    if len(texte) <= LONGUEUR_EXTRAIT:
        return texte
    normalise = normaliser(texte)
    positions = [p for p in (normalise.find(m) for m in mots) if p >= 0]
    debut = max(0, min(positions) - LONGUEUR_EXTRAIT // 3) if positions else 0
    debut = min(debut, len(texte) - LONGUEUR_EXTRAIT)
    return (("…" if debut > 0 else "") + texte[debut:debut + LONGUEUR_EXTRAIT]
            + ("…" if debut + LONGUEUR_EXTRAIT < len(texte) else ""))


def chercher(con: sqlite3.Connection, requete: str, limite: int = 10) -> list[dict]:
    requete = (requete or "").strip()
    if not requete:
        return []
    limite = min(max(int(limite), 1), LIMITE_MAX)
    con.create_function("regexp", 2, _regexp, deterministic=True)
    exacts = _exacts(con, requete)
    mots = _termes(requete)
    lexical: list[str] = []
    if mots:
        lexical = _plein_texte(con, mots, limite * 3) or _par_trigrammes(con, mots, limite * 3)
    ordre = exacts + [d for d in lexical if d not in exacts]
    resultats = []
    for doc_id in ordre[:limite]:
        ligne = con.execute("SELECT nom, texte_extrait FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if ligne is None:
            continue
        resultats.append({"id": doc_id, "source": "ingestion", "titre": ligne["nom"],
                          "extrait": _extrait(ligne["texte_extrait"] or "", mots),
                          "rang": len(resultats) + 1, "exact": doc_id in exacts})
    return resultats
```

- [ ] **Step 4 : Tenir l'index à jour dans `stockage.py`**

Dans `briques/ingestion/stockage.py` :

a) ajouter `import recherche` après les imports existants ;

b) dans `initialiser()`, après `_migrer_colonne_venture_id(con)` :

```python
        # S241 — index de recherche FTS5. Reconstruit s'il ne correspond plus aux documents
        # (base antérieure à S241, ou écriture faite hors de ce module).
        recherche.creer_tables(con)
        if recherche.index_desynchronise(con):
            recherche.reconstruire_index(con)
```

c) dans `sauvegarder()` et `importer()`, après le `con.execute("""INSERT ...""", (...))`, toujours dans le bloc `with _conn() as con:` :

```python
        recherche.indexer(con, doc_id)
```

d) dans `classer()`, après le `con.execute("UPDATE documents SET metadonnees = ? ...")` :

```python
        recherche.indexer(con, doc_id)
```

e) remplacer `supprimer()` par :

```python
def supprimer(doc_id: str) -> bool:
    with _conn() as con:
        recherche.desindexer(con, doc_id)
        nb = con.execute("DELETE FROM documents WHERE id = ?", (doc_id,)).rowcount
    return nb > 0
```

f) ajouter à la fin du fichier :

```python
def chercher(requete: str, limite: int = 10) -> list[dict]:
    """Recherche plein texte (S241) : références exactes, mots, fautes de frappe."""
    with _conn() as con:
        return recherche.chercher(con, requete, limite)
```

- [ ] **Step 5 : Ajouter la route dans `main.py`**

Dans `briques/ingestion/main.py`, après la route `GET /dossiers` :

```python
@app.get("/recherche", summary="Rechercher dans les documents ingérés (références exactes, mots, fautes de frappe)")
def rechercher(q: str = "", limite: int = 10, _cle: str = Depends(cle_api)):
    """S241 — appelée par la recherche unifiée du Cœur (outil `chercher_documents`, onglet
    Recherche). Pas de capacité au manifeste : le Cœur la câble lui-même."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(422, "Paramètre requis : 'q' (les termes recherchés).")
    return {"mode": "lexical", "resultats": stockage.chercher(q, limite)}
```

(Vérifier que `HTTPException` est déjà importé depuis `fastapi` en tête de `main.py` ; sinon l'ajouter à l'import existant.)

- [ ] **Step 6 : Lancer, vérifier le succès**

Run : `cd /Users/garinat_t/Desktop/Workplace && scripts/tests_briques.sh ingestion 2>&1 | tail -15`
Attendu : ingestion au vert, les 7 nouveaux tests passent, aucun test existant cassé.

- [ ] **Step 7 : Commit**

```bash
git add briques/ingestion/recherche.py briques/ingestion/stockage.py briques/ingestion/main.py \
  briques/ingestion/test_recherche_s241.py
git commit -m "feat(S241): recherche plein texte de la brique ingestion (FTS5, fautes de frappe, références exactes)"
```

---

### Task 9 : Cœur — service de recherche unifiée

**Files:**
- Create: `core/recherche_unifiee.py`
- Test: `core/test_recherche_unifiee.py`

**Interfaces:**
- Consumes : `orchestrateur._brique_base(registre, nom)`, `outils_communs._entetes_brique`, `outils_communs.entetes_forge_sortants` (existants) ; routes `forge:/documents/chercher` (Task 7), `ingestion:/recherche` (Task 8), `memoire:/rappeler` (existante).
- Produces (`recherche_unifiee`) :
  - `K_RRF = 60`, `DELAI_SOURCE = 8.0`, `SOURCES = ("forge", "ingestion", "memoire")`, `ESPACES_MEMOIRE = ("perso", "solution", "veille")`
  - `class ToutesSourcesIndisponibles(Exception)` — `args[0]` = liste des sources
  - `async rechercher(q: str, registre, limite: int = 10, sources: set[str] | None = None, transport=None) -> dict` → `{"resultats": [{"source", "id", "titre", "extrait", "partage", "exact"}], "modes": {nom: mode}, "sources_indisponibles": [noms]}` ; noms de sous-sources : `forge`, `ingestion`, `memoire-perso`, `memoire-solution`, `memoire-veille`

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `core/test_recherche_unifiee.py` :

```python
"""S241 — recherche unifiée du Cœur : fan-out, délais, fusion, identité.

$ cd core && python3 -m pytest test_recherche_unifiee.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import httpx  # noqa: E402
import pytest  # noqa: E402

import contexte_tenant  # noqa: E402
import recherche_unifiee as ru  # noqa: E402


@pytest.fixture(autouse=True)
def _bases(monkeypatch):
    monkeypatch.setattr(ru.orchestrateur, "_brique_base", lambda registre, nom: f"http://{nom}")


def _reponses(pannes=(), lents=(), forge_identite="service"):
    vus = []

    async def gerer(requete: httpx.Request):
        hote = requete.url.host
        vus.append(requete)
        if hote in lents:
            await asyncio.sleep(1)
        if hote in pannes:
            raise httpx.ConnectError("hors ligne", request=requete)
        if hote == "forge":
            return httpx.Response(200, json={"mode": "hybride", "identite": forge_identite, "resultats": [
                {"id": "f1", "source": "document", "titre": "Devis toiture", "extrait": "…", "exact": False},
                {"id": "k1", "source": "kb", "titre": "Procédure", "extrait": "…", "exact": False}]})
        if hote == "ingestion":
            return httpx.Response(200, json={"mode": "lexical", "resultats": [
                {"id": "i1", "source": "ingestion", "titre": "FAC-1", "extrait": "…", "exact": True}]})
        espace = requete.url.params["espace"]
        return httpx.Response(200, json={"mode": "hybride", "souvenirs": [
            {"id": f"m-{espace}", "titre": f"Souvenir {espace}", "extrait": "…", "correspondance": "lexicale"}]})

    return httpx.MockTransport(gerer), vus


def _lancer(transport, **kw):
    return asyncio.run(ru.rechercher("toiture FAC-1", registre=None, transport=transport, **kw))


def test_fusion_exacts_devant_et_toutes_les_sources():
    transport, _ = _reponses()
    rep = _lancer(transport)
    assert rep["resultats"][0]["id"] == "i1" and rep["resultats"][0]["exact"] is True
    assert {r["source"] for r in rep["resultats"]} == {
        "forge-document", "forge-kb", "ingestion", "memoire-perso", "memoire-solution", "memoire-veille"}
    assert rep["sources_indisponibles"] == []
    assert rep["modes"]["ingestion"] == "lexical" and rep["modes"]["forge"] == "hybride"


def test_partage_signale():
    transport, _ = _reponses(forge_identite="service")
    rep = _lancer(transport)
    par_source = {r["source"]: r["partage"] for r in rep["resultats"]}
    assert par_source["forge-document"] is True and par_source["ingestion"] is True
    assert par_source["memoire-perso"] is False
    transport, _ = _reponses(forge_identite="utilisateur")
    assert {r["partage"] for r in _lancer(transport)["resultats"] if r["source"].startswith("forge")} == {False}


def test_source_en_panne_signalee_les_autres_repondent():
    transport, _ = _reponses(pannes=("forge",))
    rep = _lancer(transport)
    assert rep["sources_indisponibles"] == ["forge"]
    assert rep["resultats"] and not any(r["source"].startswith("forge") for r in rep["resultats"])


def test_source_trop_lente_signalee(monkeypatch):
    monkeypatch.setattr(ru, "DELAI_SOURCE", 0.05)
    transport, _ = _reponses(lents=("ingestion",))
    assert _lancer(transport)["sources_indisponibles"] == ["ingestion"]


def test_toutes_en_panne_leve():
    transport, _ = _reponses(pannes=("forge", "ingestion", "memoire"))
    with pytest.raises(ru.ToutesSourcesIndisponibles):
        _lancer(transport)


def test_filtre_sources_et_requete_vide():
    transport, vus = _reponses()
    rep = _lancer(transport, sources={"memoire"})
    assert {r.url.host for r in vus} == {"memoire"}
    assert all(r["source"].startswith("memoire") for r in rep["resultats"])
    assert asyncio.run(ru.rechercher("  ", registre=None, transport=transport)) == {
        "resultats": [], "modes": {}, "sources_indisponibles": []}


def test_identite_transmise(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    transport, vus = _reponses()

    async def scenario():
        contexte_tenant.definir_contexte(utilisateur="marina", user_token="JWT-M")
        return await ru.rechercher("toiture", registre=None, transport=transport)

    asyncio.run(scenario())
    forge = next(r for r in vus if r.url.host == "forge")
    memoire = [r for r in vus if r.url.host == "memoire"]
    assert forge.headers["X-Forge-User-Token"] == "Bearer JWT-M"
    assert {r.headers["X-User-Id"] for r in memoire} == {"marina"}
    assert {r.url.params["espace"] for r in memoire} == {"perso", "solution", "veille"}
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `cd /Users/garinat_t/Desktop/Workplace && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest -q core/test_recherche_unifiee.py`
Attendu : `ModuleNotFoundError: No module named 'recherche_unifiee'`.

- [ ] **Step 3 : Implémenter**

Créer `core/recherche_unifiee.py` :

```python
"""Recherche unifiée du Cœur (S241) : Forge + Ingestion + Mémoire, fusionnées par rang.

Chaque brique cherche dans sa propre base (qui fait foi) avec l'identité de l'appelant ; le
Cœur ne fait que fusionner (RRF, références exactes devant). Aucune source n'est
indispensable : une source en panne ou trop lente est signalée dans
`sources_indisponibles` et les autres répondent quand même. Si TOUTES échouent, on lève
`ToutesSourcesIndisponibles` — jamais une liste vide présentée comme un succès.

`partage` : vrai pour Ingestion (une seule clé de service, aucune isolation par personne) et
pour la Forge quand elle a cherché sous son identité de service (pas de jeton utilisateur).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

import orchestrateur
from outils_communs import _entetes_brique, entetes_forge_sortants

logger = logging.getLogger(__name__)

K_RRF = 60
DELAI_SOURCE = 8.0
LIMITE_MAX = 50
SOURCES = ("forge", "ingestion", "memoire")
ESPACES_MEMOIRE = ("perso", "solution", "veille")


class ToutesSourcesIndisponibles(Exception):
    """Aucune source n'a répondu ; `args[0]` = la liste des sources tentées."""


@dataclass
class _Liste:
    nom: str
    mode: str
    resultats: list[dict]


def _resultat(source: str, x: dict, partage: bool, exact: bool) -> dict:
    return {"source": source, "id": str(x.get("id") or ""), "titre": x.get("titre") or "",
            "extrait": x.get("extrait") or "", "partage": partage, "exact": exact}


async def _forge(client: httpx.AsyncClient, registre, q: str, n: int) -> _Liste:
    base = orchestrateur._brique_base(registre, "forge")
    r = await client.get(f"{base}/documents/chercher", params={"q": q, "limite": n},
                         headers=entetes_forge_sortants())
    r.raise_for_status()
    d = r.json()
    partage = d.get("identite") != "utilisateur"
    return _Liste("forge", d.get("mode", "hybride"), [
        _resultat("forge-kb" if x.get("source") == "kb" else "forge-document", x, partage, bool(x.get("exact")))
        for x in d.get("resultats", [])])


async def _ingestion(client: httpx.AsyncClient, registre, q: str, n: int) -> _Liste:
    base = orchestrateur._brique_base(registre, "ingestion")
    r = await client.get(f"{base}/recherche", params={"q": q, "limite": n},
                         headers=_entetes_brique("ingestion"))
    r.raise_for_status()
    d = r.json()
    return _Liste("ingestion", d.get("mode", "lexical"), [
        _resultat("ingestion", x, True, bool(x.get("exact"))) for x in d.get("resultats", [])])


async def _memoire(client: httpx.AsyncClient, registre, q: str, n: int, espace: str) -> _Liste:
    base = orchestrateur._brique_base(registre, "memoire")
    r = await client.get(f"{base}/rappeler", params={"q": q, "limite": n, "espace": espace},
                         headers=_entetes_brique("memoire"))
    r.raise_for_status()
    d = r.json()
    return _Liste(f"memoire-{espace}", d.get("mode", "hybride"), [
        _resultat(f"memoire-{espace}", x, False, x.get("correspondance") == "exacte")
        for x in d.get("souvenirs", [])])


def fusionner(listes: list[_Liste], limite: int) -> list[dict]:
    """RRF sur les classements de chaque sous-source ; +1 pour une référence exacte (un score
    RRF vaut au plus 1/(K+1) par liste, donc un exact passe toujours devant)."""
    scores: dict[tuple[str, str], float] = {}
    fiches: dict[tuple[str, str], dict] = {}
    for liste in listes:
        for rang, x in enumerate(liste.resultats, start=1):
            cle = (x["source"], x["id"])
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (K_RRF + rang) + (1.0 if x["exact"] else 0.0)
            fiches.setdefault(cle, x)
    ordre = sorted(scores, key=lambda c: (-scores[c], c[0], c[1]))[:limite]
    return [fiches[c] for c in ordre]


async def rechercher(q: str, registre, limite: int = 10, sources: set[str] | None = None,
                     transport=None) -> dict:
    q = (q or "").strip()
    if not q:
        return {"resultats": [], "modes": {}, "sources_indisponibles": []}
    limite = min(max(int(limite), 1), LIMITE_MAX)
    voulues = [s for s in SOURCES if not sources or s in sources]
    async with httpx.AsyncClient(timeout=DELAI_SOURCE, transport=transport) as client:
        appels: dict = {}
        if "forge" in voulues:
            appels["forge"] = _forge(client, registre, q, limite)
        if "ingestion" in voulues:
            appels["ingestion"] = _ingestion(client, registre, q, limite)
        if "memoire" in voulues:
            for espace in ESPACES_MEMOIRE:
                appels[f"memoire-{espace}"] = _memoire(client, registre, q, limite, espace)
        reponses = await asyncio.gather(
            *(asyncio.wait_for(appel, DELAI_SOURCE) for appel in appels.values()), return_exceptions=True)
    listes, indisponibles = [], []
    for nom, reponse in zip(appels, reponses):
        if isinstance(reponse, BaseException):
            logger.warning("[recherche] source %s indisponible : %s", nom, str(reponse)[:160] or type(reponse).__name__)
            indisponibles.append(nom)
        else:
            listes.append(reponse)
    if appels and not listes:
        raise ToutesSourcesIndisponibles(indisponibles)
    # Une brique entière en panne apparaît une fois (« memoire »), pas une fois par espace.
    if all(f"memoire-{e}" in indisponibles for e in ESPACES_MEMOIRE):
        indisponibles = [n for n in indisponibles if not n.startswith("memoire-")] + ["memoire"]
    return {"resultats": fusionner(listes, limite), "modes": {l.nom: l.mode for l in listes},
            "sources_indisponibles": indisponibles}
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest -q core/test_recherche_unifiee.py`
Attendu : `7 passed`. (`test_toutes_en_panne_leve` passe par le regroupement « memoire » ; `test_source_en_panne_signalee_les_autres_repondent` attend exactement `["forge"]`.)

- [ ] **Step 5 : Commit**

```bash
git add core/recherche_unifiee.py core/test_recherche_unifiee.py
git commit -m "feat(S241): recherche unifiée du Cœur (Forge, Ingestion, Mémoire), sources en panne signalées"
```

---

### Task 10 : Cœur — route `/recherche` et outil `chercher_documents`

**Files:**
- Create: `core/routers/recherche.py`
- Modify: `core/main.py` (import + `include_router`)
- Modify: `core/outils_domaines/documents.py`, `core/outils.py`, `core/assistant.py`
- Modify: `core/test_cerveau_admin.py` (`ROUTES_SESSION`)
- Test: `core/test_recherche_route.py`

**Interfaces:**
- Consumes : `recherche_unifiee.rechercher`, `ToutesSourcesIndisponibles` (Task 9) ; `auth.exiger_session_api`, `contexte_tenant.lire_contexte_tenant` (existants).
- Produces : `GET /recherche?q=&limite=&sources=` (401 sans session, 503 si toutes les sources échouent) ; outil `chercher_documents` : avec `q` → recherche unifiée (JSON du service), sans `q` → listage d'origine.

- [ ] **Step 1 : Écrire les tests (en échec)**

Créer `core/test_recherche_route.py` :

```python
"""S241 — route /recherche du Cœur et outil chercher_documents.

$ cd core && python3 -m pytest test_recherche_route.py -v
"""
import asyncio
import json
import os
import tempfile
import time

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import recherche_unifiee  # noqa: E402
import session_registre  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    ancien = session_registre.DB
    session_registre.DB = os.path.join(tempfile.mkdtemp(), "session_registre.db")
    auth._cache_access_token.clear()
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    yield
    session_registre.DB = ancien
    auth._cache_access_token.clear()


def _cookie(sub):
    auth._cache_access_token[sub] = ("at-cache", time.time() + 60)
    return {auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": sub, "refresh_token": "rt-1"})}


def test_sans_session_401():
    assert client.get("/recherche", params={"q": "x"}).status_code == 401


def test_avec_session_relaie_au_service(monkeypatch):
    vus = {}

    async def _faux(q, registre, limite=10, sources=None, transport=None):
        vus.update(q=q, limite=limite, sources=sources)
        return {"resultats": [], "modes": {}, "sources_indisponibles": ["forge"]}

    monkeypatch.setattr(recherche_unifiee, "rechercher", _faux)
    r = client.get("/recherche", params={"q": "toiture", "limite": 5, "sources": "forge,memoire"},
                   cookies=_cookie("marina"))
    assert r.status_code == 200 and r.json()["sources_indisponibles"] == ["forge"]
    assert vus == {"q": "toiture", "limite": 5, "sources": {"forge", "memoire"}}


def test_toutes_sources_en_panne_503(monkeypatch):
    async def _panne(*a, **k):
        raise recherche_unifiee.ToutesSourcesIndisponibles(["forge", "ingestion", "memoire"])

    monkeypatch.setattr(recherche_unifiee, "rechercher", _panne)
    r = client.get("/recherche", params={"q": "x"}, cookies=_cookie("marina"))
    assert r.status_code == 503


def test_outil_avec_q_passe_par_la_recherche_unifiee(monkeypatch):
    import outils_domaines.documents as documents

    async def _faux(q, registre, limite=10, sources=None, transport=None):
        return {"resultats": [{"source": "ingestion", "id": "i1"}], "modes": {}, "sources_indisponibles": []}

    monkeypatch.setattr(recherche_unifiee, "rechercher", _faux)
    sortie = asyncio.run(documents.dispatch("chercher_documents", {"q": "toiture"}, None, None))
    assert json.loads(sortie)["resultats"][0]["id"] == "i1"


def test_outil_toutes_sources_en_panne_message_clair(monkeypatch):
    import outils_domaines.documents as documents

    async def _panne(*a, **k):
        raise recherche_unifiee.ToutesSourcesIndisponibles(["forge"])

    monkeypatch.setattr(recherche_unifiee, "rechercher", _panne)
    sortie = json.loads(asyncio.run(documents.dispatch("chercher_documents", {"q": "x"}, None, None)))
    assert sortie["ok"] is False and "indisponible" in sortie["message"]
```

Dans `core/test_cerveau_admin.py`, ajouter `("GET", "/recherche")` à `ROUTES_SESSION` :

```python
ROUTES_SESSION = {
    ("POST", "/assistant/projets"), ("PATCH", "/assistant/projets/{projet_id}"),
    ("DELETE", "/assistant/projets/{projet_id}"), ("POST", "/assistant/document"),
    ("POST", "/profil"), ("PATCH", "/profil/identite"),
    ("GET", "/recherche"),  # S241 — recherche unifiée, session obligatoire
}
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `cd /Users/garinat_t/Desktop/Workplace && VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest -q core/test_recherche_route.py core/test_cerveau_admin.py`
Attendu : 404 sur `/recherche`, `test_routes_session_exactement` en échec, outil sans branche `q`.

- [ ] **Step 3 : Implémenter la route**

Créer `core/routers/recherche.py` :

```python
"""Route « recherche » du Cœur (S241) : recherche unifiée Forge + Ingestion + Mémoire.

Session obligatoire (401 sinon, appelée en `fetch` par l'onglet Recherche du tableau de
bord). Monté avec `lire_contexte_tenant` : l'identité de la session part vers la Mémoire
(X-User-Id) et, s'il y en a un, le jeton utilisateur vers la Forge.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import auth
import recherche_unifiee
from etat import registre

router = APIRouter()


@router.get("/recherche", tags=["recherche"], dependencies=[Depends(auth.exiger_session_api)])
async def recherche(q: str = "", limite: int = 10, sources: str | None = None):
    """`sources` : liste séparée par des virgules parmi `forge`, `ingestion`, `memoire`."""
    choisies = {s.strip() for s in sources.split(",") if s.strip()} if sources else None
    try:
        return await recherche_unifiee.rechercher(q, registre, limite, choisies)
    except recherche_unifiee.ToutesSourcesIndisponibles as e:
        raise HTTPException(503, "Recherche indisponible : aucune source n'a répondu "
                                 f"({', '.join(e.args[0])}).") from None
```

Dans `core/main.py` : ajouter `recherche` à l'import `from routers import (...)` (ordre alphabétique de la liste existante), puis après `app.include_router(profil.router, dependencies=_tenant)` :

```python
# S241 — recherche unifiée (Forge + Ingestion + Mémoire) : session obligatoire (garde posée
# sur la route) + contexte de tenant pour que chaque brique cherche au nom de la personne.
app.include_router(recherche.router, dependencies=_tenant)
```

- [ ] **Step 4 : Brancher l'outil `chercher_documents`**

Dans `core/outils_domaines/documents.py`, remplacer le bloc `if nom == "chercher_documents":` par :

```python
    if nom == "chercher_documents":
        q = (args.get("q") or "").strip()
        if q:
            # S241 — recherche unifiée : Forge (documents + base de connaissances), documents
            # ingérés et Mémoire, avec références exactes en tête et fautes de frappe tolérées.
            import recherche_unifiee
            try:
                res = await recherche_unifiee.rechercher(q, registre, args.get("limite") or 10)
            except recherche_unifiee.ToutesSourcesIndisponibles:
                return json.dumps({"ok": False, "message": "Recherche indisponible : aucune source "
                                   "(Forge, documents ingérés, Mémoire) n'a répondu."}, ensure_ascii=False)
            return json.dumps(res, ensure_ascii=False)
        # Sans q : listage filtré des documents ingérés (catégorie, projet, entreprise), dont
        # dépendent les références de projet (core/projets.py).
        params = {k: args[k] for k in ("categorie", "projet", "entreprise_id")
                  if args.get(k)}
        params["limite"] = 200
        r = await client.get(f"{_base(registre, 'ingestion')}/documents", params=params,
                             headers=_entetes_brique("ingestion"))
        docs = r.json().get("documents", []) if r.status_code < 400 else []
        apercu = [{"id": d.get("id"), "nom": d.get("nom"), "type": d.get("type_mime"),
                   "classement": d.get("classement")} for d in docs]
        return json.dumps({"documents": apercu, "total": len(apercu)}, ensure_ascii=False)
```

Dans `core/outils.py`, remplacer la définition de `chercher_documents` par :

```python
    {"type": "function", "function": {
        "name": "chercher_documents",
        "description": "Cherche dans TOUS les documents : Forge (documents et base de connaissances), documents ingérés et mémoire. Avec q : références exactes (numéros, codes, expressions entre guillemets) en tête, puis mots et sens ; les fautes de frappe sont tolérées ; la réponse signale les sources indisponibles et le mode « lexical » (recherche par le sens momentanément coupée). Sans q : liste les documents ingérés, filtrables par catégorie, projet ou entreprise. Lecture seule.",
        "parameters": _p({
            "q": {"type": "string", "description": "Termes recherchés (optionnel ; sans q, listage filtré)."},
            "limite": {"type": "integer", "description": "Nombre maximum de résultats avec q (défaut 10, maximum 50)."},
            "categorie": {"type": "string", "description": "Sans q : filtre par catégorie (devis, facture, contrat…)."},
            "projet": {"type": "string", "description": "Sans q : filtre par dossier de projet (ex. « prochain sprint »)."},
            "entreprise_id": {"type": "string", "description": "Sans q : filtre par entreprise rattachée (livraison_id)."},
        }, [])}},
```

Dans `core/assistant.py` (ligne ~76), remplacer `"`chercher_documents` filtre par catégorie, projet ou entreprise ; avec "` par :

```python
    "`chercher_documents` cherche dans tous les documents (Forge, documents déposés, "
    "mémoire) avec `q`, ou liste les documents déposés par catégorie, projet ou entreprise "
    "sans `q` ; avec "
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run : `VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest -q core/test_recherche_route.py core/test_cerveau_admin.py core/test_ingestion_cle_service.py core/test_projets.py`
Attendu : tout passe.

Run (suite complète du Cœur) : `make test-core 2>&1 | tail -3`
Attendu : aucun échec. Noter le compte exact.

- [ ] **Step 6 : Commit**

```bash
git add core/routers/recherche.py core/main.py core/outils_domaines/documents.py core/outils.py \
  core/assistant.py core/test_cerveau_admin.py core/test_recherche_route.py
git commit -m "feat(S241): route /recherche du Cœur (session) et outil chercher_documents unifié"
```

---

### Task 11 : Cœur — onglet « 🔎 Recherche » du tableau de bord

**Files:**
- Modify: `core/dashboard.html`
- Test: `core/test_dashboard_xss.py` (existant, doit rester vert) + `core/test_recherche_dashboard.py` (créé)

**Interfaces:**
- Consumes : `GET /recherche` (Task 10).
- Produces : bouton d'onglet `data-vue="recherche"`, vue `#vue-recherche`, fonction JS `lancerRecherche()`.

- [ ] **Step 1 : Écrire le test (en échec)**

Créer `core/test_recherche_dashboard.py` :

```python
"""S241 — onglet Recherche : présent, appelle /recherche, rend SANS innerHTML.

$ cd core && python3 -m pytest test_recherche_dashboard.py -v
"""
import re
from pathlib import Path

SOURCE = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def _fonction(nom: str) -> str:
    debut = SOURCE.index(f"async function {nom}(")
    fin = SOURCE.index("\n}\n", debut)
    return SOURCE[debut:fin]


def test_onglet_et_vue_presents():
    assert 'data-vue="recherche"' in SOURCE
    assert 'id="vue-recherche"' in SOURCE


def test_appelle_la_route_du_coeur():
    assert "'/recherche?'" in _fonction("lancerRecherche")


def test_rendu_par_textcontent_uniquement():
    corps = _fonction("lancerRecherche")
    assert "innerHTML" not in corps and "insertAdjacentHTML" not in corps
    assert re.search(r"\.textContent\s*=", corps)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest -q core/test_recherche_dashboard.py`
Attendu : 3 échecs (`ValueError: substring not found` / assertions).

- [ ] **Step 3 : Ajouter l'onglet**

Dans `core/dashboard.html`, dans `<div class="tabs">`, après le bouton `data-vue="profil"` :

```html
      <button class="tab" data-vue="recherche" onclick="switchVue('recherche')" title="Chercher dans tous tes documents (Forge, documents déposés) et dans ta mémoire, même avec une faute de frappe.">🔎 Recherche</button>
```

- [ ] **Step 4 : Ajouter la vue**

Juste après `<main>` (avant `<!-- VUE BRIQUES -->`) :

```html
  <!-- VUE RECHERCHE (S241) — recherche unifiée Forge + documents déposés + Mémoire -->
  <div class="view" id="vue-recherche">
    <div class="topbar">
      <h2>Recherche</h2>
    </div>
    <form onsubmit="event.preventDefault(); lancerRecherche();" style="display:flex;gap:8px;margin:12px 0">
      <input id="recherche-q" type="search" placeholder="Un numéro, un nom, une idée…" autocomplete="off"
             style="flex:1;padding:10px 12px;border-radius:8px;border:1px solid var(--bord, #444);background:transparent;color:inherit">
      <button class="btn" type="submit">Chercher</button>
    </form>
    <div id="recherche-bandeau" style="display:none;margin:8px 0;padding:8px 12px;border-radius:8px;background:rgba(214,158,46,.15)"></div>
    <div id="recherche-resultats"></div>
  </div>
```

- [ ] **Step 5 : Ajouter le script**

Dans le `<script>` principal (après la ligne `const esc = …`, ligne ~1139 ; n'importe quel point du script de premier niveau convient), ajouter :

```javascript
// S241 — recherche unifiée. Rendu par création d'éléments et textContent UNIQUEMENT : les
// titres et extraits viennent de documents déposés par n'importe qui (filet XSS S240).
const RECHERCHE_LIBELLES = {
  'forge-document': 'Forge · document', 'forge-kb': 'Forge · connaissance', 'ingestion': 'Document déposé',
  'memoire-perso': 'Mémoire · perso', 'memoire-solution': 'Mémoire · travail', 'memoire-veille': 'Mémoire · veille',
};
async function lancerRecherche() {
  const q = document.getElementById('recherche-q').value.trim();
  const bandeau = document.getElementById('recherche-bandeau');
  const liste = document.getElementById('recherche-resultats');
  liste.replaceChildren();
  bandeau.style.display = 'none';
  if (!q) return;
  const attente = document.createElement('p');
  attente.textContent = 'Recherche…';
  liste.append(attente);
  let d;
  try {
    const r = await fetch('/recherche?' + new URLSearchParams({q, limite: '20'}), {credentials: 'same-origin'});
    d = await r.json().catch(() => ({}));
    if (!r.ok) { attente.textContent = d.detail || ('Erreur ' + r.status); return; }
  } catch (e) { attente.textContent = 'Erreur réseau : ' + e; return; }
  const avis = [];
  if ((d.sources_indisponibles || []).length) avis.push('Injoignable : ' + d.sources_indisponibles.join(', ') + '.');
  if (Object.values(d.modes || {}).includes('lexical')) avis.push('Recherche par le sens indisponible pour une partie des sources : seuls les mots ont été cherchés.');
  if (avis.length) { bandeau.textContent = avis.join(' '); bandeau.style.display = 'block'; }
  liste.replaceChildren();
  if (!(d.resultats || []).length) { attente.textContent = 'Aucun résultat.'; liste.append(attente); return; }
  for (const x of d.resultats) {
    const carte = document.createElement('div');
    carte.className = 'card';
    carte.style.margin = '8px 0';
    const tete = document.createElement('div');
    tete.style.cssText = 'display:flex;gap:8px;align-items:center;font-size:.85em;opacity:.8';
    const badge = document.createElement('span');
    badge.textContent = RECHERCHE_LIBELLES[x.source] || x.source;
    tete.append(badge);
    if (x.exact) { const e = document.createElement('span'); e.textContent = '· référence exacte'; tete.append(e); }
    if (x.partage) { const p = document.createElement('span'); p.textContent = '· partagé'; p.title = 'Visible par tous les comptes du cercle'; tete.append(p); }
    const titre = document.createElement('div');
    titre.style.cssText = 'font-weight:600;margin:4px 0';
    titre.textContent = x.titre || '(sans titre)';
    const extrait = document.createElement('div');
    extrait.style.opacity = '.85';
    extrait.textContent = x.extrait || '';
    carte.append(tete, titre, extrait);
    liste.append(carte);
  }
}
```

Vérifier que `switchVue('recherche')` affiche bien `#vue-recherche` : lire la fonction `switchVue` (`grep -n "function switchVue" core/dashboard.html`). Si elle s'appuie sur la convention `vue-<nom>` + `data-vue`, rien d'autre à faire ; sinon, ajouter le cas `recherche` en suivant le motif des autres vues, et placer le focus sur `#recherche-q` à l'ouverture.

- [ ] **Step 6 : Lancer, vérifier le succès**

Run : `VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test python3 -m pytest -q core/test_recherche_dashboard.py core/test_dashboard_xss.py`
Attendu : tout passe (le filet XSS ne voit aucune insertion HTML nouvelle).

- [ ] **Step 7 : Vérifier dans un navigateur**

Lancer le Cœur localement avec `AUTH_ENABLED=false` comme dans les sprints précédents (cf. `core/Makefile`, cible `up`), ouvrir `http://localhost:5100/dashboard`, onglet « 🔎 Recherche », chercher un mot : la liste ou un message (« Aucun résultat », bandeau « Injoignable : … » si les briques ne tournent pas) s'affiche, sans erreur dans la console. Avec Playwright si disponible : capture d'écran dans `docs/captures/S241-recherche.png`. Si le Cœur ne peut pas tourner localement, le noter et reporter cette vérification à la preuve LIVE (Task 13).

- [ ] **Step 8 : Commit**

```bash
git add core/dashboard.html core/test_recherche_dashboard.py
git commit -m "feat(S241): onglet Recherche du tableau de bord (rendu sans innerHTML)"
```

---

### Task 12 : Mesure du rappel@5

**Files:**
- Create: `briques/forge/forge/core/scripts/mesure_recherche_s241.json`
- Create: `briques/forge/forge/core/scripts/mesure_recherche_s241.py`

**Interfaces:**
- Consumes : `scripts.init_db.appliquer_schema`, `app.recherche_service.rechercher`, `app.memory.indexer_source` (Tasks 1, 3, 5).
- Produces : tableau markdown sur la sortie standard (repris dans les résultats, Task 13).

- [ ] **Step 1 : Écrire le jeu fixe**

Créer `briques/forge/forge/core/scripts/mesure_recherche_s241.json` :

```json
{
  "documents": [
    {"cle": "devis_toiture", "nom": "Devis DEV-2026-114 toiture Martin", "contenu": "Devis pour la réfection complète de la toiture de la maison Martin : dépose des tuiles, remplacement des liteaux, pose de tuiles mécaniques. Montant 18 400 euros TTC, validité trois mois."},
    {"cle": "facture_chaudiere", "nom": "Facture FAC-2026-0042", "contenu": "Facture d'entretien annuel de la chaudière gaz du client Durand. Ramonage, contrôle de combustion, remplacement du joint de brûleur. 240 euros payés par virement."},
    {"cle": "contrat_maintenance", "nom": "Contrat de maintenance ascenseur", "contenu": "Contrat de maintenance préventive de l'ascenseur de la résidence Les Tilleuls. Deux visites par an, dépannage sous quatre heures, pièces d'usure comprises."},
    {"cle": "pv_reception", "nom": "Procès-verbal de réception", "contenu": "Procès-verbal de réception des travaux d'isolation des combles, signé sans réserve le 12 mars. Garantie décennale de l'entreprise Isolpro jointe."},
    {"cle": "planning_chantier", "nom": "Planning chantier école", "contenu": "Planning du chantier de rénovation de l'école primaire : désamiantage en juillet, gros œuvre en août, livraison avant la rentrée de septembre."},
    {"cle": "note_recrutement", "nom": "Recrutement d'un conducteur de travaux", "contenu": "Nous cherchons un conducteur de travaux expérimenté pour encadrer les équipes sur les chantiers de logements collectifs. Permis B exigé, poste basé à Lyon."},
    {"cle": "rgpd", "nom": "Registre des traitements RGPD", "contenu": "Registre des traitements de données personnelles : fichier clients, paie des salariés, vidéosurveillance du dépôt. Durées de conservation et responsables désignés."},
    {"cle": "assurance", "nom": "Attestation d'assurance décennale", "contenu": "Attestation d'assurance responsabilité civile décennale valable pour l'année en cours, couvrant les activités de couverture, charpente et zinguerie."},
    {"cle": "relance_impaye", "nom": "Relance client Petit", "contenu": "Deuxième relance pour la facture FAC-2026-0057 restée impayée depuis soixante jours. Sans règlement sous huit jours, mise en demeure."},
    {"cle": "fiche_securite", "nom": "Consignes de sécurité échafaudage", "contenu": "Consignes de montage et de vérification des échafaudages : garde-corps obligatoires, vérification journalière, port du harnais au-delà de trois mètres."},
    {"cle": "commande_materiaux", "nom": "Bon de commande BC-7781", "contenu": "Commande de plaques de plâtre hydrofuges, rails et montants métalliques pour l'aménagement des salles de bain du lot B."},
    {"cle": "compte_rendu_reunion", "nom": "Compte rendu réunion de chantier n°7", "contenu": "Réunion de chantier : retard du plombier sur les colonnes d'eau, décision de décaler le carrelage d'une semaine, prochain rendez-vous jeudi."}
  ],
  "requetes": [
    {"type": "exacte", "q": "DEV-2026-114", "attendu": "devis_toiture"},
    {"type": "exacte", "q": "FAC-2026-0042", "attendu": "facture_chaudiere"},
    {"type": "exacte", "q": "FAC-2026-0057", "attendu": "relance_impaye"},
    {"type": "exacte", "q": "BC-7781", "attendu": "commande_materiaux"},
    {"type": "exacte", "q": "\"sans réserve\"", "attendu": "pv_reception"},
    {"type": "exacte", "q": "réunion de chantier n°7", "attendu": "compte_rendu_reunion"},
    {"type": "exacte", "q": "Isolpro", "attendu": "pv_reception"},
    {"type": "exacte", "q": "résidence Les Tilleuls", "attendu": "contrat_maintenance"},
    {"type": "semantique", "q": "combien coûte refaire le toit", "attendu": "devis_toiture"},
    {"type": "semantique", "q": "révision du chauffage au gaz", "attendu": "facture_chaudiere"},
    {"type": "semantique", "q": "entretien régulier de l'élévateur", "attendu": "contrat_maintenance"},
    {"type": "semantique", "q": "fin des travaux acceptée par le client", "attendu": "pv_reception"},
    {"type": "semantique", "q": "calendrier des travaux du bâtiment scolaire", "attendu": "planning_chantier"},
    {"type": "semantique", "q": "offre d'emploi chef de chantier", "attendu": "note_recrutement"},
    {"type": "semantique", "q": "protection des données personnelles", "attendu": "rgpd"},
    {"type": "semantique", "q": "client qui ne paie pas", "attendu": "relance_impaye"},
    {"type": "faute", "q": "toiturre", "attendu": "devis_toiture"},
    {"type": "faute", "q": "chaudierre", "attendu": "facture_chaudiere"},
    {"type": "faute", "q": "ascensseur", "attendu": "contrat_maintenance"},
    {"type": "faute", "q": "receptoin des travaux", "attendu": "pv_reception"},
    {"type": "faute", "q": "desamiantage", "attendu": "planning_chantier"},
    {"type": "faute", "q": "conducteur de travau", "attendu": "note_recrutement"},
    {"type": "faute", "q": "echaffaudage", "attendu": "fiche_securite"},
    {"type": "faute", "q": "decenale", "attendu": "assurance"}
  ]
}
```

- [ ] **Step 2 : Écrire le script de mesure**

Créer `briques/forge/forge/core/scripts/mesure_recherche_s241.py` :

```python
"""Mesure S241 : rappel@5 de la recherche Forge sur un jeu fixe (exacte, sens, faute de frappe).

Trois modes : « hybride » (embedder RÉEL de la Gateway — seulement si GATEWAY_API_KEY est
transmise), « lexical » (embedder coupé) et « LIKE » (l'ancienne recherche /api/search :
LIKE sensible à la casse, sans tolérance de faute). À lancer via le lanceur :
    scripts/en_docker.sh python -m scripts.mesure_recherche_s241
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import text

from app import memory
from app.db import SessionLocal, engine
from app.models import Documents
from app.recherche_service import rechercher
from scripts.init_db import appliquer_schema

JEU = json.loads((Path(__file__).with_suffix(".json")).read_text(encoding="utf-8"))
UTILISATEUR = "mesure-s241"
TYPES = ("exacte", "semantique", "faute")


async def _charger() -> dict[str, str]:
    async with engine.begin() as conn:
        await appliquer_schema(conn)
        await conn.execute(text("DELETE FROM documents WHERE user_id = :u"), {"u": UTILISATEUR})
    ids = {}
    async with SessionLocal() as s:
        for d in JEU["documents"]:
            doc = Documents(user_id=UTILISATEUR, nom=d["nom"], contenu=d["contenu"], taille=len(d["contenu"]))
            s.add(doc)
            await s.flush()
            ids[str(doc.id)] = d["cle"]
        await s.commit()
    return ids


async def _like(q: str, ids: dict[str, str]) -> list[str]:
    async with SessionLocal() as s:
        lignes = await s.execute(text(
            "SELECT id FROM documents WHERE user_id = :u AND (nom LIKE :p OR contenu LIKE :p) LIMIT 5"),
            {"u": UTILISATEUR, "p": f"%{q}%"})
        return [ids[str(r[0])] for r in lignes.all()]


async def _moteur(q: str, ids: dict[str, str]) -> list[str]:
    rep = await rechercher(q, UTILISATEUR, 5)
    return [ids[r["id"]] for r in rep["resultats"]]


async def _rappel(chercheur, ids) -> dict[str, float]:
    par_type = {}
    for t in TYPES:
        requetes = [r for r in JEU["requetes"] if r["type"] == t]
        trouves = sum(1 for r in requetes if r["attendu"] in await chercheur(r["q"], ids))
        par_type[t] = trouves / len(requetes)
    return par_type


async def principal() -> None:
    ids = await _charger()
    lignes = []
    if os.environ.get("GATEWAY_API_KEY"):
        for doc_id, cle in ids.items():
            d = next(x for x in JEU["documents"] if x["cle"] == cle)
            await memory.indexer_source(d["contenu"], doc_id, "document", UTILISATEUR, d["nom"])
        lignes.append(("hybride (embedder réel)", await _rappel(_moteur, ids)))
    else:
        lignes.append(("hybride (embedder réel)", None))

    async def _panne(textes, provider):
        raise RuntimeError("embedder coupé pour la mesure")

    memory._embed_batch = _panne
    lignes.append(("lexical (embedder coupé)", await _rappel(_moteur, ids)))
    lignes.append(("ancien LIKE", await _rappel(_like, ids)))

    print("| Mode | Exacte | Sens | Faute de frappe |")
    print("|---|---|---|---|")
    for nom, r in lignes:
        if r is None:
            print(f"| {nom} | non mesuré (GATEWAY_API_KEY absente) | | |")
        else:
            print(f"| {nom} | {r['exacte']:.2f} | {r['semantique']:.2f} | {r['faute']:.2f} |")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(principal())
```

- [ ] **Step 3 : Lancer la mesure**

Sans embedder réel :
Run : `cd briques/forge/forge/core && scripts/en_docker.sh python -m scripts.mesure_recherche_s241`
Attendu : tableau avec `lexical` et `ancien LIKE` mesurés, `hybride` « non mesuré ». Le lexical doit battre LIKE sur « faute » et « exacte » ; si ce n'est pas le cas, c'est un défaut à analyser (systematic-debugging), pas un chiffre à publier tel quel.

Avec l'embedder réel (Gateway du HP, joignable en LAN) — **sans jamais afficher la clé** :

```bash
cd /Users/garinat_t/Desktop/Workplace/briques/forge/forge/core
GATEWAY_BASE_URL=http://192.168.1.89:4001 \
GATEWAY_API_KEY="$(grep -E '^GATEWAY_KEY=' /Users/garinat_t/Desktop/Workplace/.env | cut -d= -f2-)" \
scripts/en_docker.sh python -m scripts.mesure_recherche_s241
```

(La substitution `$(…)` ne s'affiche pas ; ne pas ajouter `set -x`, ne pas faire `echo`.) Si la Gateway refuse (401/403) ou est injoignable, noter « hybride : non mesuré, raison » plutôt que de contourner.

Copier le tableau obtenu : il ira dans les résultats (Task 13).

- [ ] **Step 4 : Commit**

```bash
git add briques/forge/forge/core/scripts/mesure_recherche_s241.json briques/forge/forge/core/scripts/mesure_recherche_s241.py
git commit -m "test(S241): mesure du rappel@5 (exacte, sens, faute de frappe) contre l'ancien LIKE"
```

---

### Task 13 : Revue finale, déploiement HP, preuve LIVE, résultats

Cette tâche est opérationnelle (pas de TDD) ; elle est exécutée par l'agent principal, pas par un sous-agent, à cause des accès SSH et des secrets.

**Files:**
- Create: `docs/sprints/S241-recherche-unifiee-resultats.md`
- Modify: `docs/sprints/S235-S239-infrastructure-supervision-recherche.md` (statut de l'ex-S239 Meilisearch)

- [ ] **Step 1 : Filets complets, relancés par l'agent principal**

```bash
cd /Users/garinat_t/Desktop/Workplace
(cd briques/forge/forge/core && scripts/en_docker.sh python -m pytest -p no:cacheprovider -q 2>&1 | tail -3)
scripts/tests_briques.sh forge ingestion memoire 2>&1 | tail -20
make test 2>&1 | tail -3
```

Attendu : zéro échec partout. Noter les comptes exacts.

- [ ] **Step 2 : Revue finale de branche**

Invoquer `requesting-code-review` sur `main..sprint/s241-recherche-unifiee` (revue de toute la branche, pas tâche par tâche : les défauts entre tâches n'apparaissent qu'ici). Points à faire vérifier explicitement :
- aucun chemin de recherche Forge sans `user_id` (RAG, chat, ReAct, WS, recherche hybride) ;
- aucune interpolation de valeur utilisateur dans le SQL (seuls des noms issus de `TABLES`) ;
- index FTS5 cohérent après chaque écriture d'ingestion, y compris `importer` (`INSERT OR REPLACE`) ;
- rendu de l'onglet sans HTML ;
- `chercher_documents` sans `q` inchangé.

Traiter chaque Critical/Important (receiving-code-review : vérifier avant d'accepter), relancer les filets, refaire relire les correctifs.

- [ ] **Step 3 : Préparer le HP (lecture seule d'abord)**

Utiliser le skill `hpworkplace`. Relever, sans afficher aucun `.env` :

```bash
ssh debian@192.168.1.89 'cd ~/workplace && git status --short | head; git log --oneline -1;
  for c in forge-forge-1 forge-forge-adapter-1 workplace-ingestion; do docker inspect --format "{{.Name}} {{.Config.Image}}" $c; done;
  docker ps --format "{{.Names}} {{.Image}}" | grep -iE "core|coeur" '
```

Noter les noms d'images exacts (Forge core, adaptateur Forge, ingestion, Cœur).

- [ ] **Step 4 : Sauvegardes et étiquettes de retour arrière**

```bash
ssh debian@192.168.1.89 'set -e; mkdir -p ~/s241-avant
  docker exec forge-forge-db-1 sh -c "pg_dump -U \$POSTGRES_USER \$POSTGRES_DB" | gzip > ~/s241-avant/forge-db.sql.gz
  docker exec forge-forge-1 python -c "
import urllib.request,json
r=urllib.request.Request(\"http://qdrant:6333/collections/forge_local/snapshots\",method=\"POST\")
print(json.load(urllib.request.urlopen(r))[\"result\"][\"name\"])"
  docker cp workplace-ingestion:/data/ingestion.db ~/s241-avant/ingestion.db
  ls -la ~/s241-avant'
```

Puis, pour chaque image relevée au Step 3 : `docker tag <image> <dépôt>:avant-s241` sur le HP.

- [ ] **Step 5 : Construire sur le Mac, charger sur le HP**

Piège connu : `pip` ne résout pas pythonhosted depuis le HP (DNS NetBird) → construire sur le Mac.

```bash
cd /Users/garinat_t/Desktop/Workplace
git push -u origin sprint/s241-recherche-unifiee
(cd briques/forge && docker compose build forge forge-migrate forge-adapter)
(cd briques/ingestion && docker compose build)
(cd core && docker compose build)
docker save <images relevées au Step 3, mêmes noms:étiquettes> | ssh debian@192.168.1.89 docker load
```

(Les noms de services exacts sont ceux des `docker-compose.yml` ; les vérifier par `grep -n "^  [a-z]" <compose>`, jamais par `docker compose config`.)

- [ ] **Step 6 : Déployer dans l'ordre**

Sur le HP, dans `~/workplace` : `git fetch && git checkout sprint/s241-recherche-unifiee` (ou fusion dans `main` après accord de l'utilisateur), puis :
1. Forge : `docker compose -f briques/forge/docker-compose.yml up -d --no-build forge-migrate forge forge-adapter` (forge-migrate applique S241 avant que forge ne démarre) ;
2. Ingestion : `docker compose -f briques/ingestion/docker-compose.yml up -d --no-build` (l'index se construit au démarrage) ;
3. Cœur : `docker compose -f core/docker-compose.yml up -d --no-build`.
Vérifier la santé : `docker ps --format "{{.Names}} {{.Status}}" | grep -E "forge|ingestion|core"`.

- [ ] **Step 7 : Indexer l'existant et vérifier**

```bash
ssh debian@192.168.1.89 'docker exec forge-forge-1 python -m app.recherche_reindexer'
```

Attendu : `✓ N source(s) revectorisée(s) dans forge_local` (N = documents de plus de 20 caractères, ≤ 6). Puis vérifier le compte de points Qdrant (commande du constat de conception).

- [ ] **Step 8 : Preuve LIVE**

Avec une session réelle du Cœur (navigateur de l'utilisateur, ou cookie obtenu par la procédure de preuve de S240), et en relevant les sorties :
1. faute de frappe sur un vrai document de la brique ingestion (choisir un mot de son titre, le déformer) → trouvé ;
2. sans session : `curl -s -o /dev/null -w "%{http_code}" "http://192.168.1.89:5100/recherche?q=x"` → `401` ;
3. Forge arrêtée (`docker stop forge-forge-adapter-1`) → réponse 200 avec `"sources_indisponibles": ["forge"]` et des résultats Mémoire/Ingestion ; puis `docker start forge-forge-adapter-1` ;
4. embedder coupé : pendant que la Gateway est arrêtée quelques secondes (ou en pointant la Forge vers un modèle d'embedding inexistant n'est PAS acceptable en prod — préférer `docker stop` de la Gateway, accord de l'utilisateur requis, durée minimale) → `modes.forge == "lexical"`, résultats présents ; redémarrer la Gateway ;
5. document supprimé : créer un document de test dans la Forge, le trouver, le supprimer par son API, vérifier qu'il n'est plus trouvé, sans action sur Qdrant ;
6. onglet « 🔎 Recherche » ouvert dans le tableau de bord : capture `docs/captures/S241-recherche-live.png`.

Tout écart = défaut à corriger avant de conclure, pas une limite à documenter.

- [ ] **Step 9 : Écrire les résultats**

Créer `docs/sprints/S241-recherche-unifiee-resultats.md` sur le modèle de `docs/sprints/S240-modeles-configurables-cerveau-resultats.md` : décisions, ce qui a été livré, faille corrigée (RAG Forge sans filtre `user_id`), tests (comptes exacts relancés), tableau de mesure (Task 12), revue (findings et correctifs), déploiement (images, étiquettes `avant-s241`, sauvegardes `~/s241-avant/`), preuve LIVE (sorties), limites connues (ingestion partagée, Forge sous identité de service depuis le Cœur, doublons Forge/Mémoire possibles, pas de lien profond).

Dans `docs/sprints/S235-S239-infrastructure-supervision-recherche.md`, section « S239 — Recherche documentaire hybride Meilisearch + Qdrant », ajouter en tête :
`Statut : réalisé sous le numéro S241 (2026-10-06), sans Meilisearch (fédération Forge + Ingestion + Mémoire) — voir [résultats S241](S241-recherche-unifiee-resultats.md). Le numéro S239 a servi à la panne LLM.`

- [ ] **Step 10 : Commit, push**

```bash
git add docs/sprints/S241-recherche-unifiee-resultats.md docs/sprints/S235-S239-infrastructure-supervision-recherche.md docs/captures/S241-*.png
git commit -m "docs(S241): résultats, mesure, déploiement et preuve LIVE HP"
git push
```

Puis proposer à l'utilisateur la fusion dans `main` (finishing-a-development-branch).
