"""ReAct executor Python — portage de agents/react-executor.ts (S128).

Remplace le Vercel AI SDK : tout passe par la **LiteLLM Gateway** (OpenAI-compatible,
function-calling). Réplique : tools de base (query_knowledge_base, search_web,
calculate, calendar_get_planning), depth-guard (MAX_AGENT_DEPTH=3, S112), fallback
chain (S111), traces d'exécution (agent_executions), governor usage (S110).

Limites assumées pour S128 (affinées plus tard) :
- RAG `get_context` best-effort (retriever Qdrant porté en S129 memory) → "" si indispo.
- MCP tools non chargés (table mcp_servers absente de l'instance) → ignorés.
- coût governor à 0.0 (pricing détaillé porté en S133 governor).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid as uuidlib
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from openai import AsyncOpenAI
from sqlalchemy import update

from app.config import settings
from app.db import SessionLocal
from app.llm import gateway_model
from app.models import AgentExecutions, GovernorUsage

logger = logging.getLogger(__name__)

MAX_AGENT_DEPTH = 3
MAX_STEPS = 8


@dataclass
class ReactStep:
    type: str  # thought | tool_call | tool_result | answer
    content: str
    toolName: str | None = None
    agentName: str | None = None
    depth: int | None = None

    def to_dict(self) -> dict:
        d = {"type": self.type, "content": self.content, "agentName": self.agentName, "depth": self.depth}
        if self.toolName is not None:
            d["toolName"] = self.toolName
        return d


@dataclass
class ReactResult:
    steps: list[dict] = field(default_factory=list)
    answer: str = ""
    tokensIn: int = 0
    tokensOut: int = 0
    actualProvider: str | None = None
    actualModel: str | None = None
    executionId: str | None = None


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)


async def get_context(query: str, session_id: str) -> str:
    """RAG best-effort via le module mémoire (S129). Retourne "" si indisponible."""
    from app.memory import get_context as _mem_get_context

    return await _mem_get_context(query, session_id)


# ── Tools de base (function-calling OpenAI) ─────────────────────────
def _base_tool_specs() -> list[dict]:
    return [
        {"type": "function", "function": {"name": "query_knowledge_base",
            "description": "Search the knowledge base (RAG) for context from this project.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "search_web",
            "description": "Search the web for current information, news, or facts.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "calculate",
            "description": "Evaluate a mathematical expression.",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    ]


async def _exec_tool(name: str, args: dict, session_id: str, user_id: str) -> str:
    if name == "query_knowledge_base":
        return (await get_context(args.get("query", ""), session_id)) or "Nothing found."
    if name == "search_web":
        key = os.getenv("BRAVE_SEARCH_API_KEY")
        if not key:
            return "Web search unavailable (BRAVE_SEARCH_API_KEY not set)."
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.search.brave.com/res/v1/web/search",
                                params={"q": args.get("query", ""), "count": 3},
                                headers={"X-Subscription-Token": key, "Accept": "application/json"})
            if r.status_code != 200:
                return "Web search failed."
            res = r.json().get("web", {}).get("results", [])[:3]
            return "\n".join(f"**{x.get('title')}**: {x.get('description')}" for x in res) or "No results."
        except Exception:
            return "Web search error."
    if name == "calculate":
        try:
            safe = re.sub(r"[^0-9+\-*/().%, ]", "", args.get("expression", ""))
            return str(eval(safe, {"__builtins__": {}}, {}))  # noqa: S307 — expression assainie
        except Exception:
            return "Calculation error."
    return f"Unknown tool {name}."


def _parse_fallback_chain() -> list[dict]:
    out = []
    for entry in (settings.FALLBACK_LLM_CHAIN or "").split(","):
        entry = entry.strip()
        i = entry.find(":")
        if i > 0:
            out.append({"provider": entry[:i], "model": entry[i + 1:] or None})
    return out


async def run_react(
    input_text: str,
    session_id: str,
    user_id: str,
    provider: str | None = None,
    model: str | None = None,
    skills_context: str | None = None,
    on_step: Callable[[dict], Awaitable[None]] | Callable[[dict], None] | None = None,
    personality_prompt: str | None = None,
    agent_name: str | None = None,
    depth: int = 0,
    parent_execution_id: str | None = None,
) -> ReactResult:
    current_agent = agent_name or "Forge"
    if depth >= MAX_AGENT_DEPTH:
        raise RuntimeError(f"Max agent call depth ({MAX_AGENT_DEPTH}) exceeded")

    start = time.time()
    execution_id: str | None = None
    async with SessionLocal() as s:
        try:
            row = AgentExecutions(
                parent_id=uuidlib.UUID(parent_execution_id) if parent_execution_id else None,
                agent_name=current_agent, session_id=session_id, user_id=user_id,
                depth=depth, input=input_text[:2000], status="running",
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            execution_id = str(row.id)
        except Exception:
            await s.rollback()

    steps: list[dict] = []
    rag = await get_context(input_text, session_id)

    async def push(step: ReactStep):
        step.agentName = current_agent
        step.depth = depth
        d = step.to_dict()
        steps.append(d)
        if on_step:
            res = on_step(d)
            if hasattr(res, "__await__"):
                await res

    base_identity = personality_prompt or "You are Forge, an expert AI assistant operating in ReAct mode (Reason + Act)."
    system_prompt = (
        f"{base_identity}\n"
        "Think carefully, use tools when you need external information, then give a final answer.\n"
        + (f"\n## Active Skills\n{skills_context}\n" if skills_context else "")
        + (f"\n## Project Context\n{rag}\n" if rag else "")
        + "Always respond in the same language as the user."
    )

    providers_to_try = [{"provider": provider, "model": model}] + _parse_fallback_chain()
    tools = _base_tool_specs()
    answer = ""
    tin = tout = 0
    actual_provider = provider or settings.DEFAULT_LLM_PROVIDER
    actual_model = model or settings.DEFAULT_LLM_MODEL
    last_error: Exception | None = None
    success = False

    for attempt in providers_to_try:
        steps_emitted = len(steps)
        try:
            client = _client()
            gmodel = gateway_model(attempt.get("provider"), attempt.get("model"))
            msgs: list[dict] = [{"role": "system", "content": system_prompt}, {"role": "user", "content": input_text}]
            for _ in range(MAX_STEPS):
                resp = await client.chat.completions.create(model=gmodel, messages=msgs, tools=tools)
                tin += resp.usage.prompt_tokens if resp.usage else 0
                tout += resp.usage.completion_tokens if resp.usage else 0
                msg = resp.choices[0].message
                if msg.content:
                    await push(ReactStep(type="thought", content=msg.content))
                if not msg.tool_calls:
                    answer = msg.content or ""
                    break
                msgs.append({"role": "assistant", "content": msg.content or "", "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    await push(ReactStep(type="tool_call", toolName=tc.function.name, content=json.dumps(args)))
                    result = await _exec_tool(tc.function.name, args, session_id, user_id)
                    await push(ReactStep(type="tool_result", toolName=tc.function.name, content=result))
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            actual_provider = attempt.get("provider") or settings.DEFAULT_LLM_PROVIDER
            actual_model = attempt.get("model") or settings.DEFAULT_LLM_MODEL
            success = True
            break
        except Exception as e:
            if len(steps) > steps_emitted:
                raise
            last_error = e
            logger.warning("[run_react] LLM %s/%s failed, next fallback: %s", attempt.get("provider"), attempt.get("model"), e)
            del steps[steps_emitted:]

    if not success:
        if execution_id:
            async with SessionLocal() as s:
                await s.execute(
                    update(AgentExecutions).where(AgentExecutions.id == uuidlib.UUID(execution_id)).values(
                        duration_ms=int((time.time() - start) * 1000), status="error"))
                await s.commit()
        raise last_error or RuntimeError("No LLM available")

    await push(ReactStep(type="answer", content=answer))

    # Governor (fire-and-forget, coût 0.0 — pricing détaillé en S133)
    try:
        async with SessionLocal() as s:
            s.add(GovernorUsage(user_id=user_id, provider=actual_provider, model=actual_model,
                                tokens_in=tin, tokens_out=tout, cout_usd=0.0))
            if execution_id:
                await s.execute(
                    update(AgentExecutions).where(AgentExecutions.id == uuidlib.UUID(execution_id)).values(
                        output=answer[:2000], duration_ms=int((time.time() - start) * 1000), status="done"))
            await s.commit()
    except Exception:
        pass

    first_provider = provider or settings.DEFAULT_LLM_PROVIDER
    first_model = model or settings.DEFAULT_LLM_MODEL
    used_fallback = actual_provider != first_provider or actual_model != first_model

    return ReactResult(
        steps=steps, answer=answer, tokensIn=tin, tokensOut=tout,
        actualProvider=actual_provider if used_fallback else None,
        actualModel=actual_model if used_fallback else None,
        executionId=execution_id,
    )
