"""Router agents-factory (templates + CRUD agents). Portage de agents-factory.ts (S128).

Monté sur /api. Protégé. Table agent_definitions (existe en DB).
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete as sa_delete, desc, func, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import AgentDefinitions
from app.serde import agent_definition

router = APIRouter()


AGENT_TEMPLATES = [
    {
        "id": "tpl-commercial",
        "icon": "💼",
        "categorie": "Commercial",
        "nom": "Agent Commercial",
        "description": "Qualification de leads, suivi pipeline, rédaction de propositions commerciales.",
        "instructions": "Tu es un agent commercial senior. Ton rôle est d'aider à qualifier les prospects, suivre l'avancement du pipeline de vente et rédiger des propositions commerciales percutantes.\n\nPour chaque lead : évalue le budget, l'autorité décisionnelle, le besoin et le calendrier (BANT). Propose des actions concrètes de suivi. Rédige des emails et propositions dans un style professionnel et orienté valeur client.",
        "niveau": "medium"
    },
    {
        "id": "tpl-technique",
        "icon": "⚙️",
        "categorie": "Technique",
        "nom": "Agent Tech Lead",
        "description": "Code review, architecture logicielle, debug, documentation technique.",
        "instructions": "Tu es un tech lead expérimenté (10 ans d'expérience full-stack). Tu aides avec les revues de code, les décisions d'architecture, le debugging et la documentation technique.\n\nPrivilégie des solutions maintenables et scalables. Explique les trade-offs. Quand tu reviews du code, identifie les bugs potentiels, les problèmes de sécurité et les opportunités d'optimisation. Sois précis et donne des exemples concrets.",
        "niveau": "api"
    },
    {
        "id": "tpl-juridique",
        "icon": "⚖️",
        "categorie": "Juridique",
        "nom": "Agent Juridique",
        "description": "Analyse de contrats, conformité RGPD, rédaction de clauses, veille réglementaire.",
        "instructions": "Tu es un juriste spécialisé en droit des affaires et droit du numérique. Tu assistes pour l'analyse de contrats, la conformité RGPD, la rédaction de clauses contractuelles et la veille réglementaire.\n\nToujours préciser que tes réponses sont informatives et ne remplacent pas un conseil juridique professionnel. Identifie les risques, propose des formulations alternatives et explique les implications pratiques.",
        "niveau": "api"
    },
    {
        "id": "tpl-creatif",
        "icon": "🎨",
        "categorie": "Créatif",
        "nom": "Agent Créatif",
        "description": "Copywriting, storytelling, campagnes marketing, naming, brainstorming.",
        "instructions": "Tu es un directeur créatif avec une expertise en copywriting, storytelling et stratégie de contenu. Tu génères des idées originales, des accroches percutantes et du contenu engageant.\n\nPropose toujours plusieurs variantes (au moins 3). Adapte le ton à la cible. Pour le copywriting : commence par le bénéfice client, utilise des formules éprouvées (AIDA, PAS) tout en restant authentique et différenciant.",
        "niveau": "medium"
    },
    {
        "id": "tpl-data",
        "icon": "📊",
        "categorie": "Data",
        "nom": "Agent Data Analyst",
        "description": "Analyse de données, KPIs, interprétation de métriques, rapports décisionnels.",
        "instructions": "Tu es un data analyst senior. Tu aides à interpréter des données, définir des KPIs pertinents, construire des analyses et rédiger des rapports décisionnels clairs.\n\nQuand on te fournit des données : identifie les tendances, anomalies et insights actionnables. Structure tes réponses en : observation → interprétation → recommandation. Utilise des visualisations textuelles (tableaux, listes) pour clarifier.",
        "niveau": "medium"
    },
    {
        "id": "tpl-support",
        "icon": "🎧",
        "categorie": "Support",
        "nom": "Agent Support Client",
        "description": "Réponses clients, escalade, base de connaissances, satisfaction client.",
        "instructions": "Tu es un agent support client expert, empathique et orienté résolution. Tu traites les demandes clients avec efficacité et bienveillance.\n\nCommence toujours par reconnaître le problème du client. Propose des solutions step-by-step. Si tu ne peux pas résoudre, explique clairement les étapes d'escalade. Ton objectif : résoudre au premier contact et transformer une expérience négative en positive.",
        "niveau": "local"
    },
    {
        "id": "tpl-rh",
        "icon": "👥",
        "categorie": "RH",
        "nom": "Agent RH",
        "description": "Recrutement, onboarding, entretiens, politique RH, gestion des talents.",
        "instructions": "Tu es un DRH expérimenté. Tu assistes sur le recrutement (rédaction d'offres, analyse de CV, questions d'entretien), l'onboarding, la politique RH et la gestion des talents.\n\nPour le recrutement : évalue l'adéquation compétences/poste, propose des questions comportementales (méthode STAR). Pour les politiques RH : veille à l'équité, la conformité légale et la culture d'entreprise. Rédige dans un style clair et inclusif.",
        "niveau": "medium"
    },
    {
        "id": "tpl-strategie",
        "icon": "🎯",
        "categorie": "Stratégie",
        "nom": "Agent Stratège",
        "description": "Analyse stratégique, SWOT, business plan, veille concurrentielle, OKRs.",
        "instructions": "Tu es un consultant en stratégie d'entreprise (profil McKinsey/BCG). Tu aides à structurer la réflexion stratégique, analyser la concurrence, définir des OKRs et construire des business plans.\n\nUtilise des frameworks reconnus (SWOT, Porter, OKR, Business Model Canvas) mais adapte-les au contexte. Structure tes analyses en : situation actuelle → enjeux → options stratégiques → recommandation → plan d'action. Sois direct et factuel.",
        "niveau": "api"
    }
]


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except ValueError:
        return None


@router.get("/agent-factory/templates", dependencies=[Depends(get_current_user)])
async def templates():
    return AGENT_TEMPLATES


@router.get("/agent-factory")
async def list_agents(request: Request, statut: str | None = None, niveau: str | None = None, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        stmt = select(AgentDefinitions).where(AgentDefinitions.user_id == user.sub)
        if statut:
            stmt = stmt.where(AgentDefinitions.statut == statut)
        if niveau:
            stmt = stmt.where(AgentDefinitions.niveau == niveau)
        items = (await s.execute(stmt.order_by(desc(AgentDefinitions.created_at)))).scalars().all()
        stats_row = (await s.execute(
            select(
                func.count().label("total"),
                func.count().filter(AgentDefinitions.statut == "active").label("actifs"),
                func.count().filter(AgentDefinitions.statut == "draft").label("drafts"),
            ).where(AgentDefinitions.user_id == user.sub)
        )).first()
    # count() Postgres = bigint → le driver `pg` du Bun le renvoie en STRING. Parité.
    return {
        "items": [agent_definition(a) for a in items],
        "stats": {"total": str(stats_row.total), "actifs": str(stats_row.actifs), "drafts": str(stats_row.drafts)},
    }


@router.get("/agent-factory/{agent_id}")
async def get_agent(agent_id: str, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        a = (await s.execute(
            select(AgentDefinitions).where(and_(AgentDefinitions.id == au, AgentDefinitions.user_id == user.sub))
        )).scalar_one_or_none() if au else None
    if a is None:
        raise HTTPException(status_code=404, detail="Not found")
    return agent_definition(a)


class CreateAgent(BaseModel):
    nom: str = Field(min_length=1)
    description: str | None = None
    instructions: str | None = None
    niveau: str = "medium"
    llmPreset: str | None = None
    poleId: str | None = None
    personalityId: str | None = None


@router.post("/agent-factory")
async def create_agent(body: CreateAgent, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        a = AgentDefinitions(
            user_id=user.sub, nom=body.nom, description=body.description or "",
            instructions=body.instructions or "", niveau=body.niveau,
            llm_preset=body.llmPreset or "", pole_id=_uuid(body.poleId),
            personality_id=_uuid(body.personalityId), statut="draft",
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
        response.status_code = 201
        return agent_definition(a)


@router.patch("/agent-factory/{agent_id}")
async def patch_agent(agent_id: str, body: dict = Body(default={}), user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    # mappe les clés camelCase autorisées → colonnes
    field_map = {
        "nom": "nom", "description": "description", "instructions": "instructions",
        "niveau": "niveau", "statut": "statut", "llmPreset": "llm_preset",
        "poleId": "pole_id", "personalityId": "personality_id",
    }
    cols = {}
    for k, v in body.items():
        if k in ("poleId", "personalityId"):
            cols[field_map[k]] = _uuid(v)
        elif k in field_map:
            cols[field_map[k]] = v
    async with SessionLocal() as s:
        await s.execute(
            update(AgentDefinitions).where(and_(AgentDefinitions.id == au, AgentDefinitions.user_id == user.sub)).values(updated_at=func.now(), **cols)
        )
        await s.commit()
        row = (await s.execute(select(AgentDefinitions).where(AgentDefinitions.id == au))).scalar_one_or_none()
    return agent_definition(row) if row else None


@router.delete("/agent-factory/{agent_id}")
async def delete_agent(agent_id: str, user: UserContext = Depends(get_current_user)):
    au = _uuid(agent_id)
    async with SessionLocal() as s:
        await s.execute(sa_delete(AgentDefinitions).where(and_(AgentDefinitions.id == au, AgentDefinitions.user_id == user.sub)))
        await s.commit()
    return {"ok": True}
