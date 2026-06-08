"""Router RGPD exécutable (S18, Chantier 2). Monté /api, protégé.

Droits du sujet, **réels** (pas seulement audités) :
- ``GET  /rgpd/apercu``   — ce qui serait effacé (comptage par table), sans rien supprimer.
- ``GET  /rgpd/export``   — accès & portabilité (Art. 15 & 20) : toutes ses données en JSON.
- ``POST /rgpd/effacer``  — droit à l'effacement (Art. 17) : Postgres + Qdrant + Mémoire.

Périmètre : le **sujet authentifié lui-même** (self-service), scopé ``user.sub`` sur
toutes les orgs où il a des données. L'effacement exige une confirmation explicite.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app import rgpd as rgpd_svc
from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.routers.audit_logs import log_audit

router = APIRouter()


@router.get("/rgpd/apercu")
async def apercu_donnees(user: UserContext = Depends(get_current_user)):
    """Comptage par table de ce que l'effacement supprimerait (lecture seule)."""
    uid = rgpd_svc._as_uuid(user.sub)
    apercu: dict[str, int] = {}
    async with SessionLocal() as s:
        for table in [t for t in rgpd_svc.Base.metadata.sorted_tables if "user_id" in t.c]:
            from sqlalchemy import func
            n = (await s.execute(
                select(func.count()).select_from(table).where(table.c.user_id == uid)
            )).scalar_one()
            if n:
                apercu[table.name] = int(n)
    return {"sujet": user.sub, "tables": apercu, "total": sum(apercu.values())}


@router.get("/rgpd/export")
async def export_donnees(user: UserContext = Depends(get_current_user)):
    """Accès & portabilité (Art. 15 & 20) : toutes les données du sujet en JSON."""
    async with SessionLocal() as s:
        data = await rgpd_svc.export_user_postgres(s, user.sub)
    # Trace d'audit (Art. 30) — l'export n'efface rien, le sujet existe → audit_logs OK.
    await log_audit(
        user_id=user.sub, org_id=user.org_id,
        action="rgpd_export", entite="rgpd", entite_id=user.sub,
        details={"tables": list(data.keys())},
    )
    return JSONResponse(content={
        "sujet": user.sub,
        "format": "json",
        "donnees": data,
    })


class EffacerBody(BaseModel):
    confirmation: str  # doit valoir "EFFACER" pour exécuter


@router.post("/rgpd/effacer")
async def effacer_donnees(body: EffacerBody, user: UserContext = Depends(get_current_user)):
    """Droit à l'effacement (Art. 17) — multi-store, irréversible.

    Garde-fou : ``confirmation`` doit valoir exactement ``EFFACER`` (sinon 400).
    """
    if body.confirmation != "EFFACER":
        raise HTTPException(status_code=400, detail="Confirmation requise : 'EFFACER'")
    async with SessionLocal() as s:
        recu = await rgpd_svc.erase_user_all_stores(s, user.sub)
    return recu
