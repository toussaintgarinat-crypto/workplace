"""
Yjs CRDT WebSocket server for Oria shared zones.

Implements the y-websocket binary protocol (lib0 varints):
  [0][0][len][state_vector]   → syncStep1
  [0][1][len][update]         → syncStep2
  [0][2][len][update]         → update (broadcast)
  [1][len][awareness_state]   → awareness (relay)

Requires y-py: pip install y-py
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

try:
    import y_py as Y
    _YJS_OK = True
except ImportError:
    _YJS_OK = False


# ── lib0 varint encoding ─────────────────────────────────────────

def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    result, shift = 0, 0
    while offset < len(data):
        b = data[offset]; offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, offset
        shift += 7
    return result, offset


def _write_varint(n: int) -> bytes:
    out = []
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            break
    return bytes(out)


def _make_sync(sync_type: int, payload: bytes) -> bytes:
    return (_write_varint(0) + _write_varint(sync_type)
            + _write_varint(len(payload)) + payload)


# ── In-memory state per zone ─────────────────────────────────────

_docs:    Dict[str, "Y.YDoc"]       = {}
_clients: Dict[str, Set[WebSocket]] = {}
_locks:   Dict[str, asyncio.Lock]   = {}


def _ydoc(zone_id: str) -> "Y.YDoc":
    if zone_id not in _docs:
        _docs[zone_id] = Y.YDoc()
    return _docs[zone_id]


def _lock(zone_id: str) -> asyncio.Lock:
    if zone_id not in _locks:
        _locks[zone_id] = asyncio.Lock()
    return _locks[zone_id]


async def _broadcast(zone_id: str, msg: bytes, exclude: Optional[WebSocket] = None) -> None:
    dead = []
    for ws in list(_clients.get(zone_id, set())):
        if ws is exclude:
            continue
        try:
            await ws.send_bytes(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.get(zone_id, set()).discard(ws)


# ── Main handler — mount as FastAPI WebSocket route ──────────────

async def yjs_websocket_handler(websocket: WebSocket, zone_id: str) -> None:
    await websocket.accept()

    if not _YJS_OK:
        await websocket.close(code=1011, reason="y-py not installed")
        return

    _clients.setdefault(zone_id, set()).add(websocket)
    doc  = _ydoc(zone_id)
    lock = _lock(zone_id)

    # Initiate sync: push our state vector (syncStep1)
    async with lock:
        sv = Y.encode_state_vector(doc)
    await websocket.send_bytes(_make_sync(0, sv))

    try:
        while True:
            raw = await websocket.receive_bytes()
            if not raw:
                continue

            msg_type, pos = _read_varint(raw, 0)

            if msg_type == 0:  # sync message
                sync_type, pos  = _read_varint(raw, pos)
                payload_len, pos = _read_varint(raw, pos)
                payload = raw[pos: pos + payload_len]

                if sync_type == 0:  # step1 → reply with step2 (our diff)
                    async with lock:
                        diff = Y.encode_state_as_update(doc, payload)
                    await websocket.send_bytes(_make_sync(1, diff))

                elif sync_type in (1, 2):  # step2 / update → apply + broadcast
                    if payload:
                        async with lock:
                            Y.apply_update(doc, payload)
                        await _broadcast(zone_id, _make_sync(2, payload), exclude=websocket)

            elif msg_type == 1:  # awareness → relay verbatim
                await _broadcast(zone_id, raw)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _clients.get(zone_id, set()).discard(websocket)
