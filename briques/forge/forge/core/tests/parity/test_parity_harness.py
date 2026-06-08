"""Tests unitaires du harnais de parité (la logique du filet de sécurité)."""

import pytest

from tests.parity.harness import (
    DEFAULT_IGNORE_KEYS,
    ParityResult,
    compare,
    normalize_json,
)


def test_normalize_drops_ignored_keys():
    a = {"id": "x1", "nom": "Acme", "created_at": "2026-01-01"}
    b = {"id": "x2", "nom": "Acme", "created_at": "2026-02-02"}
    assert normalize_json(a, DEFAULT_IGNORE_KEYS) == normalize_json(b, DEFAULT_IGNORE_KEYS)


def test_normalize_sorts_scalar_lists():
    assert normalize_json([3, 1, 2]) == normalize_json([1, 2, 3])


def test_normalize_preserves_object_list_order():
    objs = [{"k": 1}, {"k": 2}]
    assert normalize_json(objs) == [{"k": 1}, {"k": 2}]


def test_normalize_is_recursive():
    a = {"data": {"id": 1, "v": 10}, "list": [{"id": 9, "x": 1}]}
    b = {"data": {"id": 2, "v": 10}, "list": [{"id": 8, "x": 1}]}
    assert normalize_json(a, DEFAULT_IGNORE_KEYS) == normalize_json(b, DEFAULT_IGNORE_KEYS)


def test_parity_result_ok_and_str():
    ok = ParityResult("GET", "/x", 200, 200)
    assert ok.ok
    assert "PARITY OK" in str(ok)

    bad = ParityResult("GET", "/x", 200, 500, diffs=["status: py=200 ≠ bun=500"])
    assert not bad.ok
    assert "PARITY FAIL" in str(bad)


@pytest.mark.asyncio
async def test_compare_detects_status_and_body_diff(client):
    """compare() détecte un écart de status/body via mock httpx (respx)."""
    import respx
    from httpx import Response

    with respx.mock:
        # Python: /health natif (200) ; Bun mocké renvoie 404 → diff de status attendu
        respx.get("http://localhost:3001/health").mock(return_value=Response(200, json={"status": "ok"}))
        respx.get("http://bun.test/health").mock(return_value=Response(404, json={"error": "nope"}))

        result = await compare(
            client,
            "http://bun.test",
            method="GET",
            path="/health",
            compare_body=False,
        )
        assert not result.ok
        assert result.status_py == 200
        assert result.status_bun == 404
