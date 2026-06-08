import uuid

import pytest

pytestmark = pytest.mark.asyncio


class TestSpaces:
    async def test_create_space(self, client, auth_headers):
        response = await client.post(
            "/api/v1/spaces",
            json={"name": "My Space", "description": "My desc"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "My Space"
        assert data["role"] == "owner"
        assert "id" in data

    async def test_list_spaces(self, client, auth_headers, test_space):
        response = await client.get("/api/v1/spaces", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["id"] == test_space["id"]

    async def test_list_spaces_unauthorized(self, client):
        response = await client.get("/api/v1/spaces")
        assert response.status_code == 401

    async def test_get_space(self, client, auth_headers, test_space):
        response = await client.get(
            f"/api/v1/spaces/{test_space['id']}", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Test Space"

    async def test_get_space_not_found(self, client, auth_headers):
        response = await client.get(
            "/api/v1/spaces/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_space_not_found_other_user(self, client):
        uid = uuid.uuid4().hex[:8]
        await client.post(
            "/api/v1/auth/register",
            json={"email": f"other_{uid}@test.com", "password": "pass123"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": f"other_{uid}@test.com", "password": "pass123"},
        )
        other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        response = await client.get(
            "/api/v1/spaces/00000000-0000-0000-0000-000000000000",
            headers=other_headers,
        )
        assert response.status_code == 404

    async def test_delete_space(self, client, auth_headers):
        space = await client.post(
            "/api/v1/spaces",
            json={"name": "To Delete", "description": ""},
            headers=auth_headers,
        )
        space_data = space.json()

        response = await client.delete(
            f"/api/v1/spaces/{space_data['id']}", headers=auth_headers
        )
        assert response.status_code == 200

        response = await client.get(
            f"/api/v1/spaces/{space_data['id']}", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_get_space_members(self, client, auth_headers, test_space):
        response = await client.get(
            f"/api/v1/spaces/{test_space['id']}/members",
            headers=auth_headers,
        )
        assert response.status_code == 200
        members = response.json()
        assert len(members) == 1
        assert members[0]["role"] == "owner"

    async def test_invite_member(self, client, auth_headers, test_space):
        uid = uuid.uuid4().hex[:8]
        member_email = f"member_{uid}@test.com"
        await client.post(
            "/api/v1/auth/register",
            json={"email": member_email, "password": "pass123"},
        )
        response = await client.post(
            f"/api/v1/spaces/{test_space['id']}/invite",
            json={"email": member_email, "role": "member"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        members_resp = await client.get(
            f"/api/v1/spaces/{test_space['id']}/members",
            headers=auth_headers,
        )
        assert len(members_resp.json()) == 2

    async def test_remove_member(self, client, auth_headers, test_space):
        uid = uuid.uuid4().hex[:8]
        remove_email = f"remove_{uid}@test.com"
        await client.post(
            "/api/v1/auth/register",
            json={"email": remove_email, "password": "pass123"},
        )
        await client.post(
            f"/api/v1/spaces/{test_space['id']}/invite",
            json={"email": remove_email, "role": "member"},
            headers=auth_headers,
        )
        members = await client.get(
            f"/api/v1/spaces/{test_space['id']}/members",
            headers=auth_headers,
        )
        members_data = members.json()
        member_id = next(m["id"] for m in members_data if m["email"] == remove_email)

        response = await client.delete(
            f"/api/v1/spaces/{test_space['id']}/members/{member_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
