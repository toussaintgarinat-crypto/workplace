import pytest

pytestmark = pytest.mark.asyncio


class TestNodes:
    async def test_create_node(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        response = await client.post(
            f"/api/v1/spaces/{space_id}/nodes",
            json={
                "type": "input",
                "title": "My Note",
                "content_md": "# Content",
                "frontmatter": {"priority": "high", "tags": ["test"]},
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "My Note"
        assert data["type"] == "input"
        assert data["ipcra_stage"] == "input"
        assert data["storage_tier"] == "hot"
        assert "id" in data

    async def test_create_projet(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        response = await client.post(
            f"/api/v1/spaces/{space_id}/nodes",
            json={
                "type": "projet",
                "title": "Test Project",
                "content_md": "# Project Plan",
                "frontmatter": {
                    "deadline": "2026-12-31",
                    "status": "active",
                    "priority": "high",
                    "next_actions": ["Step 1", "Step 2"],
                },
                "location": {"wing": "Travail", "room": "Projets", "drawer": None},
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "projet"
        assert data["ipcra_stage"] == "projet"

    async def test_list_nodes(self, client, auth_headers, test_node, test_space):
        response = await client.get(
            f"/api/v1/spaces/{test_space['id']}/nodes",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["title"] == "Test Note"

    async def test_list_nodes_filter_type(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        await client.post(
            f"/api/v1/spaces/{space_id}/nodes",
            json={"type": "input", "title": "Input 1"},
            headers=auth_headers,
        )
        await client.post(
            f"/api/v1/spaces/{space_id}/nodes",
            json={"type": "projet", "title": "Project 1"},
            headers=auth_headers,
        )
        response = await client.get(
            f"/api/v1/spaces/{space_id}/nodes?type=input",
            headers=auth_headers,
        )
        assert response.status_code == 200
        for node in response.json():
            assert node["type"] == "input"

    async def test_list_nodes_filter_wing(self, client, auth_headers, test_space):
        """wing/room ne sont pas des colonnes : ils vivent dans frontmatter (posé par
        l'appelant, ex. briques/memoire/main.py). Sans filtre JSONB sur list_nodes(), un
        appelant qui demande `wing=atelier-images-video` recevait TOUS les nœuds de
        l'espace — bug constaté : galerie images/vidéo affichant des souvenirs d'autres
        briques (veille, dev)."""
        space_id = test_space["id"]
        await client.post(
            f"/api/v1/spaces/{space_id}/nodes",
            json={"type": "ressource", "title": "Image atelier",
                  "frontmatter": {"wing": "atelier-images-video", "room": "image"}},
            headers=auth_headers,
        )
        await client.post(
            f"/api/v1/spaces/{space_id}/nodes",
            json={"type": "ressource", "title": "Note veille",
                  "frontmatter": {"wing": "veille", "room": "info"}},
            headers=auth_headers,
        )
        response = await client.get(
            f"/api/v1/spaces/{space_id}/nodes?wing=atelier-images-video",
            headers=auth_headers,
        )
        assert response.status_code == 200
        titres = [n["title"] for n in response.json()]
        assert "Image atelier" in titres
        assert "Note veille" not in titres

    async def test_get_node(self, client, auth_headers, test_node, test_space):
        response = await client.get(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_node["id"]
        assert data["title"] == "Test Note"

    async def test_get_node_not_found(self, client, auth_headers, test_space):
        response = await client.get(
            f"/api/v1/spaces/{test_space['id']}/nodes/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_update_node(self, client, auth_headers, test_node, test_space):
        response = await client.put(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}",
            json={"title": "Updated Title", "content_md": "# Updated"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"

    async def test_update_stage(self, client, auth_headers, test_node, test_space):
        response = await client.patch(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}/stage",
            json={"stage": "ressource"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["ipcra_stage"] == "ressource"

    async def test_update_tier(self, client, auth_headers, test_node, test_space):
        response = await client.patch(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}/tier",
            json={"tier": "archive"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["storage_tier"] == "archive"

    async def test_soft_delete_node(self, client, auth_headers, test_node, test_space):
        response = await client.delete(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}",
            headers=auth_headers,
        )
        assert response.status_code == 200

        get_resp = await client.get(
            f"/api/v1/spaces/{test_space['id']}/nodes",
            headers=auth_headers,
        )
        for node in get_resp.json():
            assert node["id"] != test_node["id"]

    async def test_touch_node(self, client, auth_headers, test_node, test_space):
        response = await client.post(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}/touch",
            headers=auth_headers,
        )
        assert response.status_code == 200

    async def test_move_node_location(self, client, auth_headers, test_node, test_space):
        response = await client.put(
            f"/api/v1/spaces/{test_space['id']}/nodes/{test_node['id']}/location",
            json={"wing": "Savoir", "room": "Python", "drawer": None},
            headers=auth_headers,
        )
        assert response.status_code == 200
