"""Tests des endpoints d'authentification (OIDC Keycloak)."""
import pytest
from sqlalchemy import text
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import TestSessionLocal, TEST_USER


@pytest.fixture(autouse=True)
def clean_users():
    yield
    session = TestSessionLocal()
    try:
        session.execute(text("DELETE FROM users WHERE id != :id"), {"id": TEST_USER["id"]})
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def user_in_db():
    session = TestSessionLocal()
    try:
        from models.user import User
        user = User(
            id=TEST_USER["id"],
            email=TEST_USER["email"],
            nom=TEST_USER["nom"],
            avatar_emoji=TEST_USER["avatar_emoji"],
            hashed_password="",
        )
        session.add(user)
        session.commit()
    finally:
        session.close()
    yield
    session = TestSessionLocal()
    try:
        session.execute(text("DELETE FROM users WHERE id = :id"), {"id": TEST_USER["id"]})
        session.commit()
    finally:
        session.close()


class TestAuthRequired:
    def test_get_me_sans_bearer_retourne_401(self):
        """Vérifie que GET /me sans token Keycloak retourne 401."""
        from main import app
        from fastapi.testclient import TestClient
        from database import get_db

        def override_db():
            s = TestSessionLocal()
            try:
                yield s
            finally:
                s.close()

        saved = dict(app.dependency_overrides)
        app.dependency_overrides = {get_db: override_db}
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.get("/api/auth/me")
                assert r.status_code == 401
        finally:
            app.dependency_overrides = saved


class TestProfil:
    def test_get_me_retourne_utilisateur(self, client, user_in_db):
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["user"]["nom"] == TEST_USER["nom"]

    def test_patch_me_met_à_jour_nom(self, client, user_in_db):
        r = client.patch("/api/auth/me", json={"nom": "Alice Modifié"})
        assert r.status_code == 200
        assert r.json()["user"]["nom"] == "Alice Modifié"

    def test_patch_me_met_à_jour_emoji(self, client, user_in_db):
        r = client.patch("/api/auth/me", json={"avatar_emoji": "🐉"})
        assert r.status_code == 200
        assert r.json()["user"]["avatar_emoji"] == "🐉"

    def test_statut_2fa_retourne_false(self, client, user_in_db):
        r = client.get("/api/auth/me/2fa-status")
        assert r.status_code == 200
        assert r.json()["totp_enabled"] is False

    def test_logout_retourne_ok(self, client):
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_export_données_retourne_json(self, client, user_in_db):
        r = client.get("/api/auth/me/export")
        assert r.status_code == 200
        data = r.json()
        assert "utilisateur" in data
        assert data["utilisateur"]["id"] == TEST_USER["id"]
