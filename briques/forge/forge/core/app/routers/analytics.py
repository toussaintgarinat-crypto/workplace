"""Router analytics (tableau de bord agrégé). Portage de routes/analytics.ts (S135).

Monté /api, protégé. Agrège des compteurs sur 30 jours (pôles, sessions, messages,
CRM, incidents, KB, sprints) + solde budgétaire + 10 derniers événements blackboard.

Parité driver : les ``count()`` de Drizzle sont mappés en nombres (asyncpg renvoie
des int → OK), mais ``SUM(montant)`` (entier) est renvoyé en CHAÎNE par node-postgres
côté Bun. On reproduit ce quirk (cast str) pour ``budget.recettes/depenses``.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import (
    BlackboardEvents, BudgetEntries, CrmLeads, Incidents, KbArticles,
    Messages, Poles, Sessions, Sprints,
)
from app.serde import blackboard_event

router = APIRouter()


def _num(v):
    """Reproduit la coercition JS ``string|0 - string|0`` (soustraction → nombre)."""
    return int(v) if isinstance(v, str) else v


@router.get("/analytics", dependencies=[Depends(get_current_user)])
async def analytics(user: UserContext = Depends(get_current_user)):
    depuis30j = datetime.datetime.utcnow() - datetime.timedelta(days=30)
    sub = user.sub

    async with SessionLocal() as s:
        async def _count(stmt) -> int:
            return (await s.execute(stmt)).scalar_one()

        total_poles = await _count(
            select(func.count()).select_from(Poles).where(Poles.owner_id == sub))
        total_sessions = await _count(
            select(func.count()).select_from(Sessions)
            .where(Sessions.user_id == sub, Sessions.created_at >= depuis30j))
        sub_sessions = select(Sessions.id).where(Sessions.user_id == sub)
        total_messages = await _count(
            select(func.count()).select_from(Messages)
            .where(Messages.role == "user", Messages.session_id.in_(sub_sessions)))
        total_leads = await _count(
            select(func.count()).select_from(CrmLeads).where(CrmLeads.user_id == sub))
        leads_gagnes = await _count(
            select(func.count()).select_from(CrmLeads)
            .where(CrmLeads.user_id == sub, CrmLeads.statut == "gagne"))
        incidents_ouverts = await _count(
            select(func.count()).select_from(Incidents)
            .where(Incidents.user_id == sub, Incidents.statut == "ouvert"))
        total_kb = await _count(
            select(func.count()).select_from(KbArticles).where(KbArticles.user_id == sub))
        total_sprints = await _count(
            select(func.count()).select_from(Sprints).where(Sprints.user_id == sub))

        budget_rows = (await s.execute(
            select(BudgetEntries.type, func.sum(BudgetEntries.montant))
            .where(BudgetEntries.user_id == sub, BudgetEntries.date >= depuis30j)
            .group_by(BudgetEntries.type)
        )).all()

        recent_events = (await s.execute(
            select(BlackboardEvents).where(BlackboardEvents.created_at >= depuis30j)
            .order_by(desc(BlackboardEvents.created_at)).limit(10)
        )).scalars().all()

    # quirk Bun : SUM(integer) → chaîne (node-postgres). On caste en str si présent.
    budget_map = {t: (str(total) if total is not None else "0") for t, total in budget_rows}
    recettes = budget_map.get("recette", 0)
    depenses = budget_map.get("depense", 0)

    return {
        "poles": total_poles,
        "sessions30j": total_sessions,
        "messages": total_messages,
        "crm": {"total": total_leads, "gagnes": leads_gagnes},
        "incidentsOuverts": incidents_ouverts,
        "kb": total_kb,
        "sprints": total_sprints,
        "budget": {"recettes": recettes, "depenses": depenses,
                   "solde": _num(recettes) - _num(depenses)},
        "recentEvents": [blackboard_event(r) for r in recent_events],
    }
