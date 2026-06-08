"""Accès base de données — SQLAlchemy 2.0 async (asyncpg).

La DB est partagée avec le Bun et ne change pas pendant la migration strangler.
On ne crée donc AUCUNE table ici (pas de `create_all`) : on mappe l'existant via
``app/models/generated.py`` (sqlacodegen). Cf. roadmap S126-S137.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # évite les connexions mortes (pgbouncer/Patroni failover)
    echo=False,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI : une session par requête."""
    async with SessionLocal() as session:
        yield session


async def ping() -> bool:
    """Vérifie la connectivité DB (pour /health). True si SELECT 1 réussit."""
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose() -> None:
    await engine.dispose()
