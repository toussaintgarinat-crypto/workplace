"""
WebSocket connection manager pour le Conductor — broadcast des statuts agents.
"""
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set


class ConductorManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, payload: dict):
        message = json.dumps(payload)
        dead = set()
        async with self._lock:
            snapshot = set(self._connections)
        for ws in snapshot:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._lock:
                self._connections -= dead


conductor_manager = ConductorManager()
