import asyncio
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _enable_history(client, headers, space_id) -> dict:
    """Active le journal temporel de l'espace (opt-in S112)."""
    resp = await client.put(
        f"/api/v1/spaces/{space_id}",
        json={"track_history": True},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()


async def _create_node(client, headers, space_id, type_, title) -> dict:
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/nodes",
        json={"type": type_, "title": title},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


async def _graph_at(client, headers, space_id, t: datetime) -> dict:
    resp = await client.get(
        f"/api/v1/spaces/{space_id}/graph/at",
        params={"t": t.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()


class TestSpaceOptIn:
    """Le journal est opt-in AU NIVEAU DE L'ESPACE (distinct du suivi par document)."""

    async def test_track_history_default_false(self, client, auth_headers, test_space):
        resp = await client.get(f"/api/v1/spaces/{test_space['id']}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["track_history"] is False

    async def test_toggle_track_history(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        updated = await _enable_history(client, auth_headers, space_id)
        assert updated["track_history"] is True
        # Persisté : une relecture le confirme.
        again = await client.get(f"/api/v1/spaces/{space_id}", headers=auth_headers)
        assert again.json()["track_history"] is True


class TestStageEventsGatedByFlag:
    """Les évènements de stade ne sont écrits que si l'espace suit son histoire."""

    async def test_no_events_when_flag_off(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        await _create_node(client, auth_headers, space_id, "input", "Muet")
        timeline = await client.get(
            f"/api/v1/spaces/{space_id}/graph/timeline", headers=auth_headers
        )
        assert timeline.status_code == 200
        assert timeline.json() == []

    async def test_creation_event_when_flag_on(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        await _enable_history(client, auth_headers, space_id)
        await _create_node(client, auth_headers, space_id, "input", "Suivi")
        timeline = (await client.get(
            f"/api/v1/spaces/{space_id}/graph/timeline", headers=auth_headers
        )).json()
        assert len(timeline) == 1
        assert timeline[0]["kind"] == "created"
        assert timeline[0]["label"] == "input"

    async def test_stage_transition_recorded(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        await _enable_history(client, auth_headers, space_id)
        node = await _create_node(client, auth_headers, space_id, "input", "Évolue")
        patch = await client.patch(
            f"/api/v1/spaces/{space_id}/nodes/{node['id']}/stage",
            json={"stage": "projet"},
            headers=auth_headers,
        )
        assert patch.status_code == 200
        kinds = [e["kind"] for e in (await client.get(
            f"/api/v1/spaces/{space_id}/graph/timeline", headers=auth_headers
        )).json()]
        assert kinds == ["created", "stage"]


class TestEdgeSoftDelete:
    async def test_soft_delete_when_tracked(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        await _enable_history(client, auth_headers, space_id)
        a = await _create_node(client, auth_headers, space_id, "input", "A")
        b = await _create_node(client, auth_headers, space_id, "input", "B")
        edge = (await client.post(
            f"/api/v1/spaces/{space_id}/graph/edges",
            json={"source_id": a["id"], "target_id": b["id"]},
            headers=auth_headers,
        )).json()

        t_with_edge = _now()
        await asyncio.sleep(0.02)

        deleted = await client.delete(
            f"/api/v1/spaces/{space_id}/graph/edges/{edge['id']}", headers=auth_headers
        )
        assert deleted.status_code == 200

        # Le présent ne montre plus le lien…
        present = (await client.get(
            f"/api/v1/spaces/{space_id}/graph", headers=auth_headers
        )).json()
        assert present["edges"] == []

        # … mais à un T antérieur à la suppression, il est encore vivant.
        past = await _graph_at(client, auth_headers, space_id, t_with_edge)
        assert [e["id"] for e in past["edges"]] == [edge["id"]]

        # La suppression apparaît dans la frise (created+removed du lien).
        kinds = [e["kind"] for e in (await client.get(
            f"/api/v1/spaces/{space_id}/graph/timeline", headers=auth_headers
        )).json()]
        assert "edge_added" in kinds and "edge_removed" in kinds

    async def test_hard_delete_when_untracked(self, client, auth_headers, test_space):
        space_id = test_space["id"]  # suivi OFF par défaut
        a = await _create_node(client, auth_headers, space_id, "input", "A")
        b = await _create_node(client, auth_headers, space_id, "input", "B")
        edge = (await client.post(
            f"/api/v1/spaces/{space_id}/graph/edges",
            json={"source_id": a["id"], "target_id": b["id"]},
            headers=auth_headers,
        )).json()
        deleted = await client.delete(
            f"/api/v1/spaces/{space_id}/graph/edges/{edge['id']}", headers=auth_headers
        )
        assert deleted.status_code == 200
        # Hard-delete : aucune trace, ni au présent ni dans la frise.
        present = (await client.get(
            f"/api/v1/spaces/{space_id}/graph", headers=auth_headers
        )).json()
        assert present["edges"] == []
        timeline = (await client.get(
            f"/api/v1/spaces/{space_id}/graph/timeline", headers=auth_headers
        )).json()
        assert timeline == []


class TestGraphAtScenario:
    """Scénario complet : la photo du graphe change selon l'instant demandé."""

    async def test_state_at_t1_t2_t3(self, client, auth_headers, test_space):
        space_id = test_space["id"]
        await _enable_history(client, auth_headers, space_id)

        t0 = _now()
        await asyncio.sleep(0.02)

        a = await _create_node(client, auth_headers, space_id, "input", "A")
        await asyncio.sleep(0.02)
        t1 = _now()  # A existe, stade input, pas de lien
        await asyncio.sleep(0.02)

        await client.patch(
            f"/api/v1/spaces/{space_id}/nodes/{a['id']}/stage",
            json={"stage": "projet"},
            headers=auth_headers,
        )
        await asyncio.sleep(0.02)
        t2 = _now()  # A est projet
        await asyncio.sleep(0.02)

        b = await _create_node(client, auth_headers, space_id, "input", "B")
        edge = (await client.post(
            f"/api/v1/spaces/{space_id}/graph/edges",
            json={"source_id": a["id"], "target_id": b["id"]},
            headers=auth_headers,
        )).json()
        await asyncio.sleep(0.02)
        t3 = _now()  # A+B, lien présent

        # t0 : rien n'existe encore.
        at0 = await _graph_at(client, auth_headers, space_id, t0)
        assert at0["nodes"] == [] and at0["edges"] == []

        # t1 : A seul, stade input.
        at1 = await _graph_at(client, auth_headers, space_id, t1)
        assert [n["id"] for n in at1["nodes"]] == [a["id"]]
        assert at1["nodes"][0]["stage"] == "input"
        assert at1["edges"] == []

        # t2 : A est devenu projet, toujours seul.
        at2 = await _graph_at(client, auth_headers, space_id, t2)
        assert {n["id"]: n["stage"] for n in at2["nodes"]} == {a["id"]: "projet"}

        # t3 : A (projet) + B + le lien.
        at3 = await _graph_at(client, auth_headers, space_id, t3)
        assert {n["id"] for n in at3["nodes"]} == {a["id"], b["id"]}
        assert [e["id"] for e in at3["edges"]] == [edge["id"]]
        stage_a = next(n["stage"] for n in at3["nodes"] if n["id"] == a["id"])
        assert stage_a == "projet"
