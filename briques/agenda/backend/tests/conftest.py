"""Fixtures de test — base SQLite en mémoire + secret de coffre.

Les fonctions du coffre et du pont prennent une AsyncSession en argument : on les
teste donc directement, sans monter l'app FastAPI ni toucher au réseau.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings


@pytest.fixture(autouse=True)
def _vault_secret():
    """Le coffre exige un VAULT_SECRET ; on en fixe un déterministe pour les tests."""
    settings.VAULT_SECRET = "test-vault-secret-32-bytes-min-xx"
    yield


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    from models.orm import Base  # import tardif → modèles enregistrés

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()
