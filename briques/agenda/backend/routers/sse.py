"""SSE — stream temps réel des changements calendrier."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, get_current_user_sse
from config import settings
from db import get_db
from utils.access import require_list_access

router = APIRouter(tags=["sse"])
logger = logging.getLogger(__name__)


@router.get("/sse/calendars/{cal_id}")
async def calendar_sse(
    cal_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """SSE stream — émet les changements (event.created/updated/deleted) en temps réel."""

    async def _generator():
        if not settings.REDIS_URL:
            yield {"data": json.dumps({"type": "connected", "calendar_id": cal_id})}
            while not await request.is_disconnected():
                await asyncio.sleep(30)
                yield {"data": json.dumps({"type": "ping"})}
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = f"calendar:{cal_id}:changes"
        await pubsub.subscribe(channel)
        yield {"data": json.dumps({"type": "connected", "calendar_id": cal_id})}
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield {"data": message["data"]}
        except Exception as exc:
            logger.warning("SSE error for calendar %s: %s", cal_id, exc)
        finally:
            await pubsub.unsubscribe(channel)
            await r.aclose()

    return EventSourceResponse(_generator())


@router.get("/sse/lists/{list_id}")
async def list_sse(
    list_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user_sse),
):
    """SSE stream — changements d'une liste (item.added/checked/…) en temps réel."""
    await require_list_access(db, list_id, user["sub"], min_role="viewer")

    async def _generator():
        if not settings.REDIS_URL:
            yield {"data": json.dumps({"type": "connected", "list_id": list_id})}
            while not await request.is_disconnected():
                await asyncio.sleep(30)
                yield {"data": json.dumps({"type": "ping"})}
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = f"list:{list_id}:changes"
        await pubsub.subscribe(channel)
        yield {"data": json.dumps({"type": "connected", "list_id": list_id})}
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield {"data": message["data"]}
        except Exception as exc:
            logger.warning("SSE error for list %s: %s", list_id, exc)
        finally:
            await pubsub.unsubscribe(channel)
            await r.aclose()

    return EventSourceResponse(_generator())
