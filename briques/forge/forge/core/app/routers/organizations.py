"""Router organizations. Portage de routes/organizations.ts (S131). Monté /api/orgs, protégé.

Multi-tenant : organisations + membres (owner/admin/member), invitation par email,
suppression réservée au owner (interdite pour l'org personnelle).
"""

from __future__ import annotations

import re
import time
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import Text, and_, cast, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import OrganizationMembers, Organizations, Users
from app.serde import iso, organization

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("", dependencies=[Depends(get_current_user)])
async def list_orgs(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Organizations, OrganizationMembers.role)
            .join(OrganizationMembers, OrganizationMembers.org_id == Organizations.id)
            .where(OrganizationMembers.user_id == user.sub)
        )).all()
    return [
        {**organization(org), "role": role, "active": str(org.id) == user.org_id}
        for org, role in rows
    ]


class CreateOrg(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    emoji: str = "🏢"
    slug: str | None = Field(default=None, min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")


@router.post("", dependencies=[Depends(get_current_user)])
async def create_org(body: CreateOrg, response: Response, user: UserContext = Depends(get_current_user)):
    slug = body.slug or f"{re.sub(r'[^a-z0-9]', '-', body.nom.lower())}-{int(time.time() * 1000)}"
    async with SessionLocal() as s:
        org = Organizations(nom=body.nom, emoji=body.emoji, slug=slug, owner_id=user.sub, plan="team")
        s.add(org)
        await s.flush()
        s.add(OrganizationMembers(org_id=org.id, user_id=user.sub, role="owner"))
        await s.commit()
        await s.refresh(org)
    response.status_code = 201
    return organization(org)


@router.get("/{org_id}", dependencies=[Depends(get_current_user)])
async def get_org(org_id: str, user: UserContext = Depends(get_current_user)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        membership = (await s.execute(
            select(OrganizationMembers).where(and_(
                OrganizationMembers.org_id == oid, OrganizationMembers.user_id == user.sub))
        )).scalar_one_or_none() if oid else None
        if membership is None:
            raise HTTPException(status_code=404, detail="Not found")
        org = (await s.execute(select(Organizations).where(Organizations.id == oid))).scalar_one_or_none()
        members_rows = (await s.execute(
            select(
                OrganizationMembers.id,
                OrganizationMembers.user_id,
                OrganizationMembers.role,
                OrganizationMembers.joined_at,
                Users.nom,
                Users.avatar_emoji,
                Users.email,
            )
            .join(Users, cast(Users.id, Text) == OrganizationMembers.user_id)
            .where(OrganizationMembers.org_id == oid)
        )).all()
    members = [
        {
            "id": str(m_id),
            "userId": m_user_id,
            "role": m_role,
            "joinedAt": iso(m_joined),
            "nom": m_nom,
            "avatarEmoji": m_avatar,
            "email": m_email,
        }
        for (m_id, m_user_id, m_role, m_joined, m_nom, m_avatar, m_email) in members_rows
    ]
    return {**organization(org), "members": members, "myRole": membership.role}


class UpdateOrg(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=100)
    emoji: str | None = None


@router.patch("/{org_id}", dependencies=[Depends(get_current_user)])
async def update_org(org_id: str, body: UpdateOrg, user: UserContext = Depends(get_current_user)):
    oid = _uuid(org_id)
    data = body.model_dump(exclude_unset=True)
    async with SessionLocal() as s:
        org = None
        if oid:
            if data:
                await s.execute(
                    update(Organizations)
                    .where(and_(Organizations.id == oid, Organizations.owner_id == user.sub))
                    .values(**data)
                )
                await s.commit()
            org = (await s.execute(
                select(Organizations).where(and_(
                    Organizations.id == oid, Organizations.owner_id == user.sub))
            )).scalar_one_or_none()
        if org is None:
            # S223 — 404 : « organisation d'autrui » et « organisation inexistante »
            # doivent porter le même code, pas seulement le même libellé.
            raise HTTPException(status_code=404, detail="Not found")
    return organization(org)


class AddMember(BaseModel):
    email: str
    role: str = "member"


@router.post("/{org_id}/members", dependencies=[Depends(get_current_user)])
async def add_member(org_id: str, body: AddMember, user: UserContext = Depends(get_current_user)):
    oid = _uuid(org_id)
    if body.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")
    async with SessionLocal() as s:
        my = (await s.execute(
            select(OrganizationMembers).where(and_(
                OrganizationMembers.org_id == oid, OrganizationMembers.user_id == user.sub))
        )).scalar_one_or_none() if oid else None
        if my is None or my.role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Forbidden")
        target = (await s.execute(
            select(Users).where(Users.email == body.email)
        )).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        stmt = pg_insert(OrganizationMembers).values(
            org_id=oid, user_id=str(target.id), role=body.role
        ).on_conflict_do_update(
            index_elements=[OrganizationMembers.org_id, OrganizationMembers.user_id],
            set_={"role": body.role},
        )
        await s.execute(stmt)
        await s.commit()
    return {"ok": True, "userId": str(target.id), "role": body.role}


@router.delete("/{org_id}/members/{user_id}", dependencies=[Depends(get_current_user)])
async def remove_member(org_id: str, user_id: str, user: UserContext = Depends(get_current_user)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        # S223 — l'appartenance est vérifiée AVANT toute règle métier. Dans l'ordre
        # inverse (règle métier d'abord), un non-membre qui balayait les identifiants
        # recevait 400 « Cannot remove owner » quand il tombait juste, et 403 sinon :
        # le code de retour révélait à la fois l'existence de l'organisation ET
        # l'identité de son propriétaire.
        my = (await s.execute(
            select(OrganizationMembers).where(and_(
                OrganizationMembers.org_id == oid, OrganizationMembers.user_id == user.sub))
        )).scalar_one_or_none() if oid else None
        if my is None:
            raise HTTPException(status_code=404, detail="Not found")
        if my.role not in ("owner", "admin") and user_id != user.sub:
            raise HTTPException(status_code=403, detail="Forbidden")
        org = (await s.execute(select(Organizations).where(Organizations.id == oid))).scalar_one_or_none() if oid else None
        if org is not None and org.owner_id == user_id:
            raise HTTPException(status_code=400, detail="Cannot remove owner")
        await s.execute(sa_delete(OrganizationMembers).where(and_(
            OrganizationMembers.org_id == oid, OrganizationMembers.user_id == user_id)))
        await s.commit()
    return {"ok": True}


@router.delete("/{org_id}", dependencies=[Depends(get_current_user)])
async def delete_org(org_id: str, user: UserContext = Depends(get_current_user)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        org = (await s.execute(select(Organizations).where(Organizations.id == oid))).scalar_one_or_none() if oid else None
        if org is None or org.owner_id != user.sub:
            # S223 — 404 : inexistante et « pas la vôtre » sont déjà confondues ici ;
            # on aligne le code sur le reste de la brique.
            raise HTTPException(status_code=404, detail="Not found")
        if org.plan == "personal":
            raise HTTPException(status_code=400, detail="Cannot delete personal org")
        await s.execute(sa_delete(Organizations).where(Organizations.id == oid))
        await s.commit()
    return {"ok": True}
