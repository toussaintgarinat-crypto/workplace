"""Router gitpack. Portage de routes/gitpack.ts (S132). Monté /api, protégé.

Analyse IA d'un repo GitHub (langage/framework/build) en tâche de fond via la
gateway LLM (remplace generateText du Vercel AI SDK, décision S128). Le job est
créé statut='running' et répondu en 202 ; l'analyse met à jour done/error.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.llm import generate_text
from app.models import GitpackJobs
from app.serde import gitpack_job

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/gitpack/jobs", dependencies=[Depends(get_current_user)])
async def list_jobs(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(GitpackJobs).where(GitpackJobs.user_id == user.sub)
            .order_by(desc(GitpackJobs.created_at))
        )).scalars().all()
    return [gitpack_job(x) for x in rows]


@router.get("/gitpack/jobs/{jid}", dependencies=[Depends(get_current_user)])
async def get_job(jid: str, user: UserContext = Depends(get_current_user)):
    juid = _uuid(jid)
    async with SessionLocal() as s:
        job = None
        if juid:
            job = (await s.execute(
                select(GitpackJobs).where(and_(GitpackJobs.id == juid, GitpackJobs.user_id == user.sub))
            )).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Not found")
    return gitpack_job(job)


class AnalyzeBody(BaseModel):
    githubUrl: str = Field(min_length=1)
    platform: str | None = None


async def _analyze_job(job_id, github_url: str, platform: str) -> None:
    """Analyse IA en tâche de fond ; met à jour le job (done/error)."""
    try:
        repo_name = "/".join(github_url.rstrip("/").split("/")[-2:])
        prompt = (
            f"Analyse ce repo GitHub: {github_url}\n\n"
            "Détecte :\n"
            "1. Le langage principal (Python, Node.js, Go, Rust, etc.)\n"
            "2. Le framework (Flask, Express, Gin, etc.)\n"
            "3. Les dépendances principales\n"
            f"4. Les instructions de build pour {platform}\n"
            "5. Les risques ou blocages potentiels\n\n"
            "Réponds en JSON structuré :\n"
            '{\n  "language": "...",\n  "framework": "...",\n  "dependencies": [...],\n'
            '  "buildSteps": [...],\n  "risks": [...],\n  "estimatedSize": "...",\n'
            '  "compatible": true/false\n}'
        )
        text = await generate_text(prompt=prompt, max_tokens=800)

        analysis: dict = {}
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                analysis = json.loads(m.group(0))
            except (ValueError, TypeError):
                analysis = {}

        logs = [
            f"✅ Analyse terminée pour {repo_name}",
            f"Langage: {analysis.get('language') or '?'}",
            f"Framework: {analysis.get('framework') or '?'}",
            *[f"→ {s}" for s in (analysis.get("buildSteps") or [])],
            *[f"⚠️ {r}" for r in (analysis.get("risks") or [])],
        ]
        async with SessionLocal() as s:
            await s.execute(
                update(GitpackJobs).where(GitpackJobs.id == job_id).values(
                    statut="done",
                    language=str(analysis.get("language") or "Unknown"),
                    framework=str(analysis.get("framework") or ""),
                    logs=json.dumps(logs),
                    updated_at=datetime.datetime.utcnow(),
                )
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001 — parité Bun (catch-all → statut error)
        async with SessionLocal() as s:
            await s.execute(
                update(GitpackJobs).where(GitpackJobs.id == job_id).values(
                    statut="error", error=str(e), updated_at=datetime.datetime.utcnow(),
                )
            )
            await s.commit()


@router.post("/gitpack/analyze", dependencies=[Depends(get_current_user)])
async def analyze(body: AnalyzeBody, user: UserContext = Depends(get_current_user)):
    platform = body.platform or "macos"
    async with SessionLocal() as s:
        job = GitpackJobs(
            user_id=user.sub, github_url=body.githubUrl, platform=platform, statut="running",
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
        job_id = job.id
        payload = gitpack_job(job)

    asyncio.create_task(_analyze_job(job_id, body.githubUrl, platform))
    return JSONResponse(status_code=202, content=payload)


@router.delete("/gitpack/jobs/{jid}", dependencies=[Depends(get_current_user)])
async def delete_job(jid: str, user: UserContext = Depends(get_current_user)):
    juid = _uuid(jid)
    async with SessionLocal() as s:
        if juid:
            await s.execute(sa_delete(GitpackJobs).where(and_(GitpackJobs.id == juid, GitpackJobs.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
