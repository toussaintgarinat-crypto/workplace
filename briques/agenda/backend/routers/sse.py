"""SSE — stream temps réel des changements calendrier."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from auth import get_current_user, get_current_user_sse
from config import settings
from db import get_db
from models.orm import AvailabilityPoll
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


@router.get("/sse/polls/{share_token}")
async def poll_sse(
    share_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """SSE public d'un sondage — le `share_token` (query dans l'URL) EST la capacité, donc
    pas d'auth : quiconque a le lien de vote suit la grille en direct. On résout le jeton
    en poll_id (canal `poll:{id}:changes`) ; 404 silencieux via flux vide si jeton inconnu."""
    poll = (await db.execute(
        select(AvailabilityPoll).where(
            AvailabilityPoll.share_token == share_token))).scalar_one_or_none()
    poll_id = poll.id if poll else None

    async def _generator():
        if poll_id is None or not settings.REDIS_URL:
            yield {"data": json.dumps({"type": "connected", "poll": bool(poll_id)})}
            while not await request.is_disconnected():
                await asyncio.sleep(30)
                yield {"data": json.dumps({"type": "ping"})}
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = f"poll:{poll_id}:changes"
        await pubsub.subscribe(channel)
        yield {"data": json.dumps({"type": "connected", "poll": True})}
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield {"data": message["data"]}
        except Exception as exc:
            logger.warning("SSE error for poll %s: %s", poll_id, exc)
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


@router.get("/sse/presence")
async def presence_sse(
    request: Request,
    user: dict = Depends(get_current_user_sse),
):
    """SSE — changements de présence (partage/arrêt) en temps réel. Canal `presence:changes`."""

    async def _generator():
        if not settings.REDIS_URL:
            yield {"data": json.dumps({"type": "connected"})}
            while not await request.is_disconnected():
                await asyncio.sleep(30)
                yield {"data": json.dumps({"type": "ping"})}
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = "presence:changes"
        await pubsub.subscribe(channel)
        yield {"data": json.dumps({"type": "connected"})}
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield {"data": message["data"]}
        except Exception as exc:
            logger.warning("SSE error for presence: %s", exc)
        finally:
            await pubsub.unsubscribe(channel)
            await r.aclose()

    return EventSourceResponse(_generator())
