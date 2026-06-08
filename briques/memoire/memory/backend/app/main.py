import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import nodes, search, palace, graph, gardien, temporal, spaces, auth, export, import_router, stats, templates, collections
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
app.include_router(nodes.router, prefix="/api/v1/spaces/{space_id}/nodes", tags=["nodes"])
app.include_router(search.router, prefix="/api/v1/spaces/{space_id}/search", tags=["search"])
app.include_router(palace.router, prefix="/api/v1/spaces/{space_id}/palace", tags=["palace"])
app.include_router(graph.router, prefix="/api/v1/spaces/{space_id}/graph", tags=["graph"])
app.include_router(gardien.router, prefix="/api/v1/spaces/{space_id}/gardien", tags=["gardien"])
app.include_router(temporal.router, prefix="/api/v1/spaces/{space_id}", tags=["temporal"])
app.include_router(export.router, prefix="/api/v1/spaces/{space_id}/export", tags=["export"])
app.include_router(import_router.router, prefix="/api/v1/spaces/{space_id}/import", tags=["import"])
app.include_router(stats.router, prefix="/api/v1/spaces/{space_id}/stats", tags=["stats"])
app.include_router(templates.router, prefix="/api/v1/spaces/{space_id}/templates", tags=["templates"])
app.include_router(collections.router, prefix="/api/v1/spaces/{space_id}/collections", tags=["collections"])
