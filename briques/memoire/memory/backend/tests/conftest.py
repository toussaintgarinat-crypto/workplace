import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

# ── Override engine BEFORE importing app modules ──────────────
import app.database
import app.config

# Postgres de test : par défaut une instance locale (dev), surchargeable par env
# (TEST_DATABASE_URL) pour tourner dans un conteneur sur le réseau Docker de la brique.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://garinat_t@localhost:5432/memory_test",
)

app.config.settings.database_url = TEST_DB_URL

test_engine = create_async_engine(TEST_DB_URL, echo=False, pool_size=5, max_overflow=10)
app.database.engine = test_engine
app.database.async_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

from app import database as db_module
from app.database import Base
from app.main import app as fastapi_app
from app.models.user import User
from passlib.hash import bcrypt

get_db = db_module.get_db


# ── Create tables once ───────────────────────────────────────
@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Override get_db (same engine, different session) ─────────
async def override_get_db():
    async with db_module.async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


fastapi_app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(client):
    uid = uuid.uuid4().hex[:8]
    email = f"test_{uid}@example.com"

    async with db_module.async_session_factory() as db:
        user = User(email=email, display_name="Test User", password_hash=bcrypt.hash("password123"))
        db.add(user)
        await db.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_space(client, auth_headers):
    response = await client.post(
        "/api/v1/spaces",
        json={"name": "Test Space", "description": "A test space"},
        headers=auth_headers,
    )
    return response.json()


@pytest_asyncio.fixture
async def test_node(client, auth_headers, test_space):
    response = await client.post(
        f"/api/v1/spaces/{test_space['id']}/nodes",
        json={
            "type": "input",
            "title": "Test Note",
            "content_md": "# Hello\nThis is a test.",
            "frontmatter": {"priority": "medium", "tags": ["test"]},
        },
        headers=auth_headers,
    )
    return response.json()
