"""S134 — montage natif des routes temps réel (push, webhooks, voice).

Les routes HTTP exigent l'auth (401 sans token) → preuve de montage natif, pas
proxy Bun. Les WebSockets (ws, voice-realtime) refusent proprement sans token
valide (frame d'erreur + close), sans toucher la DB ni l'amont.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

GET_ROUTES = [
    "/api/push/subscriptions",
    "/api/webhooks",
]

POST_ROUTES = [
    "/api/push/subscribe",
    "/api/push/send",
    "/api/webhooks",
    "/api/voice/synthesize",
]


@pytest.mark.asyncio
async def test_s134_http_routes_mounted_native_401():
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in GET_ROUTES:
            r = await c.get(path)
            assert r.status_code == 401, f"GET {path} → {r.status_code}"
        for path in POST_ROUTES:
            r = await c.post(path, json={})
            assert r.status_code == 401, f"POST {path} → {r.status_code}"
        # alias canonique /v1/api monté nativement
        for path in ("/v1/api/push/subscriptions", "/v1/api/webhooks"):
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}"


@pytest.mark.asyncio
async def test_voice_transcribe_no_token_401():
    """STT multipart : sans token → 401 (auth router-level), avant tout appel amont."""
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/voice/transcribe", files={"audio": ("a.webm", b"x", "audio/webm")})
        assert r.status_code == 401


def test_ws_chat_rejects_without_token():
    """WS /api/ws/:id sans token → accept puis frame error 'Unauthorized' + close."""
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as tc:
        with tc.websocket_connect("/api/ws/sess-1") as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"type": "error", "message": "Unauthorized"}


def test_voice_realtime_rejects_without_token():
    """WS /api/voice/realtime sans token → frame error 'Unauthorized' + close."""
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as tc:
        with tc.websocket_connect("/api/voice/realtime") as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"type": "error", "message": "Unauthorized"}
