"""Câblage S176 : routers exposent les bons chemins + main.py les enregistre et sème.

`import main` tire `agent_personnel_shared` (résolu seulement en conteneur) → on vérifie le
câblage par inspection des sources de main.py, comme test_manifest_capacites.py."""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MAIN = (BACKEND / "main.py").read_text()


def _paths(router):
    return {getattr(r, "path", "") for r in router.routes}


def test_routers_exposent_les_chemins():
    from routers.lists import router as lists_r
    from routers.list_items import router as items_r
    from routers.list_catalog import router as catalog_r
    from routers.loyalty import router as loyalty_r
    from routers.sse import router as sse_r
    assert "/lists" in _paths(lists_r)
    assert "/lists/{list_id}/items" in _paths(items_r)
    assert "/lists/{list_id}/catalog" in _paths(catalog_r)
    assert "/loyalty-cards" in _paths(loyalty_r)
    assert "/sse/lists/{list_id}" in _paths(sse_r)


def test_main_enregistre_les_routers():
    for r in ("lists_router", "list_items_router", "list_catalog_router", "loyalty_router"):
        assert f"app.include_router({r})" in MAIN, f"{r} non enregistré dans main.py"


def test_main_seme_le_catalogue():
    assert "semer_catalogue" in MAIN


def test_main_monte_le_static():
    assert "StaticFiles" in MAIN and "/static" in MAIN
