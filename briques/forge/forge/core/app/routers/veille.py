"""Router veille. Portage de routes/veille.ts (S130). Monté /api, protégé.

Sources de veille (RSS/web) + articles + fetch RSS manuel (parser XML léger par
regex, fidèle au Bun) avec dédup par URL.
"""

from __future__ import annotations

import re
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import VeilleArticles, VeilleSources
from app.serde import veille_article, veille_source

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


# ── Sources ───────────────────────────────────────────────────

@router.get("/veille/sources", dependencies=[Depends(get_current_user)])
async def list_sources(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(VeilleSources).where(VeilleSources.user_id == user.sub)
            .order_by(desc(VeilleSources.created_at))
        )).scalars().all()
    return [veille_source(r) for r in rows]


class CreateSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str
    type: str = "rss"  # rss|web


@router.post("/veille/sources", dependencies=[Depends(get_current_user)])
async def create_source(body: CreateSource, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        src = VeilleSources(user_id=user.sub, nom=body.nom, url=body.url, type=body.type)
        s.add(src)
        await s.commit()
        await s.refresh(src)
    response.status_code = 201
    return veille_source(src)


@router.patch("/veille/sources/{sid}", dependencies=[Depends(get_current_user)])
async def update_source(sid: str, request: Request, user: UserContext = Depends(get_current_user)):
    u = _uuid(sid)
    body = await request.json()
    colmap = {"nom": "nom", "url": "url", "type": "type", "enabled": "enabled"}
    cols = {colmap[k]: v for k, v in body.items() if k in colmap}
    async with SessionLocal() as s:
        if u and cols:
            await s.execute(update(VeilleSources)
                            .where(and_(VeilleSources.id == u, VeilleSources.user_id == user.sub))
                            .values(**cols))
            await s.commit()
        src = (await s.execute(
            select(VeilleSources).where(and_(VeilleSources.id == u, VeilleSources.user_id == user.sub))
        )).scalar_one_or_none() if u else None
    return veille_source(src) if src else None


@router.delete("/veille/sources/{sid}", dependencies=[Depends(get_current_user)])
async def delete_source(sid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(sid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(VeilleSources)
                            .where(and_(VeilleSources.id == u, VeilleSources.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


# ── Articles ──────────────────────────────────────────────────

@router.get("/veille/articles", dependencies=[Depends(get_current_user)])
async def list_articles(request: Request, user: UserContext = Depends(get_current_user)):
    source_id = request.query_params.get("sourceId")
    async with SessionLocal() as s:
        where = VeilleArticles.user_id == user.sub
        if source_id:
            where = and_(where, VeilleArticles.source_id == _uuid(source_id))
        rows = (await s.execute(
            select(VeilleArticles).where(where).order_by(desc(VeilleArticles.created_at)).limit(100)
        )).scalars().all()
    return [veille_article(r) for r in rows]


@router.patch("/veille/articles/{aid}", dependencies=[Depends(get_current_user)])
async def update_article(aid: str, request: Request, user: UserContext = Depends(get_current_user)):
    u = _uuid(aid)
    body = await request.json()
    colmap = {"lu": "lu", "resume": "resume", "titre": "titre", "url": "url"}
    cols = {colmap[k]: v for k, v in body.items() if k in colmap}
    async with SessionLocal() as s:
        if u and cols:
            await s.execute(update(VeilleArticles)
                            .where(and_(VeilleArticles.id == u, VeilleArticles.user_id == user.sub))
                            .values(**cols))
            await s.commit()
        a = (await s.execute(
            select(VeilleArticles).where(and_(VeilleArticles.id == u, VeilleArticles.user_id == user.sub))
        )).scalar_one_or_none() if u else None
    return veille_article(a) if a else None


# ── Fetch RSS (parser léger par regex, fidèle au Bun) ──────────

_ITEM_RE = re.compile(r"<item[^>]*>([\s\S]*?)</item>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link[^>]*>(.*?)</link>", re.IGNORECASE | re.DOTALL)
_GUID_RE = re.compile(r"<guid[^>]*>(https?://[^<]+)</guid>", re.IGNORECASE)
_PUBDATE_RE = re.compile(r"<pubDate[^>]*>(.*?)</pubDate>", re.IGNORECASE | re.DOTALL)


def _parse_rss_items(text: str) -> list[dict]:
    """Parse <item> RSS → [{titre, url, publishedAt}], fidèle au regex du Bun."""
    items: list[dict] = []
    for m in _ITEM_RE.finditer(text):
        item = m.group(1)
        title_m = _TITLE_RE.search(item)
        title = (title_m.group(1).strip() if title_m else "")
        link_m = _LINK_RE.search(item)
        link = link_m.group(1).strip() if link_m and link_m.group(1).strip() else ""
        if not link:
            guid_m = _GUID_RE.search(item)
            link = guid_m.group(1).strip() if guid_m else ""
        pub_m = _PUBDATE_RE.search(item)
        pub = pub_m.group(1).strip() if pub_m else ""
        if title and link:
            items.append({"titre": title, "url": link, "publishedAt": pub})
    return items


@router.post("/veille/fetch/{source_id}", dependencies=[Depends(get_current_user)])
async def fetch_source(source_id: str, user: UserContext = Depends(get_current_user)):
    su = _uuid(source_id)
    async with SessionLocal() as s:
        src = (await s.execute(
            select(VeilleSources).where(and_(VeilleSources.id == su, VeilleSources.user_id == user.sub))
        )).scalar_one_or_none() if su else None
        if src is None:
            raise HTTPException(status_code=404, detail="Source not found")
        src_url, src_pk = src.url, src.id

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.get(src_url, headers={"User-Agent": "Forge/1.0 RSS Reader"})
            text = res.text
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))

    items = _parse_rss_items(text)

    added = 0
    async with SessionLocal() as s:
        for item in items[:20]:
            existing = (await s.execute(
                select(VeilleArticles).where(and_(
                    VeilleArticles.user_id == user.sub, VeilleArticles.url == item["url"]))
            )).scalars().all()
            if not existing:
                s.add(VeilleArticles(user_id=user.sub, source_id=src_pk, titre=item["titre"],
                                     url=item["url"], published_at=item["publishedAt"]))
                added += 1
        await s.commit()
    return {"added": added, "total": len(items)}
