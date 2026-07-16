"""Redis pub/sub — broadcast des changements calendrier aux clients SSE."""

from __future__ import annotations

import json
import logging

from config import settings

logger = logging.getLogger(__name__)


async def publish_change(calendar_id: str, event_type: str, payload: dict) -> None:
    if not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        msg = json.dumps({"type": event_type, "data": payload})
        await r.publish(f"calendar:{calendar_id}:changes", msg)
        await r.aclose()
    except Exception as exc:
        logger.warning("Redis publish failed: %s", exc)


async def publish_list_change(list_id: str, event_type: str, payload: dict) -> None:
    """Broadcast d'un changement de liste vers les clients SSE (canal dédié). Best-effort."""
    if not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        msg = json.dumps({"type": event_type, "data": payload})
        await r.publish(f"list:{list_id}:changes", msg)
        await r.aclose()
    except Exception as exc:
        logger.warning("Redis publish (list) failed: %s", exc)


async def publish_poll_change(poll_id: str, event_type: str, payload: dict) -> None:
    """Broadcast d'un changement de sondage (vote/finalisation) aux clients SSE. Best-effort."""
    if not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        msg = json.dumps({"type": event_type, "data": payload})
        await r.publish(f"poll:{poll_id}:changes", msg)
        await r.aclose()
    except Exception as exc:
        logger.warning("Redis publish (poll) failed: %s", exc)
