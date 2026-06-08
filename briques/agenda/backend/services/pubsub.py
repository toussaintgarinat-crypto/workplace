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
