"""Calendar Service — point d'entrée FastAPI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from agent_personnel_shared.fastapi_setup import setup_cors, setup_logging
from config import settings
from db import init_db
from routers.app_web import router as app_web_router
from routers.attachments import router as attachments_router
from routers.calendars import router as calendars_router
from routers.comments import router as comments_router
from routers.events import router as events_router
from routers.google_sync import router as google_router
from routers.health import router as health_router
from routers.invitations import router as invitations_router
from routers.labels import router as labels_router
from routers.members import router as members_router
from routers.participants import router as participants_router
from routers.profiles import router as profiles_router
from routers.service import router as service_router
from routers.sse import router as sse_router
from routers.timetree import router as timetree_router

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # S174 : rend le modèle « destinataire = participant » uniforme pour les events
    # d'avant le sprint. Idempotent — quasi no-op après le premier démarrage.
    try:
        from db import AsyncSessionLocal
        from services.backfill import creer_participants_createurs
        async with AsyncSessionLocal() as _db:
            n = await creer_participants_createurs(_db)
            if n:
                logger.info("S174 backfill : %d participant(s) créateur(s) posé(s)", n)
    except Exception as ex:  # noqa: BLE001 — un backfill KO ne doit pas empêcher le boot
        logger.warning("S174 backfill ignoré : %s", ex)
    logger.info("Calendar service started on port 8400")
    yield
    logger.info("Calendar service shutting down")


app = FastAPI(title="Calendar Service", version="1.0.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

setup_cors(app, settings.CORS_ORIGINS, default=["http://localhost:8300"])

app.include_router(health_router)
app.include_router(app_web_router)
app.include_router(calendars_router)
app.include_router(labels_router)
app.include_router(events_router)
app.include_router(members_router)
app.include_router(invitations_router)
app.include_router(participants_router)
app.include_router(profiles_router)
app.include_router(service_router)
app.include_router(comments_router)
app.include_router(attachments_router)
app.include_router(sse_router)
app.include_router(google_router)
app.include_router(timetree_router)
