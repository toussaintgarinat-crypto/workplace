"""S179 — le flux SSE présence émet un 'connected' initial (sans Redis en test)."""
from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from config import settings
from routers import sse


class _Req:
    async def is_disconnected(self):
        return True


@pytest.mark.asyncio
async def test_sse_presence_emet_connected(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    resp = await sse.presence_sse(request=_Req(), user={"sub": "alice"})
    gen = resp.body_iterator
    premier = await gen.__anext__()
    data = json.loads(premier["data"])
    assert data["type"] == "connected"
