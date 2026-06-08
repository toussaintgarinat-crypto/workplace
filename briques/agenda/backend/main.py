"""Calendar Service — point d'entrée FastAPI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from agent_personnel_shared.fastapi_setup import setup_cors, setup_logging
from config import settings
from db import init_db
from routers.attachments import router as attachments_router
from routers.calendars import router as calendars_router
from routers.comments import router as comments_router
from routers.events import router as events_router
from routers.health import router as health_router
from routers.invitations import router as invitations_router
from routers.members import router as members_router
from routers.participants import router as participants_router
from routers.sse import router as sse_router

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Calendar service started on port 8400")
    yield
    logger.info("Calendar service shutting down")


app = FastAPI(title="Calendar Service", version="1.0.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

setup_cors(app, settings.CORS_ORIGINS, default=["http://localhost:8300"])

app.include_router(health_router)
app.include_router(calendars_router)
app.include_router(events_router)
app.include_router(members_router)
app.include_router(invitations_router)
app.include_router(participants_router)
app.include_router(comments_router)
app.include_router(attachments_router)
app.include_router(sse_router)
