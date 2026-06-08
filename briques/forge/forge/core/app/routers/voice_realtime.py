"""Router WebSocket voice realtime. Portage de routes/voice-realtime.ts (S134).

Monté /api/voice/realtime. Proxy bidirectionnel transparent vers l'API OpenAI
Realtime (``wss://api.openai.com/v1/realtime``). Auth via ``?token=<jwt>`` ; le
client ne voit jamais la clé OpenAI (injectée côté serveur, sous-protocole WS).

Pas de provisionnement utilisateur (comme voice-realtime.ts : simple vérification
du token). Les frames sont relayées telles quelles dans les deux sens.
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import verify_ws_token
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/realtime")
async def voice_realtime(websocket: WebSocket):
    token = websocket.query_params.get("token")
    model = websocket.query_params.get("model") or "gpt-4o-realtime-preview"

    payload = await verify_ws_token(token)
    await websocket.accept()
    if payload is None:
        await websocket.send_text(json.dumps({"type": "error", "message": "Unauthorized"}))
        await websocket.close()
        return

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        await websocket.send_text(json.dumps({"type": "error", "message": "OPENAI_API_KEY non configuré"}))
        await websocket.close()
        return

    upstream_url = f"wss://api.openai.com/v1/realtime?model={model}"
    subprotocols = ["realtime", f"openai-insecure-api-key.{api_key}", "openai-beta.realtime-v1"]

    try:
        async with websockets.connect(upstream_url, subprotocols=subprotocols, max_size=None) as openai_ws:
            await websocket.send_text(json.dumps({"type": "realtime.connected", "model": model}))

            async def client_to_openai():
                while True:
                    msg = await websocket.receive_text()
                    await openai_ws.send(msg)

            async def openai_to_client():
                async for msg in openai_ws:
                    if isinstance(msg, bytes):
                        await websocket.send_bytes(msg)
                    else:
                        await websocket.send_text(msg)

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_openai()), asyncio.create_task(openai_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.info("[voice:realtime] %s", str(exc)[:160])
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "OpenAI Realtime connection failed"}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
