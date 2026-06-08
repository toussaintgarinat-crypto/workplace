"""Résolution des clés API providers (DB chiffrée → env), cache TTL.

Réplique ``forge/core/src/config/keystore.ts``. Le cache est par-process (comme le
Bun) ; ``invalidate_cache`` est appelé après un PUT/DELETE de clé.
"""

from __future__ import annotations

import os
import time

from sqlalchemy import select

from app.crypto import decrypt
from app.db import SessionLocal
from app.models import ProviderApiKeys

ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}

_TTL_S = 60.0
_cache: dict[str, tuple[str, float]] = {}


def _ck(user_id: str, provider: str) -> str:
    return f"{user_id}:{provider}"


async def resolve_key(user_id: str, provider: str) -> str | None:
    ck = _ck(user_id, provider)
    cached = _cache.get(ck)
    if cached and (time.monotonic() - cached[1]) < _TTL_S:
        return cached[0]

    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ProviderApiKeys).where(
                    ProviderApiKeys.user_id == user_id,
                    ProviderApiKeys.provider == provider,
                )
            )
        ).scalar_one_or_none()

    if row and row.encrypted_key:
        try:
            value = decrypt(row.encrypted_key)
            _cache[ck] = (value, time.monotonic())
            return value
        except Exception:
            pass  # clé corrompue → fallback env

    env_value = os.getenv(ENV_MAP.get(provider, ""))
    if env_value:
        _cache[ck] = (env_value, time.monotonic())
    return env_value


def invalidate_cache(user_id: str, provider: str) -> None:
    _cache.pop(_ck(user_id, provider), None)
