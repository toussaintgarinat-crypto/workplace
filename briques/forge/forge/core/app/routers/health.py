"""Endpoint /health — schéma commun (HealthBuilder, S101)."""

from fastapi import APIRouter

from agent_personnel_shared.health import HealthBuilder

from app.config import settings
from app.db import engine

router = APIRouter()


@router.get("/health")
async def health():
    builder = HealthBuilder(
        settings.SERVICE_NAME,
        version=settings.VERSION,
        metadata={"mode": "native"},  # S136 — backend forge unique (Bun supprimé)
    )
    await builder.check_pg(engine)
    return builder.build()
