"""Router ventures. Portage de routes/ventures.ts (S130). Monté /api, protégé.

CRUD ventures + pôles par défaut à la création + suppression à confirmation par
code email (token TTL 15 min). `resolveOrgId` ignore un X-Org-ID périmé/fantôme
(évite la violation de FK à l'insertion — cf. fix S125 venture/audit FK org).
"""

from __future__ import annotations

import logging
import random
import uuid as uuidlib
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.config import settings
from app.db import SessionLocal
from app.email import send_venture_deletion_code
from app.models import (
    AuditMissions, LlmPresets, OrganizationMembers, PoleMembers, Poles, Users,
    VentureDeleteTokens, VentureMembers, Ventures,
)
from app.serde import audit_mission, pole, venture, venture_member

router = APIRouter()
logger = logging.getLogger(__name__)

# Pôles créés par défaut pour chaque nouvelle venture (parité ventures.ts).
DEFAULT_POLES = [
    {"nom": "Finance", "type": "finance", "emoji": "📊", "couleur": "#10b981"},
    {"nom": "Marketing", "type": "marketing", "emoji": "🚀", "couleur": "#8b5cf6"},
    {"nom": "Sales", "type": "sales", "emoji": "🤝", "couleur": "#f59e0b"},
    {"nom": "Opérations", "type": "ops", "emoji": "⚙️", "couleur": "#3b82f6"},
    {"nom": "Juridique", "type": "legal", "emoji": "🛡️", "couleur": "#ef4444"},
    {"nom": "Dev", "type": "dev", "emoji": "💻", "couleur": "#6366f1"},
]


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


async def _resolve_org_id(s, org_id: str | None, user_id: str) -> str | None:
    """Renvoie org_id seulement si l'utilisateur en est membre, sinon None."""
    if not org_id:
        return None
    ou = _uuid(org_id)
    if ou is None:
        return None
    m = (await s.execute(
        select(OrganizationMembers).where(and_(
            OrganizationMembers.org_id == ou, OrganizationMembers.user_id == user_id))
    )).scalar_one_or_none()
    return org_id if m else None


@router.get("/ventures", dependencies=[Depends(get_current_user)])
async def list_ventures(request: Request, user: UserContext = Depends(get_current_user)):
    org_id = request.headers.get("X-Org-ID")
    async with SessionLocal() as s:
        where = Ventures.owner_id == user.sub
        if org_id:
            ou = _uuid(org_id)
            where = and_(where, (Ventures.org_id == ou) | (Ventures.org_id.is_(None)))
        rows = (await s.execute(
            select(Ventures).where(where).order_by(desc(Ventures.created_at))
        )).scalars().all()
    return [venture(r) for r in rows]


class CreateVenture(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str | None = None
    emoji: str | None = None
    couleur: str | None = None
    type: str | None = None  # 'own' | 'audit'


@router.post("/ventures", dependencies=[Depends(get_current_user)])
async def create_venture(body: CreateVenture, response: Response, request: Request,
                         user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        org_id = await _resolve_org_id(s, request.headers.get("X-Org-ID"), user.sub)
        ou = _uuid(org_id) if org_id else None
        v = Ventures(
            owner_id=user.sub, org_id=ou,
            nom=body.nom, description=body.description or "",
            emoji=body.emoji or "🚀", couleur=body.couleur or "#6366f1",
            type=body.type or "own",
        )
        s.add(v)
        await s.flush()

        for p in DEFAULT_POLES:
            po = Poles(nom=p["nom"], type=p["type"], emoji=p["emoji"], couleur=p["couleur"],
                       venture_id=str(v.id), owner_id=user.sub, org_id=ou)
            s.add(po)
            await s.flush()
            s.add(PoleMembers(pole_id=po.id, user_id=user.sub,
                              nom=user.nom or "Utilisateur", avatar_emoji=user.avatar_emoji or "👤",
                              role="owner"))
            s.add(LlmPresets(scope_type="pole", scope_id=str(po.id), venture_id=v.id, updated_by=user.sub))
        await s.commit()
        await s.refresh(v)
    response.status_code = 201
    return venture(v)


@router.get("/ventures/{vid}", dependencies=[Depends(get_current_user)])
async def get_venture(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")
        members = (await s.execute(
            select(VentureMembers).where(VentureMembers.venture_id == u)
        )).scalars().all()
    return {**venture(v), "members": [venture_member(m) for m in members]}


class UpdateVenture(BaseModel):
    nom: str | None = None
    description: str | None = None
    emoji: str | None = None
    couleur: str | None = None
    statut: str | None = None  # 'actif' | 'archive' | 'livre'
    geo_object_id: str | None = Field(None, alias="geoObjectId")
    audit_id: str | None = Field(None, alias="auditId")
    profil_entreprise: dict | None = Field(None, alias="profilEntreprise")

    model_config = {"populate_by_name": True}


@router.patch("/ventures/{vid}", dependencies=[Depends(get_current_user)])
async def update_venture(vid: str, body: UpdateVenture, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    cols = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    async with SessionLocal() as s:
        v = None
        if u:
            await s.execute(
                update(Ventures)
                .where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
                .values(updated_at=datetime.utcnow(), **cols)
            )
            await s.commit()
            v = (await s.execute(
                select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
            )).scalar_one_or_none()
    return venture(v) if v else None


@router.post("/ventures/{vid}/delete-request", dependencies=[Depends(get_current_user)])
async def delete_request(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")
        email = (await s.execute(select(Users.email).where(Users.id == _uuid(user.sub)))).scalar_one_or_none()
        if not email:
            raise HTTPException(status_code=400, detail="No email on account")

        await s.execute(sa_delete(VentureDeleteTokens).where(and_(
            VentureDeleteTokens.venture_id == u, VentureDeleteTokens.user_id == user.sub)))
        code = str(random.randint(100000, 999999))
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        s.add(VentureDeleteTokens(venture_id=u, user_id=user.sub, code=code, expires_at=expires_at))
        await s.commit()
        v_nom = v.nom

    try:
        await send_venture_deletion_code(to=email, venture_name=v_nom, code=code, expires_in="15 minutes")
    except Exception as err:  # noqa: BLE001
        logger.error("[forge:email] Failed to send deletion code: %s", str(err)[:120])
        raise HTTPException(status_code=500, detail="Email sending failed. Check SMTP configuration.")

    import re
    masked = re.sub(r"(.{2}).+(@.+)", r"\1***\2", email)
    return {"ok": True, "email": masked}


class DeleteVenture(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.delete("/ventures/{vid}", dependencies=[Depends(get_current_user)])
async def delete_venture(vid: str, body: DeleteVenture, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        token = (await s.execute(
            select(VentureDeleteTokens).where(and_(
                VentureDeleteTokens.venture_id == u,
                VentureDeleteTokens.user_id == user.sub,
                VentureDeleteTokens.code == body.code,
                VentureDeleteTokens.expires_at > datetime.utcnow(),
                VentureDeleteTokens.used_at.is_(None),
            ))
        )).scalar_one_or_none() if u else None
        if token is None:
            raise HTTPException(status_code=400, detail="Code invalide ou expiré")
        await s.execute(update(VentureDeleteTokens).where(VentureDeleteTokens.id == token.id)
                        .values(used_at=datetime.utcnow()))
        await s.execute(sa_delete(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub)))
        await s.commit()
    return {"ok": True}


@router.get("/ventures/{vid}/poles", dependencies=[Depends(get_current_user)])
async def list_venture_poles(vid: str, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(select(Poles).where(Poles.venture_id == vid))).scalars().all()
    return [pole(r) for r in rows]


class CreatePoleInVenture(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    description: str = ""
    emoji: str = "🌍"
    couleur: str = "#6366f1"
    type: str = "custom"  # finance|marketing|sales|ops|legal|custom|dev


@router.post("/ventures/{vid}/poles", dependencies=[Depends(get_current_user)])
async def create_venture_pole(vid: str, body: CreatePoleInVenture, response: Response, request: Request,
                              user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        org_id = await _resolve_org_id(s, request.headers.get("X-Org-ID") or user.org_id, user.sub)
        ou = _uuid(org_id) if org_id else None
        po = Poles(nom=body.nom, description=body.description, emoji=body.emoji, couleur=body.couleur,
                   type=body.type, venture_id=vid, owner_id=user.sub, org_id=ou)
        s.add(po)
        await s.flush()
        s.add(PoleMembers(pole_id=po.id, user_id=user.sub,
                          nom=user.nom or "Utilisateur", avatar_emoji=user.avatar_emoji or "👤", role="owner"))
        s.add(LlmPresets(scope_type="pole", scope_id=str(po.id), venture_id=_uuid(vid), updated_by=user.sub))
        await s.commit()
        await s.refresh(po)
    response.status_code = 201
    return pole(po)


async def _lire_identite(geo_object_id: str | None) -> dict:
    if not geo_object_id:
        return {"statut": "absent"}
    if not settings.GEO_URL:
        return {"statut": "indisponible", "geoObjectId": geo_object_id}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            headers = {"X-API-Key": settings.GEO_KEY} if settings.GEO_KEY else {}
            r = await c.get(f"{settings.GEO_URL.rstrip('/')}/objets/{geo_object_id}", headers=headers)
        if r.status_code != 200:
            return {"statut": "indisponible", "geoObjectId": geo_object_id}
        return r.json()
    except httpx.HTTPError:
        return {"statut": "indisponible", "geoObjectId": geo_object_id}


async def _lire_audit_business(audit_id: str | None) -> dict:
    if not audit_id:
        return {"statut": "absent"}
    if not settings.AUDIT_URL:
        return {"statut": "indisponible", "auditId": audit_id}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{settings.AUDIT_URL.rstrip('/')}/audits/{audit_id}")
        if r.status_code != 200:
            return {"statut": "indisponible", "auditId": audit_id}
        return r.json()
    except httpx.HTTPError:
        return {"statut": "indisponible", "auditId": audit_id}


async def _lister_documents(vid: str) -> list[dict]:
    if not settings.INGESTION_URL:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            headers = {"X-API-Key": settings.INGESTION_KEY} if settings.INGESTION_KEY else {}
            r = await c.get(f"{settings.INGESTION_URL.rstrip('/')}/documents",
                            params={"venture_id": vid}, headers=headers)
        if r.status_code != 200:
            return []
        return r.json().get("documents", [])
    except httpx.HTTPError:
        return []


@router.get("/ventures/{vid}/dossier", dependencies=[Depends(get_current_user)])
async def get_venture_dossier(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")

        poles_rows = (await s.execute(select(Poles).where(Poles.venture_id == vid))).scalars().all()
        pole_ids = [p.id for p in poles_rows]
        missions_rows = []
        if pole_ids:
            missions_rows = (await s.execute(
                select(AuditMissions).where(AuditMissions.pole_id.in_(pole_ids))
            )).scalars().all()

    identite = await _lire_identite(v.geo_object_id)
    audit_business = await _lire_audit_business(v.audit_id)
    documents = await _lister_documents(vid)

    return {
        "identite": identite,
        "audit": audit_business,
        "auditMissions": [audit_mission(m) for m in missions_rows],
        "documents": documents,
        "profilEntreprise": v.profil_entreprise,
    }
