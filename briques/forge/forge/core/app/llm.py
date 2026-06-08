"""Couche LLM — portage de llm/index.ts (S128), SANS Vercel AI SDK.

Tout passe désormais par la **LiteLLM Gateway** (OpenAI-compatible) : un provider
Forge (ollama/openai/anthropic/…) + un modèle → une chaîne modèle gateway
``"<provider>/<model>"`` (cf. liste `gateway` d'AVAILABLE_PROVIDERS). Le client
OpenAI async cible la gateway. Cela supprime la dépendance aux SDK providers.

`resolve_llm_config` réplique la résolution de preset hiérarchique du Bun
(agent → tool → pole → venture → global org).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select

from app.db import SessionLocal
from app.models import AgentDefinitions, LlmPresets, Poles, PoleTools

# Identique à AVAILABLE_PROVIDERS du Bun (llm/index.ts).
AVAILABLE_PROVIDERS = [
    {"id": "ollama", "label": "Ollama (local)",
     "models": ["llama3.3", "llama3.2", "gemma3", "qwen2.5", "phi4", "deepseek-r1", "mistral", "phi3", "gemma2"]},
    {"id": "lmstudio", "label": "LM Studio (local)", "models": ["local-model"]},
    {"id": "anthropic", "label": "Anthropic",
     "models": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"]},
    {"id": "openai", "label": "OpenAI",
     "models": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o4-mini", "o3"]},
    {"id": "groq", "label": "Groq",
     "models": ["llama-4-scout-17b-16e-instruct", "llama-4-maverick-17b-128e-instruct",
                "llama-3.3-70b-versatile", "qwen-qwq-32b", "gemma2-9b-it"]},
    {"id": "gemini", "label": "Gemini",
     "models": ["gemini-2.5-pro", "gemini-2.5-flash-preview", "gemini-2.0-flash", "gemini-1.5-pro"]},
    {"id": "mistral", "label": "Mistral",
     "models": ["mistral-large-latest", "codestral-latest", "ministral-8b-latest", "mistral-small-latest"]},
    {"id": "deepseek", "label": "DeepSeek", "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "openrouter", "label": "OpenRouter",
     "models": ["openai/gpt-4.1", "openai/gpt-4o", "anthropic/claude-sonnet-4-6",
                "meta-llama/llama-4-maverick", "google/gemini-2.5-pro", "deepseek/deepseek-r1", "qwen/qwq-32b"]},
    {"id": "gateway", "label": "LiteLLM Gateway",
     "models": ["openai/gpt-4o", "openai/gpt-4o-mini", "anthropic/claude-sonnet-4-6",
                "google/gemini-2.5-flash-preview", "ollama/llama3.2", "ollama/llama3.3"]},
]


def gateway_model(provider: str | None, model: str | None) -> str:
    """provider+model Forge → chaîne modèle LiteLLM Gateway."""
    from app.config import settings

    p = provider or settings.DEFAULT_LLM_PROVIDER
    m = model or settings.DEFAULT_LLM_MODEL
    # 'gateway'/'openrouter' portent déjà un préfixe "vendor/model".
    if p in ("gateway", "openrouter") or "/" in (m or ""):
        return m
    return f"{p}/{m}"


async def generate_text(
    prompt: str,
    system: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """One-shot complétion via la gateway (remplace `generateText` du Vercel AI SDK).

    Utilisé par les agents spécialisés (conseil/content/legal/seo). Renvoie le texte.
    """
    from openai import AsyncOpenAI

    from app.config import settings

    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs: dict = {"model": gateway_model(provider, model), "messages": messages}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


@dataclass
class LlmContext:
    agent_id: str | None = None
    tool_key: str | None = None
    pole_id: str | None = None
    venture_id: str | None = None
    org_id: str | None = None


async def resolve_llm_config(ctx: LlmContext):
    """Résolution hiérarchique du preset (agent→tool→pole→venture→global). Renvoie la row ou None."""
    import uuid as uuidlib

    def as_uuid(v):
        try:
            return uuidlib.UUID(v)
        except (ValueError, TypeError):
            return None

    async with SessionLocal() as s:
        checks: list[tuple[str, str]] = []

        if ctx.agent_id:
            checks.append(("agent", ctx.agent_id))
            if not ctx.pole_id and as_uuid(ctx.agent_id):
                a = (await s.execute(select(AgentDefinitions.pole_id).where(AgentDefinitions.id == as_uuid(ctx.agent_id)))).first()
                if a and a[0]:
                    ctx.pole_id = str(a[0])

        if ctx.tool_key and ctx.pole_id and as_uuid(ctx.pole_id):
            pt = (await s.execute(
                select(PoleTools.id).where(and_(PoleTools.pole_id == as_uuid(ctx.pole_id), PoleTools.tool_key == ctx.tool_key))
            )).first()
            if pt:
                checks.append(("tool", str(pt[0])))

        if ctx.pole_id:
            checks.append(("pole", ctx.pole_id))
            if not ctx.venture_id and as_uuid(ctx.pole_id):
                p = (await s.execute(select(Poles.venture_id).where(Poles.id == as_uuid(ctx.pole_id)))).first()
                if p and p[0]:
                    ctx.venture_id = p[0]

        if ctx.venture_id:
            checks.append(("venture", ctx.venture_id))

        for scope_type, scope_id in checks:
            preset = (await s.execute(
                select(LlmPresets).where(and_(LlmPresets.scope_type == scope_type, LlmPresets.scope_id == scope_id))
            )).scalar_one_or_none()
            if preset:
                return preset

        if ctx.org_id:
            g = (await s.execute(
                select(LlmPresets).where(and_(LlmPresets.scope_type == "global", LlmPresets.scope_id == ctx.org_id))
            )).scalar_one_or_none()
            if g:
                return g

    return None
