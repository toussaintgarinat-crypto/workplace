"""Router saved-filters (filtres enregistrés). Portage de routes/saved-filters.ts (S135).

Monté /api, protégé. Filtres par utilisateur, scopés org (header X-Org-ID) et contexte.
``filtre`` est stocké en TEXT JSON (sérialisé à l'écriture, renvoyé brut comme Drizzle).
"""

from __future__ import annotations

import json
import uuid as uuidlib

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import and_, desc, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import SavedFilters
from app.serde import saved_filter

router = APIRouter()


def _uuid(v: str):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/saved-filters")
async def list_saved_filters(request: Request,
                             org_id: str = Depends(require_org),
                             user: UserContext = Depends(get_current_user)):
    contexte = request.query_params.get("contexte")
    where = [SavedFilters.user_id == user.sub, SavedFilters.org_id == org_id]
    if contexte:
        where.append(SavedFilters.contexte == contexte)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(SavedFilters).where(and_(*where)).order_by(desc(SavedFilters.created_at))
        )).scalars().all()
    return [saved_filter(r) for r in rows]


@router.post("/saved-filters")
async def create_saved_filter(body: dict, response: Response,
                              org_id: str = Depends(require_org),
                              user: UserContext = Depends(get_current_user)):
    nom = (body.get("nom") or "").strip()
    filtre = body.get("filtre")
    if not nom or len(nom) > 200 or not isinstance(filtre, dict):
        response.status_code = 400
        return {"error": "Invalid body"}
    async with SessionLocal() as s:
        row = SavedFilters(
            user_id=user.sub, org_id=org_id,
            nom=nom, contexte=body.get("contexte") or "",
            filtre=json.dumps(filtre),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    response.status_code = 201
    return saved_filter(row)


@router.delete("/saved-filters/{fid}", dependencies=[Depends(get_current_user)])
async def delete_saved_filter(fid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(fid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(SavedFilters).where(and_(
                SavedFilters.id == u, SavedFilters.user_id == user.sub,
            )))
            await s.commit()
    return {"ok": True}
