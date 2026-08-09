"""Router sessions. Portage de routes/sessions.ts (S133). Monté /api/sessions, protégé.

Sessions de conversation scopées user / pole / venture, avec contrôle d'accès par
appartenance (membre ou owner). Les listes renvoient des champs joints
(poleName/poleEmoji/... ventureName/...) en plus des colonnes de session.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, asc, desc, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import Messages, PoleMembers, Poles, Sessions, VentureMembers, Ventures
from app.serde import message as ser_message
from app.serde import session as ser_session

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


async def _check_pole_membership(s, pole_id, user_sub: str) -> bool:
    m = (await s.execute(
        select(PoleMembers.id).where(and_(PoleMembers.pole_id == pole_id, PoleMembers.user_id == user_sub))
    )).first()
    if m is not None:
        return True
    o = (await s.execute(
        select(Poles.id).where(and_(Poles.id == pole_id, Poles.owner_id == user_sub))
    )).first()
    return o is not None


async def _check_venture_membership(s, venture_id, user_sub: str) -> bool:
    m = (await s.execute(
        select(VentureMembers.id).where(and_(VentureMembers.venture_id == venture_id, VentureMembers.user_id == user_sub))
    )).first()
    if m is not None:
        return True
    o = (await s.execute(
        select(Ventures.id).where(and_(Ventures.id == venture_id, Ventures.owner_id == user_sub))
    )).first()
    return o is not None


@router.get("", dependencies=[Depends(get_current_user)])
async def list_sessions(
    poleId: str | None = None,
    ventureId: str | None = None,
    user: UserContext = Depends(get_current_user),
):
    async with SessionLocal() as s:
        if poleId:
            puid = _uuid(poleId)
            if not await _check_pole_membership(s, puid, user.sub):
                raise HTTPException(status_code=403, detail="Forbidden")
            rows = (await s.execute(
                select(Sessions, Poles.nom, Poles.emoji, Poles.couleur)
                .join(Poles, Sessions.pole_id == Poles.id, isouter=True)
                .where(and_(Sessions.pole_id == puid, Sessions.scope == "pole"))
                .order_by(desc(Sessions.updated_at))
            )).all()
            return [
                {**ser_session(r[0]), "poleName": r[1], "poleEmoji": r[2], "poleCouleur": r[3]}
                for r in rows
            ]

        if ventureId:
            vuid = _uuid(ventureId)
            if not await _check_venture_membership(s, vuid, user.sub):
                raise HTTPException(status_code=403, detail="Forbidden")
            rows = (await s.execute(
                select(Sessions, Ventures.nom, Ventures.emoji, Ventures.couleur)
                .join(Ventures, Sessions.venture_id == Ventures.id, isouter=True)
                .where(and_(Sessions.venture_id == vuid, Sessions.scope == "venture"))
                .order_by(desc(Sessions.updated_at))
            )).all()
            return [
                {**ser_session(r[0]), "ventureName": r[1], "ventureEmoji": r[2], "ventureCouleur": r[3]}
                for r in rows
            ]

        rows = (await s.execute(
            select(Sessions, Poles.nom, Poles.emoji, Poles.couleur, Ventures.nom, Ventures.emoji)
            .join(Poles, Sessions.pole_id == Poles.id, isouter=True)
            .join(Ventures, Sessions.venture_id == Ventures.id, isouter=True)
            .where(Sessions.user_id == user.sub)
            .order_by(desc(Sessions.updated_at))
        )).all()
        return [
            {
                **ser_session(r[0]),
                "poleName": r[1], "poleEmoji": r[2], "poleCouleur": r[3],
                "ventureName": r[4], "ventureEmoji": r[5],
            }
            for r in rows
        ]


class CreateSession(BaseModel):
    name: str | None = None
    poleId: str | None = None
    ventureId: str | None = None
    scope: str | None = None


@router.post("")
async def create_session(
    body: CreateSession,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    # S18 (Chantier 1) : org active validée, jamais le header cru.
    oid = _uuid(org_id)
    puid = _uuid(body.poleId)
    vuid = _uuid(body.ventureId)

    resolved_scope = body.scope or "user"
    if not body.scope:
        if body.ventureId:
            resolved_scope = "venture"
        elif body.poleId:
            resolved_scope = "pole"

    default_name = "New conversation"
    async with SessionLocal() as s:
        if resolved_scope == "pole" and puid:
            pole = (await s.execute(select(Poles.nom).where(Poles.id == puid))).first()
            if pole:
                default_name = f"Chat · {pole.nom}"
        elif resolved_scope == "venture" and vuid:
            v = (await s.execute(select(Ventures.nom).where(Ventures.id == vuid))).first()
            if v:
                default_name = f"Chat · {v.nom}"

        sess = Sessions(
            user_id=user.sub, org_id=oid,
            name=body.name or default_name,
            pole_id=puid, venture_id=vuid, scope=resolved_scope,
        )
        s.add(sess)
        await s.commit()
        await s.refresh(sess)
    return JSONResponse(status_code=201, content=ser_session(sess))


class PatchSession(BaseModel):
    name: str


@router.patch("/{sid}")
async def rename_session(sid: str, body: PatchSession, user: UserContext = Depends(get_current_user)):
    # S18 (Chantier 1) : l'UPDATE par id seul était une fuite d'écriture inter-tenant
    # (n'importe quel user pouvait renommer n'importe quelle session). On borne désormais
    # à l'owner ou à un membre du pôle/venture, comme list_messages.
    suid = _uuid(sid)
    async with SessionLocal() as s:
        sess = (await s.execute(select(Sessions).where(Sessions.id == suid))).scalar_one_or_none() if suid else None
        if sess is None:
            raise HTTPException(status_code=404, detail="Not found")
        has_access = (
            sess.user_id == user.sub
            or (sess.scope == "pole" and sess.pole_id and await _check_pole_membership(s, sess.pole_id, user.sub))
            or (sess.scope == "venture" and sess.venture_id and await _check_venture_membership(s, sess.venture_id, user.sub))
        )
        if not has_access:
            # S223 — 404 et NON 403 : la ligne au-dessus renvoie déjà 404 quand la session
            # n'existe pas ; un 403 ici distinguerait « session d'autrui » de « session
            # inexistante » et permettrait d'énumérer les sessions par balayage d'id.
            raise HTTPException(status_code=404, detail="Not found")
        await s.execute(
            update(Sessions).where(Sessions.id == suid).values(name=body.name, updated_at=datetime.datetime.utcnow())
        )
        await s.commit()
        sess = (await s.execute(select(Sessions).where(Sessions.id == suid))).scalar_one_or_none()
    return ser_session(sess) if sess is not None else None


@router.get("/{sid}/messages", dependencies=[Depends(get_current_user)])
async def list_messages(sid: str, user: UserContext = Depends(get_current_user)):
    suid = _uuid(sid)
    async with SessionLocal() as s:
        sess = (await s.execute(select(Sessions).where(Sessions.id == suid))).scalar_one_or_none() if suid else None
        if sess is None:
            raise HTTPException(status_code=404, detail="Not found")
        has_access = (
            sess.user_id == user.sub
            or (sess.scope == "pole" and sess.pole_id and await _check_pole_membership(s, sess.pole_id, user.sub))
            or (sess.scope == "venture" and sess.venture_id and await _check_venture_membership(s, sess.venture_id, user.sub))
        )
        if not has_access:
            # S223 — 404 et NON 403 : la ligne au-dessus renvoie déjà 404 quand la session
            # n'existe pas ; un 403 ici distinguerait « session d'autrui » de « session
            # inexistante » et permettrait d'énumérer les sessions par balayage d'id.
            raise HTTPException(status_code=404, detail="Not found")
        rows = (await s.execute(
            select(Messages).where(Messages.session_id == suid).order_by(asc(Messages.created_at))
        )).scalars().all()
    return [ser_message(m) for m in rows]


@router.delete("/{sid}", dependencies=[Depends(get_current_user)])
async def delete_session(sid: str, user: UserContext = Depends(get_current_user)):
    suid = _uuid(sid)
    async with SessionLocal() as s:
        if suid:
            await s.execute(sa_delete(Sessions).where(and_(Sessions.id == suid, Sessions.user_id == user.sub)))
            await s.commit()
    return {"deleted": True}
