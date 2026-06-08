"""Router webhooks. Portage de routes/webhooks.ts (S134). Monté /api, protégé.

CRUD des webhooks sortants + endpoint de test (POST vers l'URL configurée). Le
champ ``events`` est stocké en TEXT JSON (parité Drizzle).

Quirk Bun préservé : GET et POST renvoient ``events`` parsé en tableau ; PATCH
renvoie la ligne brute de ``.returning()`` → ``events`` reste la chaîne JSON.
"""

from __future__ import annotations

import json
import logging
import uuid as uuidlib

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, desc, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Webhooks
from app.serde import webhook

logger = logging.getLogger(__name__)
router = APIRouter()

# Colonnes patchables (parité avec `db.update().set(body)` du Bun, mais bornée).
_PATCHABLE = {"nom", "url", "events", "enabled", "secret"}


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


class CreateBody(BaseModel):
    nom: str = Field(min_length=1)
    url: str
    events: list[str] = []
    secret: str | None = None


@router.get("/webhooks")
async def list_webhooks(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(Webhooks)
                .where(Webhooks.user_id == user.sub)
                .order_by(desc(Webhooks.created_at))
            )
        ).scalars().all()
    return [webhook(r) for r in rows]


@router.post("/webhooks", status_code=201)
async def create_webhook(body: CreateBody, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        w = Webhooks(
            user_id=user.sub,
            nom=body.nom,
            url=body.url,
            events=json.dumps(body.events),
            secret=body.secret or "",
            enabled=True,
        )
        s.add(w)
        await s.commit()
        await s.refresh(w)
    return webhook(w)


@router.patch("/webhooks/{webhook_id}")
async def update_webhook(
    webhook_id: str,
    body: dict = Body(default_factory=dict),
    user: UserContext = Depends(get_current_user),
):
    wid = _uuid(webhook_id)
    values = {k: v for k, v in body.items() if k in _PATCHABLE}
    if "events" in values:
        values["events"] = json.dumps(values["events"])

    async with SessionLocal() as s:
        if wid is None:
            return None
        if values:
            await s.execute(
                update(Webhooks)
                .where(and_(Webhooks.id == wid, Webhooks.user_id == user.sub))
                .values(**values)
            )
            await s.commit()
        w = (
            await s.execute(
                select(Webhooks).where(
                    and_(Webhooks.id == wid, Webhooks.user_id == user.sub)
                )
            )
        ).scalar_one_or_none()
    # PATCH renvoie la ligne brute → events reste une chaîne (quirk Bun).
    return webhook(w, parse_events=False) if w else None


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, user: UserContext = Depends(get_current_user)):
    wid = _uuid(webhook_id)
    async with SessionLocal() as s:
        if wid is not None:
            await s.execute(
                delete(Webhooks).where(
                    and_(Webhooks.id == wid, Webhooks.user_id == user.sub)
                )
            )
            await s.commit()
    return {"ok": True}


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str, user: UserContext = Depends(get_current_user)):
    wid = _uuid(webhook_id)
    async with SessionLocal() as s:
        w = (
            await s.execute(
                select(Webhooks).where(
                    and_(Webhooks.id == wid, Webhooks.user_id == user.sub)
                )
            )
        ).scalar_one_or_none() if wid is not None else None
    if not w:
        raise HTTPException(status_code=404, detail="Not found")

    import datetime as _dt

    headers = {"Content-Type": "application/json"}
    if w.secret:
        headers["X-Forge-Secret"] = w.secret
    payload = {
        "event": "test",
        "timestamp": _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "source": "Forge",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(w.url, json=payload, headers=headers)
        return {"ok": res.is_success, "status": res.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
