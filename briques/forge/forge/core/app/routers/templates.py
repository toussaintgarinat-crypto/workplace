"""Router templates. Portage de routes/templates.ts (S133). Monté /api, protégé.

Templates de contenu (contrat/email/rapport/brief/autre). Visibilité : les
siens (``user.sub``) OU publics ; filtrés en plus par org (X-Org-ID) et type
(``?type=``). Colonne variables = TEXT JSON.
"""

from __future__ import annotations

import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import Templates
from app.serde import template

router = APIRouter()

_TYPES = ("contrat", "email", "rapport", "brief", "autre")


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/templates")
async def list_templates(
    type: str | None = None,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    # Visibilité : les siens OU publics ; en plus bornés à l'org active (ou publics
    # — partage cross-org volontaire, pas une fuite).
    cond = [
        or_(Templates.user_id == user.sub, Templates.public.is_(True)),
        or_(Templates.org_id == oid, Templates.public.is_(True)),
    ]
    if type:
        cond.append(Templates.type == type)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Templates).where(and_(*cond)).order_by(desc(Templates.created_at))
        )).scalars().all()
    return [template(x) for x in rows]


class CreateTemplate(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str | None = None
    type: str | None = None
    contenu: str = Field(min_length=1)
    variables: list[str] | None = None
    public: bool | None = None


@router.post("/templates")
async def create_template(
    body: CreateTemplate,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    oid = _uuid(org_id)
    ttype = body.type if body.type in _TYPES else "autre"
    async with SessionLocal() as s:
        tmpl = Templates(
            user_id=user.sub, org_id=oid,
            nom=body.nom, description=body.description or "",
            type=ttype, contenu=body.contenu,
            variables=json.dumps(body.variables or []),
            public=body.public if body.public is not None else False,
        )
        s.add(tmpl)
        await s.commit()
        await s.refresh(tmpl)
    return JSONResponse(status_code=201, content=template(tmpl))


class PatchTemplate(BaseModel):
    nom: str | None = None
    description: str | None = None
    contenu: str | None = None
    variables: list[str] | None = None
    public: bool | None = None


@router.patch("/templates/{tid}", dependencies=[Depends(get_current_user)])
async def patch_template(tid: str, body: PatchTemplate, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    raw = body.model_dump(exclude_unset=True)
    cols: dict = {}
    for k in ("nom", "description", "contenu", "public"):
        if k in raw:
            cols[k] = raw[k]
    if body.variables is not None:
        cols["variables"] = json.dumps(body.variables)
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        tmpl = None
        if tuid:
            await s.execute(
                update(Templates).where(and_(Templates.id == tuid, Templates.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            tmpl = (await s.execute(
                select(Templates).where(and_(Templates.id == tuid, Templates.user_id == user.sub))
            )).scalar_one_or_none()
    return template(tmpl) if tmpl is not None else None


@router.delete("/templates/{tid}", dependencies=[Depends(get_current_user)])
async def delete_template(tid: str, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    async with SessionLocal() as s:
        if tuid:
            await s.execute(
                sa_delete(Templates).where(and_(Templates.id == tuid, Templates.user_id == user.sub))
            )
            await s.commit()
    return {"ok": True}
