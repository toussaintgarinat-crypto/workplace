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
