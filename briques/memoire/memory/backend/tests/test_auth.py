import uuid

import pytest

pytestmark = pytest.mark.asyncio


class TestAuth:
    async def test_register(self, client):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "secure123",
                "display_name": "New User",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert "id" in data

    async def test_register_duplicate(self, client):
        await client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "secure123"},
        )
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "secure123"},
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    async def test_login_success(self, client):
        await client.post(
            "/api/v1/auth/register",
            json={"email": "login@example.com", "password": "mypassword"},
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "mypassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_invalid(self, client):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrong@example.com", "password": "wrong"},
        )
        assert response.status_code == 401

    async def test_get_me(self, client, auth_headers):
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Test User"

    async def test_get_me_unauthorized(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    async def test_update_profile(self, client, auth_headers):
        response = await client.put(
            "/api/v1/auth/me",
            json={"display_name": "Updated Name"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["display_name"] == "Updated Name"

    async def test_change_password(self, client, auth_headers):
        response = await client.put(
            "/api/v1/auth/me/password",
            json={"current_password": "password123", "new_password": "newpass456"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["detail"] == "Password updated"

    async def test_delete_account(self, client, auth_headers):
        response = await client.delete("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
