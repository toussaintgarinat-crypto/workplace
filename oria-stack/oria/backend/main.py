from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from agent_personnel_shared.fastapi_setup import setup_cors, setup_logging
from database import engine, Base
from sqlalchemy import text
import models.project
import models.world, models.building, models.user, models.quartier, models.dm, models.network
import models.abonnement
import models.vote
import models.llm_config
import models.agent
import models.document
import models.ipcra
import models.social
import models.shared_zone
import models.coin
import models.resident_agent
from routers import worlds, buildings, rooms, tokens, auth, quartiers
from routers import invitations, files as files_router, network as network_router
from routers import abonnements as abonnements_router
from routers import matrix_as
from routers.agents_router   import router as agents_router
from routers.documents_router import router as documents_router
from routers.discovery_router import router as discovery_router
from routers.ipcra_router    import router as ipcra_router
from routers.conductor_router import router as conductor_router
import os

Base.metadata.create_all(bind=engine)

# Migrations manuelles pour colonnes ajoutées après création initiale
_MIGRATIONS = [
    "ALTER TABLE documents ADD COLUMN partage_reseau BOOLEAN DEFAULT FALSE",
    # S125 — statut d'indexation du document (jobs durables Redis Streams)
    "ALTER TABLE documents ADD COLUMN index_status TEXT DEFAULT 'idle'",
    "ALTER TABLE users ADD COLUMN setup_completed_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN documents_partageables_par_defaut BOOLEAN DEFAULT FALSE",
    # Backfill : les comptes créés avant S72 sont considérés comme ayant déjà fait le tour
    "UPDATE users SET setup_completed_at = created_at WHERE setup_completed_at IS NULL",
    # S115 — Projects + Room closing
    "ALTER TABLE rooms ADD COLUMN project_id TEXT REFERENCES projects(id)",
    "ALTER TABLE rooms ADD COLUMN status TEXT DEFAULT 'active'",
    "ALTER TABLE rooms ADD COLUMN closed_at TIMESTAMP",
]
with engine.connect() as _conn:
    for _sql in _MIGRATIONS:
        try:
            _conn.execute(text(_sql))
            _conn.commit()
        except Exception:
            _conn.rollback()

setup_logging(level=os.getenv("LOG_LEVEL", "INFO"), fmt=os.getenv("LOG_FORMAT", "text"))

app = FastAPI(title="Oria API", version="2.0.0")

setup_cors(
    app,
    os.getenv("ALLOWED_ORIGINS", ""),
    default=["http://localhost:3000", "http://localhost:5173"],
)

for _candidate in ["/app/uploads", "/tmp/uploads",
                   os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads"))]:
    try:
        os.makedirs(_candidate, exist_ok=True)
        UPLOAD_DIR = _candidate
        break
    except OSError:
        continue
else:
    UPLOAD_DIR = "/tmp/uploads"

try:
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
except Exception:
    pass

from routers.vote_router import router as vote_router
from routers.search_router import router as search_router
from routers.reseau_router import router as reseau_router
from routers.llm_config_router import router as llm_config_router
from routers.social_router import router as social_router
from routers.jardin_router import router as jardin_router
from routers.shared_zones_router import router as shared_zones_router
from routers.admin import router as admin_router
from routers.coins_router import router as coins_router
from routers.calendar_router import router as calendar_router
from routers.projects_router import router as projects_router

# ── S99 — Versioning d'API + alias retro-compat ───────────────────────────
# Chaque router est monte deux fois : sous /api/... (legacy, avec headers
# Deprecation/Sunset) et sous /v1/api/... (canonique). Le middleware ajoute
# les headers RFC 8594. Date de sunset ~6 mois apres livraison S99.
DEPRECATION_SUNSET = "Mon, 23 Nov 2026 00:00:00 GMT"
_DEPRECATION_EXEMPT_PREFIXES = ("/v1/", "/uploads/", "/ws/")
_DEPRECATION_EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/"}


@app.middleware("http")
async def add_deprecation_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in _DEPRECATION_EXEMPT_PATHS:
        return response
    if any(path.startswith(p) for p in _DEPRECATION_EXEMPT_PREFIXES):
        return response
    # Tout le reste — typiquement /api/... — est l'alias legacy.
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = DEPRECATION_SUNSET
    if path.startswith("/api/"):
        response.headers.setdefault("Link", f'</v1{path}>; rel="successor-version"')
    return response


# (router, prefix_suffix) — prefix_suffix s'ajoute apres /api ou /v1/api.
_API_ROUTERS = [
    (auth.router,                   "/auth",         ["Auth"]),
    (worlds.router,                 "/worlds",       ["Worlds"]),
    (buildings.router,              "/buildings",    ["Buildings"]),
    (rooms.router,                  "/rooms",        ["Rooms"]),
    (tokens.router,                 "/tokens",       ["Tokens"]),
    (quartiers.router,              "/quartiers",    ["Quartiers"]),
    (invitations.router,            "/invitations",  ["Invitations"]),
    (files_router.router,           "/files",        ["Files"]),
    (network_router.router,         "/network",      ["Network"]),
    (abonnements_router.router,     "",              ["Abonnements"]),
    (vote_router,                   "/votes",        ["Votes"]),
    (search_router,                 "/search",       ["Recherche"]),
    (reseau_router,                 "/reseau",       ["Intercommunalité"]),
    (llm_config_router,             "/llm-config",   ["Config LLM"]),
    (agents_router,                 "/agents",       ["Agents IA"]),
    (documents_router,              "/documents",    ["Documents"]),
    (discovery_router,              "/discover",     ["Découverte"]),
    (ipcra_router,                  "/ipcra",        ["IPCRA"]),
    (social_router,                 "/social",       ["Social"]),
    (jardin_router,                 "/jardin",       ["Jardin Secret"]),
    (shared_zones_router,           "/shared-zones", ["Zones partagées"]),
    (admin_router,                  "",              ["Admin"]),
    (coins_router,                  "",              ["Coins & Rooms payantes"]),
    (conductor_router,              "/conductor",    ["Conductor"]),
    (calendar_router,               "/calendar",     ["Calendar"]),
    (projects_router,               "",              ["Projects"]),
]
for r, suffix, tags in _API_ROUTERS:
    # Canonique
    app.include_router(r, prefix=f"/v1/api{suffix}", tags=tags)
    # Legacy
    app.include_router(r, prefix=f"/api{suffix}",    tags=tags)

# Application Service Matrix — montée sans préfixe (protocole Matrix). On NE
# duplique PAS sous /v1 car ce sont les endpoints Matrix natifs imposes.
app.include_router(matrix_as.router, tags=["Matrix AS"])

# ── Yjs CRDT WebSocket ─────────────────────────────────────────
from fastapi import WebSocket, WebSocketDisconnect
from yjs_server import yjs_websocket_handler

@app.websocket("/ws/yjs/{zone_id}")
async def yjs_ws(websocket: WebSocket, zone_id: str):
    await yjs_websocket_handler(websocket, zone_id)


# ── Conductor WebSocket ─────────────────────────────────────────
from services.conductor_ws import conductor_manager

@app.websocket("/ws/conductor")
async def conductor_ws(websocket: WebSocket):
    await conductor_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # garder la connexion vivante
    except WebSocketDisconnect:
        await conductor_manager.disconnect(websocket)


# ── Seeding des 5 agents résidents pôle ────────────────────────
from contextlib import asynccontextmanager
from redis_client import init_redis, close_redis

_POLE_AGENTS = [
    ("Finance",   "💰", "Expert financier — budgets, P&L, trésorerie, reporting CFO."),
    ("Marketing", "📢", "Expert marketing — brand, campagnes, leads, analytics."),
    ("Sales",     "🤝", "Expert commercial — pipeline CRM, deals, relances, prévisions."),
    ("Ops",       "⚙️", "Expert opérations — sprints, process, infra, delivery."),
    ("Legal",     "⚖️", "Expert juridique — contrats, conformité, IP, RGPD."),
]


def _seed_resident_agents():
    from database import SessionLocal
    from models.resident_agent import ResidentAgent
    forge_url   = os.getenv("FORGE_URL", "http://localhost:3001")
    forge_token = os.getenv("FORGE_TOKEN", "")
    db = SessionLocal()
    try:
        existing = {a.pole_type for a in db.query(ResidentAgent).all()}
        for pole, emoji, desc in _POLE_AGENTS:
            if pole not in existing:
                db.add(ResidentAgent(
                    name=f"Agent {pole}",
                    pole_type=pole,
                    avatar_emoji=emoji,
                    description=desc,
                    forge_url=forge_url,
                    forge_token=forge_token,
                ))
        db.commit()
    finally:
        db.close()


_seed_resident_agents()


@asynccontextmanager
async def lifespan(app):
    await init_redis()
    from jobs_worker import start_worker, stop_worker
    await start_worker()
    yield
    await stop_worker()
    await close_redis()

app.router.lifespan_context = lifespan


@app.get("/health")
async def health():
    """Schema unifie S101 (HealthBuilder) — garde `status` top-level pour Prometheus blackbox."""
    from routers.admin import _is_readonly
    from agent_personnel_shared.health import HealthBuilder
    from redis_client import redis_client

    readonly = await _is_readonly()
    if readonly:
        import logging as _logging
        _logging.getLogger(__name__).warning("Oria running in read-only mode")

    builder = HealthBuilder(
        "oria",
        version="3.0.0",
        metadata={"readonly": readonly},
        degraded=readonly,
    )
    await builder.check_redis(redis_client, name="redis")
    payload = builder.build()
    # Compat ancien format : on garde `readonly` top-level pour les clients legacy.
    payload["readonly"] = readonly
    return payload


@app.middleware("http")
async def readonly_guard(request, call_next):
    from routers.admin import _is_readonly
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not request.url.path.startswith("/api/admin"):
            readonly = await _is_readonly()
            if readonly:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Oria est en mode lecture seule (maintenance)"},
                )
    return await call_next(request)


@app.get("/")
def root():
    return {"app": "Oria", "status": "ok", "version": "3.0.0"}
