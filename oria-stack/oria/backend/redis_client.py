"""Shim local — delegue au module partage agent_personnel_shared.redis_client.

Le client retourne par `redis_client` est automatiquement prefixe `oria:`
afin d'eviter les collisions entre services qui partagent la meme instance
Redis (S101).
"""

import os
from contextlib import asynccontextmanager

from agent_personnel_shared.redis_client import (
    close_redis,
    get_client as _get_client_shared,
    init_redis as _init_redis_shared,
    lock as _lock_shared,
    publish as _publish_shared,
)

NAMESPACE = "oria"


def _prefix(key: str) -> str:
    return key if key.startswith(f"{NAMESPACE}:") else f"{NAMESPACE}:{key}"


async def init_redis() -> bool:
    return await _init_redis_shared(os.getenv("REDIS_URL", ""))


@asynccontextmanager
async def lock(key: str, ttl: int = 30):
    async with _lock_shared(_prefix(key), ttl) as acquired:
        yield acquired


async def publish(channel: str, payload) -> bool:
    return await _publish_shared(_prefix(channel), payload)


def __getattr__(name: str):
    if name == "redis_client":
        return _get_client_shared(NAMESPACE)
    raise AttributeError(name)


__all__ = ["init_redis", "close_redis", "lock", "publish", "NAMESPACE"]
