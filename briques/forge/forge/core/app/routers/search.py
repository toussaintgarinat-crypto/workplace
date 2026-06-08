"""Router recherche globale. Portage de routes/search.ts (S129). Monté /api, protégé.

Recherche LIKE (sensible à la casse, comme le Bun) sur 5 entités, ≤5 résultats chacune,
agrégées par catégorie. Pas de RAG ici (recherche structurée plein-texte simple).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Contrats, CrmLeads, Incidents, KbArticles, Sessions

router = APIRouter()


@router.get("/search", dependencies=[Depends(get_current_user)])
async def search(request: Request, user: UserContext = Depends(get_current_user)):
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return {"results": []}
    p = f"%{q}%"
    uid = user.sub

    async def _q(stmt):
        async with SessionLocal() as s:
            return (await s.execute(stmt)).all()

    kb_stmt = (select(KbArticles.id, KbArticles.titre, KbArticles.tags.label("type"),
                      KbArticles.contenu.label("entity"))
               .where(and_(KbArticles.user_id == uid,
                           or_(KbArticles.titre.like(p), KbArticles.contenu.like(p)))).limit(5))
    sess_stmt = (select(Sessions.id, Sessions.name.label("titre"), Sessions.name.label("entity"))
                 .where(and_(Sessions.user_id == uid, Sessions.name.like(p))).limit(5))
    lead_stmt = (select(CrmLeads.id, CrmLeads.nom.label("titre"), CrmLeads.entreprise.label("entity"))
                 .where(and_(CrmLeads.user_id == uid,
                             or_(CrmLeads.nom.like(p), CrmLeads.entreprise.like(p)))).limit(5))
    inc_stmt = (select(Incidents.id, Incidents.titre, Incidents.description.label("entity"))
                .where(and_(Incidents.user_id == uid, Incidents.titre.like(p))).limit(5))
    ctr_stmt = (select(Contrats.id, Contrats.titre, Contrats.parties.label("entity"))
                .where(and_(Contrats.user_id == uid, Contrats.titre.like(p))).limit(5))

    kb_r, sess_r, lead_r, inc_r, ctr_r = await asyncio.gather(
        _q(kb_stmt), _q(sess_stmt), _q(lead_stmt), _q(inc_stmt), _q(ctr_stmt))

    def _row(r, category, has_type=False):
        d = {"id": str(r.id), "titre": r.titre, "entity": r.entity, "category": category}
        if has_type:
            d["type"] = r.type
        return d

    results = (
        [_row(r, "KB", has_type=True) for r in kb_r]
        + [{"id": str(r.id), "titre": r.titre, "entity": r.entity, "category": "Conversation"} for r in sess_r]
        + [_row(r, "CRM") for r in lead_r]
        + [_row(r, "Incident") for r in inc_r]
        + [_row(r, "Contrat") for r in ctr_r]
    )
    return {"results": results}
