"""Client MCP (Model Context Protocol) — portage de mcp/client.ts (S135).

Appels JSON-RPC 2.0 vers un serveur MCP distant (``tools/list`` et ``tools/call``)
via httpx. Auth optionnelle bearer/basic. Utilisé par le router mcp.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


def _headers(server) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    auth_type = server.auth_type or "none"
    token = server.auth_token or ""
    if auth_type == "bearer":
        h["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        h["Authorization"] = f"Basic {token}"
    return h


async def list_mcp_tools(server) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            server.url, headers=_headers(server),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    if res.status_code >= 400:
        raise RuntimeError(f"MCP list failed: {res.status_code}")
    data = res.json()
    return (data.get("result") or {}).get("tools") or []


async def call_mcp_tool(server, tool_name: str, args: dict[str, Any]) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            server.url, headers=_headers(server),
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool_name, "arguments": args},
            },
        )
    if res.status_code >= 400:
        raise RuntimeError(f"MCP call failed: {res.status_code}")
    data = res.json()
    result = data.get("result")
    content = (result or {}).get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        return "\n".join(c.get("text") if isinstance(c, dict) and c.get("text") else json.dumps(c)
                         for c in content)
    return json.dumps(result if result is not None else data)
