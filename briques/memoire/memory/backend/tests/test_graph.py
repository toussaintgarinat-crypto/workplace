import pytest

pytestmark = pytest.mark.asyncio


class TestGraphPosition:
    """S109 — glisser-déposer dans le canvas : la position est persistée et relue."""

    async def test_node_has_no_position_by_default(self, client, auth_headers, test_node, test_space):
        space_id = test_space["id"]
        response = await client.get(
            f"/api/v1/spaces/{space_id}/graph",
            headers=auth_headers,
        )
        assert response.status_code == 200
        node = next(n for n in response.json()["nodes"] if n["id"] == test_node["id"])
        assert node["pos"] is None

    async def test_set_and_persist_position(self, client, auth_headers, test_node, test_space):
        space_id = test_space["id"]
        node_id = test_node["id"]

        # On déplace le nœud.
        put = await client.put(
            f"/api/v1/spaces/{space_id}/graph/nodes/{node_id}/position",
            json={"x": 321.5, "y": -64.0},
            headers=auth_headers,
        )
        assert put.status_code == 200
        assert put.json()["pos"] == {"x": 321.5, "y": -64.0}

        # Une relecture du graphe rend la position enregistrée (pas la grille).
        graph = await client.get(
            f"/api/v1/spaces/{space_id}/graph",
            headers=auth_headers,
        )
        node = next(n for n in graph.json()["nodes"] if n["id"] == node_id)
        assert node["pos"] == {"x": 321.5, "y": -64.0}

    async def test_set_position_unknown_node(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        response = await client.put(
            f"/api/v1/spaces/{space_id}/graph/nodes/00000000-0000-0000-0000-000000000000/position",
            json={"x": 1.0, "y": 2.0},
            headers=auth_headers,
        )
        assert response.status_code == 404
