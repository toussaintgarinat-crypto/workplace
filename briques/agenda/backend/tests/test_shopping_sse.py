"""publish_list_change : no-op sans Redis, canal correct avec Redis mocké."""
from __future__ import annotations

import pytest

from config import settings
from services import pubsub


@pytest.mark.asyncio
async def test_publish_noop_sans_redis(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    # Ne doit pas lever ni tenter de connexion.
    await pubsub.publish_list_change("l1", "item.added", {"id": "x"})


@pytest.mark.asyncio
async def test_publish_canal_liste(monkeypatch):
    aioredis = pytest.importorskip("redis.asyncio")  # redis absent en dev pur → skip
    envois = {}

    class FakeRedis:
        async def publish(self, channel, msg):
            envois["channel"] = channel
            envois["msg"] = msg

        async def aclose(self):
            pass

    monkeypatch.setattr(settings, "REDIS_URL", "redis://x", raising=False)
    monkeypatch.setattr(aioredis, "from_url", lambda url: FakeRedis())

    await pubsub.publish_list_change("l1", "item.checked", {"id": "x"})
    assert envois["channel"] == "list:l1:changes"
    assert "item.checked" in envois["msg"]
