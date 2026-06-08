"""Router morning-brief. Portage de routes/morning-brief.ts (S130). Monté /api, protégé.

Config du brief matinal + génération d'un brief statique (sans LLM) + historique +
marquage lu. Pas de collision avec brief.py (POST /brief/generate) : ici /brief/config.
"""

from __future__ import annotations

import json
import uuid as uuidlib
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import and_, desc, select, update

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.fmt import fr_date_long, fr_datetime
from app.models import BriefConfigs, Briefs, Incidents, Poles
from app.serde import brief, brief_config

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/brief/config", dependencies=[Depends(get_current_user)])
async def get_config(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        cfg = (await s.execute(
            select(BriefConfigs).where(BriefConfigs.user_id == user.sub)
        )).scalar_one_or_none()
    if cfg is None:
        return {"enabled": True, "heureUtc": "07:00", "joursSemaine": "[1,2,3,4,5]"}
    return brief_config(cfg)


class PutConfig(BaseModel):
    enabled: bool | None = None
    heureUtc: str | None = None
    joursSemaine: list[int] | None = None


@router.put("/brief/config")
async def put_config(body: PutConfig, response: Response,
                     user: UserContext = Depends(get_current_user),
                     org_id: str = Depends(require_org)):
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(BriefConfigs).where(BriefConfigs.user_id == user.sub)
        )).scalar_one_or_none()
        if existing:
            cols: dict = {"updated_at": datetime.utcnow()}
            if body.enabled is not None:
                cols["enabled"] = body.enabled
            if body.heureUtc is not None:
                cols["heure_utc"] = body.heureUtc
            if body.joursSemaine is not None:
                cols["jours_semaine"] = json.dumps(body.joursSemaine)
            await s.execute(update(BriefConfigs).where(BriefConfigs.id == existing.id).values(**cols))
            await s.commit()
            updated = (await s.execute(
                select(BriefConfigs).where(BriefConfigs.id == existing.id)
            )).scalar_one_or_none()
            return brief_config(updated)
        created = BriefConfigs(
            user_id=user.sub, org_id=_uuid(org_id),
            enabled=body.enabled if body.enabled is not None else True,
            heure_utc=body.heureUtc or "07:00",
            jours_semaine=json.dumps(body.joursSemaine) if body.joursSemaine is not None else "[1,2,3,4,5]",
        )
        s.add(created)
        await s.commit()
        await s.refresh(created)
    response.status_code = 201
    return brief_config(created)


@router.get("/briefs")
async def list_briefs(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    async with SessionLocal() as s:
        where = and_(Briefs.user_id == user.sub, Briefs.org_id == _uuid(org_id))
        rows = (await s.execute(
            select(Briefs).where(where).order_by(desc(Briefs.created_at)).limit(50)
        )).scalars().all()
    return [brief(b) for b in rows]


@router.post("/briefs/generate")
async def generate_brief(response: Response,
                         user: UserContext = Depends(get_current_user),
                         org_id: str = Depends(require_org)):
    async with SessionLocal() as s:
        user_poles = (await s.execute(
            select(Poles.nom, Poles.emoji).where(Poles.owner_id == user.sub).limit(5)
        )).all()
        recent_incidents = (await s.execute(
            select(Incidents.titre, Incidents.severite).where(Incidents.user_id == user.sub)
            .order_by(desc(Incidents.created_at)).limit(3)
        )).all()

        now = datetime.utcnow()
        titre = f"Brief du {fr_date_long(now, with_year=False)}"
        poles_lines = "\n".join(f"- {p.emoji} **{p.nom}**" for p in user_poles) or "- Aucun pôle configuré"
        inc_lines = "\n".join(
            f"- [{(i.severite or '').upper()}] {i.titre}" for i in recent_incidents
        ) or "- Aucun incident ouvert"

        contenu = f"""# {titre}

## 📊 Pôles actifs
{poles_lines}

## 🚨 Incidents récents
{inc_lines}

## 📋 À faire aujourd'hui
- Vérifier les décisions N0 en attente
- Passer en revue les métriques SLO
- Consulter le pipeline CRM

*Brief généré automatiquement le {fr_datetime(now)}*"""

        b = Briefs(user_id=user.sub, org_id=_uuid(org_id),
                   titre=titre, contenu=contenu, type="morning")
        s.add(b)
        await s.commit()
        await s.refresh(b)
    response.status_code = 201
    return brief(b)


@router.patch("/briefs/{bid}/lu", dependencies=[Depends(get_current_user)])
async def mark_read(bid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(bid)
    async with SessionLocal() as s:
        b = None
        if u:
            await s.execute(update(Briefs).where(and_(Briefs.id == u, Briefs.user_id == user.sub))
                            .values(lu=True))
            await s.commit()
            b = (await s.execute(
                select(Briefs).where(and_(Briefs.id == u, Briefs.user_id == user.sub))
            )).scalar_one_or_none()
    return brief(b) if b else None
