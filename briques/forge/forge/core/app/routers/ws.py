"""Router WebSocket chat. Portage de routes/ws.ts (S134). Monté /api/ws/:sessionId.

Première route WebSocket native de core (les WS ne passent pas par le proxy
strangler — il est HTTP-only). Auth via ``?token=<jwt>`` (query string), puis
provisionnement utilisateur identique à ``ws.ts``.

Deux modes par message :
- standard : streaming gateway → frames ``{type:'chunk'}``.
- ``reactMode`` : boucle ReAct (``run_react``) → frames ``{type:'react_step'}``.

Note parité : les *skills* (matchesSkillTriggers/buildSkillsContext) restent
déférés depuis S128 (non portés) — comme ``chat.py``, on ne les charge pas.
Les compteurs in-memory ``metrics.*`` du Bun ne sont pas portés (domaine /metrics).
"""

from __future__ import annotations

import json
import logging
import uuid as uuidlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
from sqlalchemy import func, select, update

from app.auth import provision_ws_user
from app.config import settings
from app.db import SessionLocal
from app.llm import LlmContext, gateway_model, resolve_llm_config
from app.models import (
    AgentDefinitions,
    ForgePersonalities,
    Messages,
    Poles,
    Sessions,
    Ventures,
)
from app.react_executor import get_context, run_react

logger = logging.getLogger(__name__)
router = APIRouter()


def _uuid(v):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


def _build_system_prompt(rag_context, pole_ctx, venture_ctx, agent_personality) -> str:
    """Réplique buildSystemPrompt d'ws.ts (distinct des POLE_PERSONAS de chat.ts)."""
    parts: list[str] = []
    if agent_personality:
        parts.append(agent_personality)
        if pole_ctx:
            parts.append(f'You are operating within the "{pole_ctx["nom"]}" pole.')
        if venture_ctx:
            parts.append(f'Context: venture "{venture_ctx["nom"]}".')
    elif pole_ctx:
        parts.append(f'You are Forge, an expert AI assistant operating within the "{pole_ctx["nom"]}" pole.')
    elif venture_ctx:
        parts.append(f'You are Forge, an expert AI assistant operating within the venture "{venture_ctx["nom"]}".')
    else:
        parts.append("You are Forge, an expert AI assistant for the Swarm-Sentinel platform.")
    parts.append("Be concise, technical, and precise. Respond in the same language as the user.")
    if rag_context:
        parts.append(f"\n## Project Context\n{rag_context}\nBase your answers on the context when relevant.")
    return "\n".join(parts)


async def _resolve_agent(agent_id):
    """agentId → (nom, personality_prompt). Personnalité > instructions (comme ws.ts)."""
    aid = _uuid(agent_id)
    if aid is None:
        return None, None
    async with SessionLocal() as s:
        agent = (await s.execute(select(AgentDefinitions).where(AgentDefinitions.id == aid))).scalar_one_or_none()
        if agent is None:
            return None, None
        personality = None
        if agent.personality_id:
            perso = (
                await s.execute(select(ForgePersonalities).where(ForgePersonalities.id == agent.personality_id))
            ).scalar_one_or_none()
            if perso and perso.system_prompt:
                personality = perso.system_prompt
        if not personality and agent.instructions:
            personality = agent.instructions
        return agent.nom, personality


async def _resolve_session(session_id, provider, model):
    su = _uuid(session_id)
    rp, rm = provider, model
    pole_ctx = venture_ctx = None
    async with SessionLocal() as s:
        session = (await s.execute(select(Sessions).where(Sessions.id == su))).scalar_one_or_none() if su else None
        if session and session.pole_id:
            pole = (await s.execute(select(Poles).where(Poles.id == session.pole_id))).scalar_one_or_none()
            if pole:
                pole_ctx = {"nom": pole.nom, "type": pole.type or "custom"}
            if not rp or not rm:
                preset = await resolve_llm_config(LlmContext(pole_id=str(session.pole_id), venture_id=session.venture_id))
                if preset and preset.provider:
                    rp = preset.provider
                if preset and preset.model:
                    rm = preset.model
        if session and session.venture_id and not pole_ctx:
            v = (await s.execute(select(Ventures).where(Ventures.id == _uuid(session.venture_id)))).scalar_one_or_none()
            if v:
                venture_ctx = {"nom": v.nom}
    return rp, rm, pole_ctx, venture_ctx


async def _save_message(session_id, role, content):
    su = _uuid(session_id)
    async with SessionLocal() as s:
        if su:
            s.add(Messages(session_id=su, role=role, content=content))
            await s.commit()


async def _touch_session(session_id):
    su = _uuid(session_id)
    async with SessionLocal() as s:
        if su:
            await s.execute(update(Sessions).where(Sessions.id == su).values(updated_at=func.now()))
            await s.commit()


@router.websocket("/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str):
    token = websocket.query_params.get("token")
    user_id = await provision_ws_user(token)

    await websocket.accept()
    if not user_id:
        await websocket.send_text(json.dumps({"type": "error", "message": "Unauthorized"}))
        await websocket.close()
        return
    await websocket.send_text(json.dumps({"type": "connected", "sessionId": session_id}))

    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            content = (payload.get("content") or "").strip()
            if not content:
                continue
            provider = payload.get("provider")
            model = payload.get("model")
            react_mode = payload.get("reactMode")
            agent_id = payload.get("agentId")
            parent_execution_id = payload.get("parentExecutionId")

            await _save_message(session_id, "user", content)
            await websocket.send_text(json.dumps({"type": "thinking"}))

            agent_name, agent_personality = await _resolve_agent(agent_id)
            rp, rm, pole_ctx, venture_ctx = await _resolve_session(session_id, provider, model)

            if react_mode:
                async def on_step(step, ws=websocket):
                    await ws.send_text(json.dumps({"type": "react_step", "step": step}))

                try:
                    result = await run_react(
                        content, session_id, user_id, rp, rm,
                        skills_context=None, on_step=on_step,
                        personality_prompt=agent_personality, agent_name=agent_name,
                        depth=0, parent_execution_id=parent_execution_id,
                    )
                    await _save_message(session_id, "assistant", result.answer)
                    await _touch_session(session_id)
                    if result.actualModel:
                        await websocket.send_text(json.dumps({
                            "type": "actual_model", "model": result.actualModel,
                            "provider": result.actualProvider,
                        }))
                    await websocket.send_text(json.dumps({
                        "type": "done", "content": result.answer,
                        "steps": result.steps, "executionId": result.executionId,
                    }))
                except Exception as exc:
                    logger.warning("[ws:react] %s", str(exc)[:160])
                    await websocket.send_text(json.dumps({"type": "error", "message": "ReAct error"}))
                continue

            # ── Mode streaming standard ──────────────────────────────────
            rag = await get_context(content, session_id)
            system_prompt = _build_system_prompt(rag, pole_ctx, venture_ctx, agent_personality)
            full = ""
            try:
                stream = await client.chat.completions.create(
                    model=gateway_model(rp, rm),
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": content}],
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        full += delta
                        await websocket.send_text(json.dumps({"type": "chunk", "content": delta}))
                await _save_message(session_id, "assistant", full)
                await _touch_session(session_id)
                await websocket.send_text(json.dumps({"type": "done", "content": full}))
            except Exception as exc:
                logger.warning("[ws:stream] %s", str(exc)[:160])
                await websocket.send_text(json.dumps({"type": "error", "message": "LLM error"}))
    except WebSocketDisconnect:
        return
    except Exception as exc:  # défense : toute autre erreur ferme proprement
        logger.info("[ws] closing: %s", str(exc)[:120])
        try:
            await websocket.close()
        except Exception:
            pass
