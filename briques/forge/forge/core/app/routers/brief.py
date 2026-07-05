"""Router brief (génération IA). Portage de routes/brief.ts (S130). Monté /api, protégé.

Brief matinal généré par le LLM à partir des événements blackboard (24h) et des
décisions N0 en attente. LLM via la gateway (`generate_text`) — l'ancien chemin
`generateWithOllama` direct est unifié sous la gateway (décision S128). Fallback
statique si le LLM est indisponible.
"""

from __future__ import annotations

import logging
import uuid as uuidlib
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy import and_, desc, select

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.fmt import fr_date_long
from app.llm import LlmContext, generate_text, resolve_llm_config
from app.models import BlackboardEvents, DecisionsN0, Poles, Ventures

router = APIRouter()
logger = logging.getLogger(__name__)


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


class CorpsBrief(BaseModel):
    ventureId: str | None = None


@router.post("/brief/generate")
async def generate_brief(
    body: CorpsBrief = Body(default_factory=CorpsBrief),
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    venture_id = body.ventureId
    since = datetime.utcnow() - timedelta(hours=24)

    # S18 (Chantier 1) : le blackboard n'a pas d'org_id direct — il se scope via son
    # pole_id → poles.org_id. On borne donc aux pôles de l'**org active** validée, et
    # JAMAIS de repli global (avant, l'absence de venture lisait tous les orgs).
    oid = _uuid(org_id)
    venture_nom = None
    async with SessionLocal() as s:
        # Pôles visibles = ceux de l'org active.
        pole_rows = (await s.execute(
            select(Poles.id).where(Poles.org_id == oid)
        )).all()
        pole_ids: list = [p[0] for p in pole_rows]

        if venture_id:
            vu = _uuid(venture_id)
            # La venture doit appartenir à l'org active, sinon pas d'accès.
            v = (await s.execute(
                select(Ventures).where(and_(Ventures.id == vu, Ventures.org_id == oid))
            )).scalar_one_or_none() if vu else None
            if v:
                venture_nom = v.nom
                venture_poles = (await s.execute(
                    select(Poles.id).where(and_(Poles.venture_id == vu, Poles.org_id == oid))
                )).all()
                pole_ids = [p[0] for p in venture_poles]
            else:
                pole_ids = []  # venture inconnue / autre org → rien

        if pole_ids:
            events = (await s.execute(
                select(BlackboardEvents).where(and_(
                    BlackboardEvents.created_at >= since, BlackboardEvents.pole_id.in_(pole_ids)))
                .order_by(desc(BlackboardEvents.created_at)).limit(20)
            )).scalars().all()
            pending = (await s.execute(
                select(DecisionsN0).where(and_(
                    DecisionsN0.statut == "en_attente", DecisionsN0.pole_id.in_(pole_ids)))
            )).scalars().all()
        else:
            events, pending = [], []

    events_text = "\n".join(
        f"[{e.pole_nom}] {e.agent_nom}: {(e.payload or '')[:150]}" for e in events
    ) if events else "Aucun événement"

    date = fr_date_long(datetime.utcnow())
    scope = f'la venture "{venture_nom}"' if venture_nom else "toute l'organisation"

    try:
        # S18 (Chantier 1) : org validée pour le choix du preset LLM, jamais le header cru.
        preset = await resolve_llm_config(LlmContext(venture_id=venture_id, org_id=org_id))
        provider = preset.provider if preset else None
        model = preset.model if preset else None
        prompt = f"""Tu es l'assistant IA de Forge, OS d'entreprise autonome.
Le fondateur commence sa journée. Génère un brief matinal concis en français (300 mots max) pour {scope}.

Données :
- Événements (24h) : {events_text}
- Décisions en attente : {len(pending)}
- Date : {date}

Structure :
## 🌅 Ce qui s'est passé
[Points clés des 24h]

## ⚡ Points d'attention
[Risques, blocages, décisions à prendre]

## 🎯 Actions recommandées
[Top 3 priorités du jour]"""
        brief_text = await generate_text(prompt=prompt, provider=provider, model=model, max_tokens=600)
    except Exception as err:  # noqa: BLE001
        logger.error("[forge:brief] LLM error: %s", str(err)[:120])
        activite = f"### Activité récente\n{events_text}" if events else ""
        brief_text = f"""## 🌅 {date}

**Événements des 24h :** {f"{len(events)} événement(s) enregistré(s)" if events else "Aucun événement"}

**Décisions en attente :** {len(pending)} décision(s) à valider

{activite}

_Brief IA non disponible — LLM non configuré ou inaccessible. Configurez un modèle dans les paramètres de Forge._"""

    return {
        "brief": brief_text,
        "generatedAt": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "eventsCount": len(events),
        "pendingDecisions": len(pending),
    }
