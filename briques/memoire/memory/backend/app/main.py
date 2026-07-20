import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine, Base
from app.dependencies import check_space_access
from app.routers import nodes, search, palace, graph, gardien, temporal, spaces, auth, export, import_router, stats, templates, collections
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all n'altère pas les tables existantes : on ajoute les colonnes
        # récentes de façon idempotente (pas d'Alembic dans ce projet). S109.
        await conn.execute(
            text("ALTER TABLE nodes ADD COLUMN IF NOT EXISTS canvas_pos JSONB")
        )
        # S110 : drapeau d'historique opt-in (la table node_revisions, elle, est
        # créée par create_all puisqu'elle est nouvelle).
        await conn.execute(
            text("ALTER TABLE nodes ADD COLUMN IF NOT EXISTS track_history BOOLEAN NOT NULL DEFAULT FALSE")
        )
        # S112 : journal temporel du GRAPHE. Opt-in au niveau de l'espace + soft-delete
        # des liens. La table node_stage_events (neuve) est créée par create_all.
        await conn.execute(
            text("ALTER TABLE spaces ADD COLUMN IF NOT EXISTS track_history BOOLEAN NOT NULL DEFAULT FALSE")
        )
        await conn.execute(
            text("ALTER TABLE edges ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
        )
    start_scheduler()
    yield
    stop_scheduler()
    await engine.dispose()


app = FastAPI(
    title="Memory API",
    version="0.1.0",
    lifespan=lifespan,
)

# Origines autorisées : liste explicite via CORS_ORIGINS (séparées par des virgules).
# Défaut restrictif (front mémoire + Cœur en local). « * » + credentials est interdit
# par les navigateurs et constitue un risque — on ne l'utilise plus par défaut.
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5100,http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(spaces.router, prefix="/api/v1/spaces", tags=["spaces"])
# Tous les routers ci-dessous sont scopés à UN espace (`{space_id}` dans le préfixe) et
# manipulent son contenu (nœuds, recherche, graphe, palais, gardien, templates,
# collections…). `check_space_access` en dépendance DE ROUTER (pas par route) : elle lit
# le MÊME `space_id` que le préfixe (FastAPI résout un paramètre de chemin une fois, partagé
# entre dépendances et handler) et exige que l'appelant soit membre — sinon 403/404. Avant
# ce correctif, AUCUNE de ces routes ne vérifiait rien : n'importe qui connaissant un
# `space_id` (UUID) pouvait lire/écrire/supprimer le contenu de N'IMPORTE QUEL espace, y
# compris les espaces "Perso-<personne>" censés être privés (S186). export/import/stats
# avaient déjà leur propre vérification, inchangée ci-dessous.
_gardé = [Depends(check_space_access)]
app.include_router(nodes.router, prefix="/api/v1/spaces/{space_id}/nodes", tags=["nodes"], dependencies=_gardé)
app.include_router(search.router, prefix="/api/v1/spaces/{space_id}/search", tags=["search"], dependencies=_gardé)
app.include_router(palace.router, prefix="/api/v1/spaces/{space_id}/palace", tags=["palace"], dependencies=_gardé)
app.include_router(graph.router, prefix="/api/v1/spaces/{space_id}/graph", tags=["graph"], dependencies=_gardé)
app.include_router(gardien.router, prefix="/api/v1/spaces/{space_id}/gardien", tags=["gardien"], dependencies=_gardé)
app.include_router(temporal.router, prefix="/api/v1/spaces/{space_id}", tags=["temporal"], dependencies=_gardé)
app.include_router(export.router, prefix="/api/v1/spaces/{space_id}/export", tags=["export"])
app.include_router(import_router.router, prefix="/api/v1/spaces/{space_id}/import", tags=["import"])
app.include_router(stats.router, prefix="/api/v1/spaces/{space_id}/stats", tags=["stats"])
app.include_router(templates.router, prefix="/api/v1/spaces/{space_id}/templates", tags=["templates"], dependencies=_gardé)
app.include_router(collections.router, prefix="/api/v1/spaces/{space_id}/collections", tags=["collections"], dependencies=_gardé)
