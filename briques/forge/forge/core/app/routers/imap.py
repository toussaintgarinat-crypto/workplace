"""Router IMAP (configs + emails). Portage de routes/imap.ts (S135).

Monté /api, protégé. Configs de boîtes mail par utilisateur (mot de passe chiffré
AES-GCM via app.crypto, jamais renvoyé), lecture des emails synchronisés.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import and_, desc, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.crypto import encrypt
from app.db import SessionLocal
from app.models import ImapConfigs, ImapEmails
from app.serde import imap_config_min, imap_config_public, imap_email

router = APIRouter()


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/imap/configs", dependencies=[Depends(get_current_user)])
async def list_configs(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(ImapConfigs).where(ImapConfigs.user_id == user.sub)
        )).scalars().all()
    return [imap_config_public(r) for r in rows]


@router.post("/imap/configs", dependencies=[Depends(get_current_user)])
async def create_config(body: dict, response: Response,
                        user: UserContext = Depends(get_current_user)):
    host = (body.get("host") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    if not host or "@" not in email or not password:
        response.status_code = 400
        return {"error": "Invalid body"}
    port = body.get("port")
    if not isinstance(port, int):
        port = 993
    async with SessionLocal() as s:
        row = ImapConfigs(
            user_id=user.sub, host=host, port=port, email=email,
            password_encrypted=encrypt(password),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return imap_config_min(row)


@router.delete("/imap/configs/{cid}", dependencies=[Depends(get_current_user)])
async def delete_config(cid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(cid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(ImapConfigs).where(and_(
                ImapConfigs.id == u, ImapConfigs.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}


@router.get("/imap/emails", dependencies=[Depends(get_current_user)])
async def list_emails(request: Request, user: UserContext = Depends(get_current_user)):
    config_id = request.query_params.get("configId")
    async with SessionLocal() as s:
        config_ids = (await s.execute(
            select(ImapConfigs.id).where(ImapConfigs.user_id == user.sub)
        )).scalars().all()
        if not config_ids:
            return []
        target = _uuid(config_id) if config_id else config_ids[0]
        rows = (await s.execute(
            select(ImapEmails).where(ImapEmails.config_id == target)
            .order_by(desc(ImapEmails.created_at)).limit(100)
        )).scalars().all()
    return [imap_email(r) for r in rows]
