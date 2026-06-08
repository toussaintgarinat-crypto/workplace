"""Router rapports. Portage de routes/rapport.ts (S130). Monté /api, protégé.

Liste + génération d'un rapport agrégé (finance/CRM/incidents sur 7 ou 30 j) en
markdown + suppression. Pas de LLM ici : agrégation SQL pure.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.fmt import fr_date, fr_datetime, fr_number
from app.models import BudgetEntries, CrmLeads, Incidents, Poles, Rapports
from app.serde import rapport

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/rapports")
async def list_rapports(
    request: Request,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    # S18 (Chantier 1) : scope org validée obligatoire, jamais le header cru.
    type_q = request.query_params.get("type")
    async with SessionLocal() as s:
        where = and_(Rapports.user_id == user.sub, Rapports.org_id == _uuid(org_id))
        if type_q:
            where = and_(where, Rapports.type == type_q)
        rows = (await s.execute(
            select(Rapports).where(where).order_by(desc(Rapports.created_at))
        )).scalars().all()
    return [rapport(r) for r in rows]


class GenerateRapport(BaseModel):
    type: str | None = None  # weekly|monthly|audit|custom
    periode: str | None = None


@router.post("/rapports/generate")
async def generate_rapport(body: GenerateRapport, response: Response,
                           user: UserContext = Depends(get_current_user),
                           org_id: str = Depends(require_org)):
    rtype = body.type or "weekly"
    now = datetime.utcnow()
    depuis = now - timedelta(days=30 if rtype == "monthly" else 7)

    async with SessionLocal() as s:
        user_poles = (await s.execute(
            select(Poles).where(Poles.owner_id == user.sub)
        )).scalars().all()
        budget_rows = (await s.execute(
            select(BudgetEntries.type, func.sum(BudgetEntries.montant))
            .where(and_(BudgetEntries.user_id == user.sub, BudgetEntries.date >= depuis))
            .group_by(BudgetEntries.type)
        )).all()
        leads = (await s.execute(
            select(CrmLeads).where(and_(CrmLeads.user_id == user.sub, CrmLeads.created_at >= depuis))
        )).scalars().all()
        open_incidents = (await s.execute(
            select(Incidents).where(and_(Incidents.user_id == user.sub, Incidents.statut == "ouvert"))
        )).scalars().all()

        budget = {row[0]: (row[1] or 0) for row in budget_rows}
        recettes = budget.get("recette", 0)
        depenses = budget.get("depense", 0)
        periode = body.periode or f"{fr_date(depuis)} - {fr_date(now)}"
        type_label = "hebdomadaire" if rtype == "weekly" else "mensuel" if rtype == "monthly" else rtype
        titre = f"Rapport {type_label} — {periode}"

        leads_gagnes = sum(1 for ld in leads if ld.statut == "gagne")
        leads_qualifies = sum(1 for ld in leads if ld.statut == "qualifie")
        incidents_lines = "\n".join(
            f"  - [{(i.severite or '').upper()}] {i.titre}" for i in open_incidents[:3]
        )

        contenu = f"""# {titre}

## 📊 Vue d'ensemble
- **Pôles actifs** : {len(user_poles)}
- **Période** : {periode}

## 💰 Finance
- Recettes : {fr_number(recettes)} €
- Dépenses : {fr_number(depenses)} €
- Solde : **{fr_number(recettes - depenses)} €**

## 🤝 CRM
- Nouveaux leads : {len(leads)}
- Leads gagnés : {leads_gagnes}
- Pipeline : {leads_qualifies} qualifiés

## 🚨 Incidents
- Incidents ouverts : {len(open_incidents)}
{incidents_lines}

*Rapport généré automatiquement le {fr_datetime(now)}*"""

        rap = Rapports(user_id=user.sub, org_id=_uuid(org_id),
                       titre=titre, contenu=contenu, type=rtype, periode=periode)
        s.add(rap)
        await s.commit()
        await s.refresh(rap)
    response.status_code = 201
    return rapport(rap)


@router.delete("/rapports/{rid}", dependencies=[Depends(get_current_user)])
async def delete_rapport(rid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(rid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(Rapports)
                            .where(and_(Rapports.id == u, Rapports.user_id == user.sub)))
            await s.commit()
    return {"ok": True}
