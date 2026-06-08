"""Router team. Portage de routes/team.ts (S131). Monté /api, protégé.

Membres d'équipe scopés par organisation. S18 (Chantier 1) : l'org provient du
``UserContext`` validé (``require_org``), **jamais** d'un ``X-Org-ID`` brut — sinon
un membre d'une org pouvait lire/modifier l'équipe d'une autre. `poles` stocké en
JSON-string (parité Drizzle).
"""

from __future__ import annotations

import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import TeamMembers
from app.serde import team_member

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/team")
async def list_team(org_id: str = Depends(require_org)):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(TeamMembers).where(TeamMembers.org_id == oid).order_by(desc(TeamMembers.created_at))
        )).scalars().all()
    return [team_member(m) for m in rows]


class CreateMember(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    email: str | None = None
    role: str | None = None
    poles: list[str] | None = None
    statut: str | None = None


@router.post("/team")
async def create_member(
    body: CreateMember,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    async with SessionLocal() as s:
        m = TeamMembers(
            org_id=oid, user_id=user.sub, nom=body.nom, email=body.email or "",
            role=body.role or "viewer", poles=json.dumps(body.poles or []),
            statut=body.statut or "invite",
        )
        s.add(m)
        await s.commit()
        await s.refresh(m)
    return JSONResponse(status_code=201, content=team_member(m))


class UpdateMember(BaseModel):
    nom: str | None = None
    role: str | None = None
    poles: list[str] | None = None
    statut: str | None = None


@router.patch("/team/{mid}")
async def update_member(
    mid: str, body: UpdateMember,
    org_id: str = Depends(require_org),
):
    muid = _uuid(mid)
    raw = body.model_dump(exclude_unset=True)
    cols: dict = {}
    if "nom" in raw:
        cols["nom"] = raw["nom"]
    if "role" in raw:
        cols["role"] = raw["role"]
    if "statut" in raw:
        cols["statut"] = raw["statut"]
    if "poles" in raw:
        cols["poles"] = json.dumps(raw["poles"] or [])
    oid = _uuid(org_id)
    where = and_(TeamMembers.id == muid, TeamMembers.org_id == oid)
    async with SessionLocal() as s:
        if muid and cols:
            await s.execute(update(TeamMembers).where(where).values(**cols))
            await s.commit()
        m = (await s.execute(select(TeamMembers).where(where))).scalar_one_or_none() if muid else None
    return team_member(m) if m else None


@router.delete("/team/{mid}")
async def delete_member(mid: str, org_id: str = Depends(require_org)):
    muid = _uuid(mid)
    oid = _uuid(org_id)
    where = and_(TeamMembers.id == muid, TeamMembers.org_id == oid)
    async with SessionLocal() as s:
        if muid:
            await s.execute(sa_delete(TeamMembers).where(where))
            await s.commit()
    return {"ok": True}
