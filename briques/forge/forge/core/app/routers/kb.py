"""Router KB (base de connaissances). Portage de routes/kb.ts (S129). Monté /api, protégé.

CRUD d'articles + ingestion/ré-ingestion Qdrant best-effort (fire-and-forget, ne bloque
pas la réponse), via le module mémoire S129.
"""

from __future__ import annotations

import asyncio
import json
import uuid as uuidlib

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.memory import delete_by_source, ingest
from app.models import KbArticles
from app.serde import kb_article

router = APIRouter()


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _ingest_bg(text: str, source_id: str, user_id: str, title: str) -> None:
    """Lance l'ingestion en tâche de fond (équivalent du .catch(()=>{}) du Bun)."""
    async def _run():
        try:
            await ingest(text=text, source_id=source_id, source_type="kb_article",
                         user_id=user_id, title=title)
        except Exception:  # noqa: BLE001
            pass
    asyncio.create_task(_run())


@router.get("/kb/articles", dependencies=[Depends(get_current_user)])
async def list_articles(request: Request, user: UserContext = Depends(get_current_user)):
    q = request.query_params.get("q")
    async with SessionLocal() as s:
        where = KbArticles.user_id == user.sub
        if q:
            where = and_(where, or_(KbArticles.titre.ilike(f"%{q}%"), KbArticles.contenu.ilike(f"%{q}%")))
        rows = (await s.execute(
            select(KbArticles).where(where).order_by(desc(KbArticles.is_pinned), desc(KbArticles.updated_at))
        )).scalars().all()
        stats_row = (await s.execute(
            select(
                func.count().label("total"),
                func.count().filter(KbArticles.is_public == True).label("publics"),  # noqa: E712
                func.count().filter(KbArticles.is_pinned == True).label("epingles"),  # noqa: E712
            ).where(KbArticles.user_id == user.sub)
        )).one()
    # parité driver pg : count() → STRING (cf. S128). on caste en str.
    stats = {"total": str(stats_row.total), "publics": str(stats_row.publics), "epingles": str(stats_row.epingles)}
    return {"articles": [kb_article(r) for r in rows], "stats": stats}


@router.get("/kb/articles/{aid}", dependencies=[Depends(get_current_user)])
async def get_article(aid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(aid)
    async with SessionLocal() as s:
        row = (await s.execute(
            select(KbArticles).where(and_(KbArticles.id == u, KbArticles.user_id == user.sub))
        )).scalar_one_or_none() if u else None
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return kb_article(row)


class CreateArticle(BaseModel):
    titre: str = Field(min_length=1)
    contenu: str | None = None
    tags: list[str] | None = None
    isPinned: bool | None = None
    isPublic: bool | None = None


@router.post("/kb/articles", dependencies=[Depends(get_current_user)])
async def create_article(body: CreateArticle, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        a = KbArticles(
            user_id=user.sub, titre=body.titre, contenu=body.contenu or "",
            tags=json.dumps(body.tags or []),
            is_pinned=body.isPinned or False, is_public=body.isPublic or False,
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
    if a.contenu:
        _ingest_bg(a.contenu, str(a.id), user.sub, a.titre)
    response.status_code = 201
    # parité Bun : POST retourne tags en TABLEAU (override de la ligne brute)
    return {**kb_article(a), "tags": body.tags or []}


@router.patch("/kb/articles/{aid}", dependencies=[Depends(get_current_user)])
async def update_article(aid: str, body: dict = Body(default={}), user: UserContext = Depends(get_current_user)):
    u = _uuid(aid)
    if "tags" in body and body["tags"] is not None:
        body["tags"] = json.dumps(body["tags"])
    # mapping camelCase → colonnes
    colmap = {"titre": "titre", "contenu": "contenu", "tags": "tags",
              "isPinned": "is_pinned", "isPublic": "is_public"}
    cols = {colmap[k]: v for k, v in body.items() if k in colmap}
    async with SessionLocal() as s:
        if cols and u:
            await s.execute(
                update(KbArticles)
                .where(and_(KbArticles.id == u, KbArticles.user_id == user.sub))
                .values(updated_at=func.now(), **cols)
            )
            await s.commit()
        row = (await s.execute(
            select(KbArticles).where(and_(KbArticles.id == u, KbArticles.user_id == user.sub))
        )).scalar_one_or_none() if u else None
    if row is not None and body.get("contenu"):
        async def _reingest():
            await delete_by_source(aid)
            await ingest(text=row.contenu or "", source_id=aid, source_type="kb_article",
                         user_id=user.sub, title=row.titre)
        asyncio.create_task(_reingest())
    return kb_article(row) if row else None


@router.delete("/kb/articles/{aid}", dependencies=[Depends(get_current_user)])
async def delete_article(aid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(aid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(KbArticles).where(and_(KbArticles.id == u, KbArticles.user_id == user.sub)))
            await s.commit()
    asyncio.create_task(delete_by_source(aid))
    return {"ok": True}
