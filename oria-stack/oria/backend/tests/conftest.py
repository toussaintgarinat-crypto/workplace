"""
Configuration pytest pour les tests IPCRA.
Remplace le moteur SQLAlchemy par SQLite in-process avant tout import de l'app,
ce qui garantit que les BackgroundTasks (qui utilisent database.SessionLocal
directement) écrivent dans la même base que les requêtes de test.
"""
import os
import sys
import pytest

# Doit précéder tout import de l'app
os.environ["DATABASE_URL"] = "sqlite:///./test_oria_e2e.db"
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")

# Ajoute le répertoire backend/ au PYTHONPATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from unittest.mock import patch

import database

# Remplace le moteur avant que main.py ne fasse create_all
TEST_DB_URL = "sqlite:///./test_oria_e2e.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
database.engine = test_engine
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
database.SessionLocal = TestSessionLocal

# Déclenche l'import de main (et donc de tous les modèles + create_all)
import main  # noqa: E402 — ordre intentionnel

from database import Base, get_db
from routers.auth import get_current_user

TEST_USER = {
    "id": "user-test-abc-123",
    "email": "test@oria-test.com",
    "nom": "Test User",
    "avatar_emoji": "👤",
}

# Patches MemPalace actifs globalement pour tous les tests
MP_PATCHES = [
    patch("mempalace_client.create_branch", return_value=True),
    patch("mempalace_client.prefetch", return_value=[]),
    patch("mempalace_client.sync", return_value=True),
    patch("mempalace_client.sync_document", return_value=2),
    patch("mempalace_client.merge_branch", return_value={"merged": 0, "conflicts": []}),
    patch("mempalace_client.check_contradictions", return_value=[]),
]


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Crée toutes les tables une fois par session de test."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists("test_oria_e2e.db"):
        os.remove("test_oria_e2e.db")


@pytest.fixture(autouse=True)
def clean_tables():
    """Vide les tables IPCRA et agents entre chaque test."""
    yield
    session = TestSessionLocal()
    try:
        session.execute(text("DELETE FROM ipcra_traces"))
        session.execute(text("DELETE FROM ipcra_items"))
        session.execute(text("DELETE FROM agent_definitions"))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def client():
    """
    Client de test FastAPI avec :
    - base SQLite de test
    - utilisateur fictif injecté (bypass JWT)
    - fonctions MemPalace mockées (dégradation gracieuse simulée)
    """
    from main import app

    def override_db():
        s = TestSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER

    mocks = [p.start() for p in MP_PATCHES]
    with TestClient(app) as c:
        yield c
    for p in MP_PATCHES:
        p.stop()

    app.dependency_overrides.clear()
