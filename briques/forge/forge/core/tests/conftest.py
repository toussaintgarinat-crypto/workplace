"""Fixtures de test communes forge/core."""

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Pas de vraie DB en test unitaire : check_pg() échoue proprement (status "down").
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://forge:forge@localhost:5432/forge")


@pytest_asyncio.fixture
async def app():
    """Importe l'app après le réglage de l'env (proxy strangler retiré au cutover S136)."""
    from app.main import app as fastapi_app

    yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
