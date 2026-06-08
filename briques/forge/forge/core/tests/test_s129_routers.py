"""S129 — routers agents spécialisés (LLM mocké via gateway) + montage des routes DB."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth import UserContext, get_current_user


def _fake_user():
    return UserContext(sub="11111111-1111-1111-1111-111111111111", nom="Bob",
                       avatar_emoji="🦊", org_id=None)


@pytest_asyncio.fixture
async def auth_client(monkeypatch):
    """Client avec auth overridée + generate_text mocké (pas d'appel gateway réel)."""
    from app.main import app as fastapi_app

    async def _fake_generate(prompt, system=None, provider=None, model=None, max_tokens=None):
        return f"[{provider or 'default'}] ok"

    # mocke le helper là où il est importé par chaque router
    for mod in ("conseil", "content_agent", "legal_agent", "seo_agent"):
        monkeypatch.setattr(f"app.routers.{mod}.generate_text", _fake_generate)

    fastapi_app.dependency_overrides[get_current_user] = _fake_user
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_conseil_caps_at_5_and_aggregates(auth_client):
    providers = [{"provider": f"p{i}", "model": "m"} for i in range(8)]
    r = await auth_client.post("/api/conseil", json={"prompt": "Hi", "providers": providers})
    assert r.status_code == 200
    responses = r.json()["responses"]
    assert len(responses) == 5  # cap à 5
    assert all(x["error"] is None and "ok" in x["answer"] for x in responses)
    assert "duree_ms" in responses[0]


@pytest.mark.asyncio
async def test_conseil_requires_prompt_and_providers(auth_client):
    r = await auth_client.post("/api/conseil", json={"prompt": "", "providers": []})
    assert r.status_code == 400
    assert r.json()["error"] == "prompt et providers requis"


@pytest.mark.asyncio
async def test_content_agent_generate(auth_client):
    r = await auth_client.post("/api/content-agent/generate",
                               json={"sujet": "Le café", "type": "tweet"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "tweet" and body["sujet"] == "Le café"
    assert "ok" in body["contenu"] and body["generatedAt"].endswith("Z")


@pytest.mark.asyncio
async def test_legal_templates_and_generate(auth_client):
    tpl = await auth_client.get("/api/legal-agent/templates")
    assert tpl.status_code == 200
    keys = {t["key"] for t in tpl.json()}
    assert {"nda", "cgv", "contrat_travail"} <= keys

    gen = await auth_client.post("/api/legal-agent/generate",
                                 json={"type": "nda", "parties": {"A": "Acme", "B": "Globex"}})
    assert gen.status_code == 200
    assert gen.json()["template"].startswith("Accord de Non-Divulgation")


@pytest.mark.asyncio
async def test_seo_keywords_fallback_on_non_json(auth_client):
    # generate_text mocké renvoie du texte non-JSON → fallback liste à 1 élément
    r = await auth_client.post("/api/seo-agent/keywords", json={"sujet": "running"})
    assert r.status_code == 200
    kw = r.json()["keywords"]
    assert kw == [{"keyword": "running", "volume": "moyen", "intention": "info", "difficulte": 5}]


@pytest.mark.asyncio
async def test_db_routes_are_mounted_native_not_proxied():
    """Sans auth, kb/memory/search renvoient 401 (montés nativement), pas un proxy Bun."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in ("/api/kb/articles", "/api/memory", "/api/search"):
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"
