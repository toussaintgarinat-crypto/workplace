"""Router clés API providers. Portage de routes/api-keys.ts (S127).

Monté sur /api/settings/api-keys (+ /v1/...). Protégé.
Chiffrement compatible Bun (app.crypto) — DB partagée.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth import UserContext, get_current_user
from app.crypto import encrypt, mask_key
from app.db import SessionLocal
from app.keystore import invalidate_cache
from app.models import ProviderApiKeys
from app.serde import iso

router = APIRouter()

PROVIDERS = [
    {"id": "openai", "label": "OpenAI", "placeholder": "sk-...", "url": "https://platform.openai.com/api-keys"},
    {"id": "anthropic", "label": "Anthropic", "placeholder": "sk-ant-...", "url": "https://console.anthropic.com/settings/keys"},
    {"id": "gemini", "label": "Gemini", "placeholder": "AIza...", "url": "https://aistudio.google.com/app/apikey"},
    {"id": "mistral", "label": "Mistral", "placeholder": "xxxxxxxx...", "url": "https://console.mistral.ai/api-keys"},
    {"id": "groq", "label": "Groq", "placeholder": "gsk_...", "url": "https://console.groq.com/keys"},
    {"id": "deepseek", "label": "DeepSeek", "placeholder": "sk-...", "url": "https://platform.deepseek.com/api_keys"},
    {"id": "openrouter", "label": "OpenRouter", "placeholder": "sk-or-...", "url": "https://openrouter.ai/keys"},
    {"id": "elevenlabs", "label": "ElevenLabs", "placeholder": "sk_...", "url": "https://elevenlabs.io/app/speech-synthesis"},
    {"id": "deepgram", "label": "Deepgram", "placeholder": "Token xxxxxxxx", "url": "https://console.deepgram.com/project"},
    {"id": "ollama", "label": "Ollama", "placeholder": "http://localhost:11434", "url": ""},
    {"id": "stripe", "label": "Stripe (clé secrète)", "placeholder": "sk_test_... / sk_live_...", "url": "https://dashboard.stripe.com/apikeys"},
    {"id": "smtp", "label": "SMTP (mot de passe)", "placeholder": "mot de passe d'application", "url": ""},
]
_PROVIDER_IDS = {p["id"] for p in PROVIDERS}


def _env_key(provider_id: str) -> str | None:
    # Réplique le `??` (nullish) du Bun : "" (défini) NE retombe PAS sur le fallback.
    v = os.getenv(f"{provider_id.upper()}_API_KEY")
    return v if v is not None else os.getenv("OLLAMA_BASE_URL")


class PutKey(BaseModel):
    key: str = Field(min_length=1)


@router.get("")
async def list_keys(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(ProviderApiKeys).where(ProviderApiKeys.user_id == user.sub))
        ).scalars().all()
    configured = {r.provider: r for r in rows}

    result = []
    for p in PROVIDERS:
        row = configured.get(p["id"])
        env_key = _env_key(p["id"])
        result.append(
            {
                **p,
                "configured": bool(row),
                "fromEnv": (not row) and bool(env_key),
                "hint": (row.hint if row else "") or "",
                "updatedAt": iso(row.updated_at) if row else None,
            }
        )
    return result


@router.put("/{provider}")
async def put_key(provider: str, body: PutKey, user: UserContext = Depends(get_current_user)):
    if provider not in _PROVIDER_IDS:
        raise HTTPException(status_code=400, detail="Unknown provider")
    encrypted = encrypt(body.key)
    hint = mask_key(body.key)
    async with SessionLocal() as session:
        stmt = pg_insert(ProviderApiKeys).values(
            user_id=user.sub, provider=provider, encrypted_key=encrypted, hint=hint
        )
        # upsert sur (user_id, provider) — à l'update on force updated_at = now()
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProviderApiKeys.user_id, ProviderApiKeys.provider],
            set_={"encrypted_key": encrypted, "hint": hint, "updated_at": func.now()},
        )
        await session.execute(stmt)
        await session.commit()
    invalidate_cache(user.sub, provider)
    return {"ok": True, "hint": hint}


@router.delete("/{provider}")
async def delete_key(provider: str, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as session:
        await session.execute(
            sa_delete(ProviderApiKeys).where(
                ProviderApiKeys.user_id == user.sub, ProviderApiKeys.provider == provider
            )
        )
        await session.commit()
    invalidate_cache(user.sub, provider)
    return {"ok": True}
