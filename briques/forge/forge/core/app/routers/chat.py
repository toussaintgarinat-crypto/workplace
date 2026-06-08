"""Router chat. Portage de chat.ts (S128). Monté /api/chat, protégé.

Exécution LLM via la **gateway** (remplace streamText du Vercel AI SDK). Le stream
SSE reproduit le protocole data-stream Vercel (`0:"<chunk>"`) au mieux — affinements
de protocole possibles au cutover S136 (le frontend ne vise core qu'à ce moment).
"""

from __future__ import annotations

import json
import logging
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.auth import get_current_user
from app.config import settings
from app.db import SessionLocal
from app.llm import LlmContext, gateway_model, resolve_llm_config
from app.models import Messages, Poles, Sessions, Ventures
from app.react_executor import get_context

logger = logging.getLogger(__name__)
router = APIRouter()

POLE_PERSONAS = {
    "finance": "You are the Finance AI of Forge. You specialize in budgets, forecasts, invoices, cash flow, OKRs, and financial reporting.",
    "marketing": "You are the Marketing AI of Forge. You specialize in campaigns, content, growth metrics, SEO, and brand strategy.",
    "sales": "You are the Sales AI of Forge. You specialize in CRM, lead qualification, pipeline management, and deal closing.",
    "ops": "You are the Operations AI of Forge. You specialize in project management, sprints, tasks, incidents, and process optimization.",
    "legal": "You are the Legal AI of Forge. You specialize in contracts, compliance, audit missions, and regulatory matters.",
    "dev": "You are the Dev AI of Forge. You specialize in code, architecture, CI/CD, and technical implementations.",
    "custom": "You are a specialized AI of Forge.",
}


class Message(BaseModel):
    sessionId: str
    content: str
    provider: str | None = None
    model: str | None = None


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


async def _resolve_session_context(session_id: str, provider, model):
    su = _uuid(session_id)
    resolved_provider, resolved_model = provider, model
    pole_ctx = venture_ctx = None
    async with SessionLocal() as s:
        session = (await s.execute(select(Sessions).where(Sessions.id == su))).scalar_one_or_none() if su else None
        if session and session.pole_id:
            pole = (await s.execute(select(Poles).where(Poles.id == session.pole_id))).scalar_one_or_none()
            if pole:
                pole_ctx = {"nom": pole.nom, "type": pole.type or "custom"}
            if not resolved_provider or not resolved_model:
                preset = await resolve_llm_config(LlmContext(pole_id=str(session.pole_id), venture_id=session.venture_id))
                if preset and preset.provider:
                    resolved_provider = preset.provider
                if preset and preset.model:
                    resolved_model = preset.model
        if session and session.venture_id and not pole_ctx:
            v = (await s.execute(select(Ventures).where(Ventures.id == _uuid(session.venture_id)))).scalar_one_or_none()
            if v:
                venture_ctx = {"nom": v.nom}
    return resolved_provider, resolved_model, pole_ctx, venture_ctx


def _build_system_prompt(context: str, pole_ctx, venture_ctx) -> str:
    parts = []
    if pole_ctx:
        persona = POLE_PERSONAS.get(pole_ctx["type"], POLE_PERSONAS["custom"])
        parts.append(f'{persona}\nYou are operating within the "{pole_ctx["nom"]}" pole.')
    elif venture_ctx:
        parts.append(f'You are Forge, an expert AI assistant operating within the venture "{venture_ctx["nom"]}".')
    else:
        parts.append("You are Forge, an expert AI assistant for the Swarm-Sentinel platform.")
    parts.append("Be concise, technical, and precise. Respond in the same language as the user.")
    if context:
        parts.append(f"\n## Project Context\n{context}\nBase your answers on the context when relevant.")
    return "\n".join(parts)


async def _save_and_prepare(body: Message):
    context = await get_context(body.content, body.sessionId)
    rp, rm, pole_ctx, venture_ctx = await _resolve_session_context(body.sessionId, body.provider, body.model)
    su = _uuid(body.sessionId)
    async with SessionLocal() as s:
        if su:
            s.add(Messages(session_id=su, role="user", content=body.content))
            await s.commit()
    return context, rp, rm, pole_ctx, venture_ctx, su


async def _persist_assistant(su, text: str):
    async with SessionLocal() as s:
        if su:
            s.add(Messages(session_id=su, role="assistant", content=text))
            await s.execute(update(Sessions).where(Sessions.id == su).values(updated_at=func.now()))
            await s.commit()


@router.post("")
async def chat(body: Message, user=Depends(get_current_user)):
    context, rp, rm, pole_ctx, venture_ctx, su = await _save_and_prepare(body)
    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)
    text = ""
    try:
        resp = await client.chat.completions.create(
            model=gateway_model(rp, rm),
            messages=[{"role": "system", "content": _build_system_prompt(context, pole_ctx, venture_ctx)},
                      {"role": "user", "content": body.content}],
        )
        text = resp.choices[0].message.content or ""
    except Exception as exc:  # parité Bun : échec LLM avalé → 200 contenu vide
        logger.warning("[chat] LLM call failed: %s", str(exc)[:160])
    await _persist_assistant(su, text)
    return {"content": text}


@router.post("/stream")
async def chat_stream(body: Message, user=Depends(get_current_user)):
    context, rp, rm, pole_ctx, venture_ctx, su = await _save_and_prepare(body)
    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)

    async def gen():
        full = ""
        try:
            stream = await client.chat.completions.create(
                model=gateway_model(rp, rm),
                messages=[{"role": "system", "content": _build_system_prompt(context, pole_ctx, venture_ctx)},
                          {"role": "user", "content": body.content}],
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    full += delta
                    yield f"0:{json.dumps(delta)}\n"
        finally:
            await _persist_assistant(su, full)
            yield f'd:{json.dumps({"finishReason": "stop"})}\n'

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
