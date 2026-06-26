import pytest

pytestmark = pytest.mark.asyncio


class TestNodeRevisions:
    """S110 — historique opt-in : on n'archive que si le nœud l'a explicitement demandé."""

    async def _revisions(self, client, auth_headers, space_id, node_id):
        r = await client.get(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}/revisions",
            headers=auth_headers,
        )
        assert r.status_code == 200
        return r.json()

    async def test_no_history_by_default(self, client, auth_headers, test_node, test_space):
        """Éditer un nœud non suivi ne crée aucune révision (souveraineté par défaut)."""
        space_id, node_id = test_space["id"], test_node["id"]

        put = await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"content_md": "version modifiée sans suivi"},
            headers=auth_headers,
        )
        assert put.status_code == 200
        assert put.json()["track_history"] is False

        assert await self._revisions(client, auth_headers, space_id, node_id) == []

    async def test_opt_in_archives_previous_versions(self, client, auth_headers, test_node, test_space):
        """Activer le suivi puis éditer archive l'état précédent, du plus récent au plus ancien."""
        space_id, node_id = test_space["id"], test_node["id"]
        original = test_node["content_md"]

        # 1) On active le suivi EN MÊME TEMPS qu'on change le contenu → l'état d'origine
        #    (baseline) doit être archivé.
        r1 = await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"track_history": True, "content_md": "v2"},
            headers=auth_headers,
        )
        assert r1.status_code == 200
        assert r1.json()["track_history"] is True

        # 2) Nouvelle édition → archive "v2".
        r2 = await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"content_md": "v3"},
            headers=auth_headers,
        )
        assert r2.status_code == 200

        revs = await self._revisions(client, auth_headers, space_id, node_id)
        assert [r["content_md"] for r in revs] == ["v2", original]
        # Horodatage présent et trié décroissant.
        assert revs[0]["captured_at"] >= revs[1]["captured_at"]

    async def test_no_revision_when_nothing_changes(self, client, auth_headers, test_node, test_space):
        """Suivi actif mais ré-écriture à l'identique = pas de révision parasite."""
        space_id, node_id = test_space["id"], test_node["id"]

        await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"track_history": True},
            headers=auth_headers,
        )
        # Même contenu que l'original → aucun champ versionné ne change.
        await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"content_md": test_node["content_md"]},
            headers=auth_headers,
        )
        assert await self._revisions(client, auth_headers, space_id, node_id) == []

    async def test_get_single_revision(self, client, auth_headers, test_node, test_space):
        space_id, node_id = test_space["id"], test_node["id"]
        await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"track_history": True, "content_md": "nouveau"},
            headers=auth_headers,
        )
        revs = await self._revisions(client, auth_headers, space_id, node_id)
        rev_id = revs[0]["id"]

        r = await client.get(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}/revisions/{rev_id}",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["content_md"] == test_node["content_md"]

    async def test_restore_revision(self, client, auth_headers, test_node, test_space):
        """Restaurer remet l'ancien contenu ET archive l'état courant au passage."""
        space_id, node_id = test_space["id"], test_node["id"]
        original = test_node["content_md"]

        await client.put(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}",
            json={"track_history": True, "content_md": "v2"},
            headers=auth_headers,
        )  # archive l'original
        revs = await self._revisions(client, auth_headers, space_id, node_id)
        original_rev_id = next(r["id"] for r in revs if r["content_md"] == original)

        restore = await client.post(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}/revisions/{original_rev_id}/restore",
            headers=auth_headers,
        )
        assert restore.status_code == 200
        assert restore.json()["content_md"] == original

        # La restauration a archivé "v2" → on a maintenant deux révisions.
        revs2 = await self._revisions(client, auth_headers, space_id, node_id)
        assert [r["content_md"] for r in revs2] == ["v2", original]

    async def test_revisions_unknown_node_404(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        r = await client.get(
            f"/api/v1/spaces/{space_id}/nodes/00000000-0000-0000-0000-000000000000/revisions",
            headers=auth_headers,
        )
        assert r.status_code == 404

    async def test_restore_unknown_revision_404(self, client, auth_headers, test_node, test_space):
        space_id, node_id = test_space["id"], test_node["id"]
        r = await client.post(
            f"/api/v1/spaces/{space_id}/nodes/{node_id}/revisions/00000000-0000-0000-0000-000000000000/restore",
            headers=auth_headers,
        )
        assert r.status_code == 404
