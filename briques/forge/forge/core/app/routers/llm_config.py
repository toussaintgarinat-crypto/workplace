"""Router llm-config. Portage de llm-config.ts (S128). Monté /api/llm-config, protégé.

CRUD presets (parité stricte) + listes de modèles (best-effort via providers externes).
"""

from __future__ import annotations

import os
import re
import uuid as uuidlib

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Body
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete as sa_delete, func, select, update

from app.auth import UserContext, get_current_user, require_org
from app.config import settings
from app.crypto import decrypt
from app.db import SessionLocal
from app.llm import AVAILABLE_PROVIDERS, LlmContext, resolve_llm_config
from app.models import AgentDefinitions, LlmPresets, Poles, PoleTools, ProviderApiKeys
from app.serde import llm_preset

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


def _ollama_base() -> str:
    base = settings.OLLAMA_BASE_URL or "http://localhost:11434/api"
    return re.sub(r"/api/?$", "", base)


async def _get_user_key(user_id: str, provider: str) -> str | None:
    async with SessionLocal() as s:
        row = (await s.execute(
            select(ProviderApiKeys).where(and_(ProviderApiKeys.user_id == user_id, ProviderApiKeys.provider == provider))
        )).scalar_one_or_none()
    if row and row.encrypted_key:
        try:
            return decrypt(row.encrypted_key)
        except Exception:
            pass
    return os.getenv(f"{provider.upper()}_API_KEY")


def _filter_models(provider: str, ids: list[str]) -> list[str]:
    excl = re.compile(r"embed|whisper|tts-|dall-|realtime|transcri", re.I)
    if provider == "openai":
        return [m for m in ids if re.match(r"^(gpt-|o[1-9]|chatgpt-)", m) and not excl.search(m)]
    if provider == "gemini":
        return [m for m in ids if re.match(r"^gemini", m)]
    return [m for m in ids if not excl.search(m)]


# ── Listes ──────────────────────────────────────────────────────────
@router.get("/providers", dependencies=[Depends(get_current_user)])
async def providers():
    return AVAILABLE_PROVIDERS


@router.get("/ollama/models", dependencies=[Depends(get_current_user)])
async def ollama_models():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            res = await c.get(f"{_ollama_base()}/api/tags")
        if res.status_code != 200:
            return {"models": []}
        data = res.json()
        models = [m.get("name") or m.get("model") for m in (data.get("models") or [])]
        return {"models": [m for m in models if m], "dynamic": True}
    except Exception:
        return {"models": []}


class OllamaPull(BaseModel):
    name: str | None = None


@router.delete("/ollama/models", dependencies=[Depends(get_current_user)])
async def ollama_delete(name: str | None = None):
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            res = await c.request("DELETE", f"{_ollama_base()}/api/delete", json={"name": name})
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Delete failed")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Ollama unreachable")


# ── Presets CRUD ────────────────────────────────────────────────────
class PresetIn(BaseModel):
    scopeType: str
    scopeId: str
    ventureId: str | None = None
    provider: str
    baseUrl: str = ""
    apiKey: str = ""
    model: str
    maxTokens: int = Field(default=2048, ge=256, le=128000)
    budgetDaily: float | None = None
    budgetMonthly: float | None = None


async def _resolve_venture_id(s, scope_type: str, scope_id: str) -> str | None:
    su = _uuid(scope_id)
    if scope_type == "venture":
        return scope_id
    if scope_type == "pole" and su:
        p = (await s.execute(select(Poles.venture_id).where(Poles.id == su))).first()
        return p[0] if p else None
    if scope_type == "tool" and su:
        pt = (await s.execute(select(PoleTools.pole_id).where(PoleTools.id == su))).first()
        if not pt or not pt[0]:
            return None
        p = (await s.execute(select(Poles.venture_id).where(Poles.id == pt[0]))).first()
        return p[0] if p else None
    if scope_type == "agent" and su:
        a = (await s.execute(select(AgentDefinitions.pole_id).where(AgentDefinitions.id == su))).first()
        if not a or not a[0]:
            return None
        p = (await s.execute(select(Poles.venture_id).where(Poles.id == a[0]))).first()
        return p[0] if p else None
    return None


@router.get("/preset", dependencies=[Depends(get_current_user)])
async def get_preset(scopeType: str | None = None, scopeId: str | None = None):
    if not scopeType or not scopeId:
        raise HTTPException(status_code=400, detail="scopeType and scopeId required")
    async with SessionLocal() as s:
        p = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == scopeType, LlmPresets.scope_id == scopeId))
        )).scalar_one_or_none()
    return llm_preset(p) if p else None


@router.get("/venture/{venture_id}", dependencies=[Depends(get_current_user)])
async def venture_presets(venture_id: str):
    vu = _uuid(venture_id)
    async with SessionLocal() as s:
        rows = (await s.execute(select(LlmPresets).where(LlmPresets.venture_id == vu))).scalars().all() if vu else []
    return [llm_preset(p) for p in rows]


@router.get("/resolve", dependencies=[Depends(get_current_user)])
async def resolve(agentId: str | None = None, toolKey: str | None = None, poleId: str | None = None, ventureId: str | None = None):
    preset = await resolve_llm_config(LlmContext(agent_id=agentId, tool_key=toolKey, pole_id=poleId, venture_id=ventureId))
    return llm_preset(preset) if preset else None


@router.put("/preset")
async def put_preset(body: PresetIn, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        venture_id = body.ventureId or await _resolve_venture_id(s, body.scopeType, body.scopeId)
        existing = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == body.scopeType, LlmPresets.scope_id == body.scopeId))
        )).scalar_one_or_none()
        vals = dict(
            scope_type=body.scopeType, scope_id=body.scopeId, venture_id=_uuid(venture_id),
            provider=body.provider, base_url=body.baseUrl, api_key=body.apiKey, model=body.model,
            max_tokens=body.maxTokens, budget_daily=body.budgetDaily, budget_monthly=body.budgetMonthly,
            updated_by=user.sub,
        )
        if existing:
            await s.execute(update(LlmPresets).where(LlmPresets.id == existing.id).values(updated_at=func.now(), **vals))
            await s.commit()
            row = (await s.execute(select(LlmPresets).where(LlmPresets.id == existing.id))).scalar_one()
            return llm_preset(row)
        row = LlmPresets(**vals)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        response.status_code = 201
        return llm_preset(row)


@router.delete("/preset")
async def delete_preset(scopeType: str | None = None, scopeId: str | None = None, user: UserContext = Depends(get_current_user)):
    if not scopeType or not scopeId:
        raise HTTPException(status_code=400, detail="scopeType and scopeId required")
    async with SessionLocal() as s:
        await s.execute(sa_delete(LlmPresets).where(and_(LlmPresets.scope_type == scopeType, LlmPresets.scope_id == scopeId)))
        await s.commit()
    return {"ok": True}


@router.get("/global")
async def get_global(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    # S18 (Chantier 1) : org validée obligatoire. Avant, un X-Org-ID cru permettait
    # de lire le preset LLM global d'un autre org.
    async with SessionLocal() as s:
        p = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == "global", LlmPresets.scope_id == org_id))
        )).scalar_one_or_none()
    return llm_preset(p) if p else None


class CorpsLlmGlobal(BaseModel):
    provider: str
    model: str


@router.put("/global")
async def put_global(
    body: CorpsLlmGlobal, response: Response,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == "global", LlmPresets.scope_id == org_id))
        )).scalar_one_or_none()
        if existing:
            await s.execute(update(LlmPresets).where(LlmPresets.id == existing.id).values(
                provider=body.provider, model=body.model, updated_at=func.now(), updated_by=user.sub))
            await s.commit()
            row = (await s.execute(select(LlmPresets).where(LlmPresets.id == existing.id))).scalar_one()
            return llm_preset(row)
        row = LlmPresets(scope_type="global", scope_id=org_id, provider=body.provider, model=body.model, updated_by=user.sub)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        response.status_code = 201
        return llm_preset(row)


# ── Dynamique : modèles d'un provider cloud (best-effort) ───────────
@router.get("/{provider}/models")
async def provider_models(provider: str, user: UserContext = Depends(get_current_user)):
    fallback = next((p["models"] for p in AVAILABLE_PROVIDERS if p["id"] == provider), [])
    try:
        key = await _get_user_key(user.sub, provider)
        ids: list[str] | None = None
        async with httpx.AsyncClient(timeout=10) as c:
            if provider in ("openai", "deepseek"):
                if not key:
                    return {"models": fallback, "dynamic": False}
                base = "https://api.deepseek.com" if provider == "deepseek" else "https://api.openai.com"
                r = await c.get(f"{base}/v1/models", headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 200:
                    ids = [m["id"] for m in r.json().get("data", [])]
            elif provider == "groq":
                if not key:
                    return {"models": fallback, "dynamic": False}
                r = await c.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 200:
                    ids = [m["id"] for m in r.json().get("data", [])]
            elif provider == "mistral":
                if not key:
                    return {"models": fallback, "dynamic": False}
                r = await c.get("https://api.mistral.ai/v1/models", headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 200:
                    ids = [m["id"] for m in r.json().get("data", [])]
            elif provider == "gemini":
                if not key:
                    return {"models": fallback, "dynamic": False}
                r = await c.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
                if r.status_code == 200:
                    ids = [m["name"].replace("models/", "") for m in r.json().get("models", [])]
            elif provider == "openrouter":
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                r = await c.get("https://openrouter.ai/api/v1/models", headers=headers)
                if r.status_code == 200:
                    ids = [m["id"] for m in r.json().get("data", [])]
            elif provider == "lmstudio":
                base = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
                r = await c.get(f"{base}/models")
                if r.status_code == 200:
                    ids = [m["id"] for m in r.json().get("data", [])]
        if not ids:
            return {"models": fallback, "dynamic": False}
        filtered = sorted(_filter_models(provider, ids))
        return {"models": filtered or fallback, "dynamic": True}
    except Exception:
        return {"models": fallback, "dynamic": False}


# ── Rétro-compat : GET /:poleId (DOIT rester en dernier) ────────────
@router.get("/{pole_id}", dependencies=[Depends(get_current_user)])
async def get_by_pole(pole_id: str):
    async with SessionLocal() as s:
        p = (await s.execute(
            select(LlmPresets).where(and_(LlmPresets.scope_type == "pole", LlmPresets.scope_id == pole_id))
        )).scalar_one_or_none()
    return llm_preset(p) if p else None
