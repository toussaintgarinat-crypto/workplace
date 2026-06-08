"""Proxy S2S vers le service Calendar (port 8400) — Sprint 107."""

from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from config import config
from routers.auth import get_current_user

router = APIRouter()


def _s2s_headers(user_id: str) -> dict[str, str]:
    headers: dict[str, str] = {"X-User-Id": user_id}
    if config.CALENDAR_SERVICE_TOKEN:
        headers["Authorization"] = f"Bearer {config.CALENDAR_SERVICE_TOKEN}"
    return headers


async def _forward(method: str, path: str, user_id: str, **kwargs: Any) -> Any:
    url = f"{config.CALENDAR_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.request(method, url, headers=_s2s_headers(user_id), **kwargs)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@router.get("/events")
async def list_events(
    calendar_id: str = Query(...),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    params: dict[str, str] = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return await _forward("GET", f"/calendars/{calendar_id}/events", user["sub"], params=params)


@router.post("/events", status_code=201)
async def create_event(
    calendar_id: str = Query(...),
    body: dict = ...,
    user: dict = Depends(get_current_user),
):
    return await _forward("POST", f"/calendars/{calendar_id}/events", user["sub"], json=body)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: str,
    body: dict,
    user: dict = Depends(get_current_user),
):
    return await _forward("PATCH", f"/events/{event_id}", user["sub"], json=body)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    user: dict = Depends(get_current_user),
):
    await _forward("DELETE", f"/events/{event_id}", user["sub"])
