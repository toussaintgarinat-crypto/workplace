"""S181 — creer_setup_key POST /api/setup-keys (client NetBird), avec transport mocké."""
import asyncio
import json

import httpx
import pytest

import netbird


def test_creer_setup_key_ok(monkeypatch):
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "nbp_test")
    monkeypatch.setattr(netbird, "NETBIRD_INVITE_GROUP_ID", "grp1")
    monkeypatch.setattr(netbird, "NETBIRD_SETUP_KEY_EXPIRES", 3600)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"key": "AAAA-BBBB-CCCC", "expires": "2026-07-19T00:00:00Z", "name": "test"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(netbird.creer_setup_key("test", client=client))
    asyncio.run(client.aclose())

    assert res["key"] == "AAAA-BBBB-CCCC"
    assert captured["url"] == "https://api.netbird.io/api/setup-keys"
    assert captured["auth"] == "Token nbp_test"
    assert captured["body"] == {
        "name": "test", "type": "one-off", "expires_in": 3600,
        "usage_limit": 1, "auto_groups": ["grp1"], "ephemeral": False,
    }


def test_creer_setup_key_sans_token(monkeypatch):
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "")
    with pytest.raises(netbird.NetbirdError):
        asyncio.run(netbird.creer_setup_key("x"))


def test_creer_setup_key_erreur_api(monkeypatch):
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "nbp_test")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="token invalid")))
    with pytest.raises(netbird.NetbirdError):
        asyncio.run(netbird.creer_setup_key("x", client=client))
    asyncio.run(client.aclose())


def test_creer_setup_key_2xx_sans_key(monkeypatch):
    """Un 200 dont le corps n'a pas de « key » reste dans le contrat NetbirdError (pas de KeyError)."""
    monkeypatch.setattr(netbird, "NETBIRD_API_TOKEN", "nbp_test")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"oops": 1})))
    with pytest.raises(netbird.NetbirdError):
        asyncio.run(netbird.creer_setup_key("x", client=client))
    asyncio.run(client.aclose())
