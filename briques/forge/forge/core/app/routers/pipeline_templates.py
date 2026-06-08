"""Router pipeline-templates. Portage de routes/pipeline-templates.ts (S133).

Monté /api, protégé. Templates de pipelines DAG : 3 templates système hardcodés
(cf. canvas React Flow S60) + templates utilisateur en DB, import en masse vers
``task_dag_items`` (cf. task-dag S132), et assistant LLM streaming (data-stream).

Les colonnes nodes/edges sont du TEXT JSON ; les templates système embarquent
leur JSON compact (``separators`` sans espace) pour coller à JSON.stringify du Bun.
"""

from __future__ import annotations

import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.config import settings
from app.db import SessionLocal
from app.llm import gateway_model
from app.models import PipelineTemplates, TaskDagItems
from app.serde import pipeline_template

router = APIRouter()


def _j(obj) -> str:
    """JSON compact (parité JSON.stringify du Bun : pas d'espaces, accents littéraux)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


# ── Templates système hardcodés ─────────────────────────────────────────
PIPELINE_TEMPLATES = [
    {
        "id": "sys-brief-analyse-rapport",
        "userId": None,
        "nom": "Brief → Analyse → Rapport",
        "description": "Pipeline linéaire classique : cadrage de la demande, analyse approfondie, livrable final.",
        "icon": "📋",
        "categorie": "Productivité",
        "isPublic": True,
        "nodes": _j([
            {"id": "n1", "type": "promptNode", "position": {"x": 50, "y": 150}, "data": {"label": "Brief", "criticite": "haute", "nodeType": "prompt", "promptText": "Analyse la demande et rédige un brief structuré : contexte, objectifs, contraintes, livrables attendus.", "agentOwner": ""}},
            {"id": "n2", "type": "promptNode", "position": {"x": 320, "y": 150}, "data": {"label": "Analyse", "criticite": "haute", "nodeType": "prompt", "promptText": "Réalise une analyse approfondie sur la base du brief. Identifie les enjeux, risques et opportunités.", "agentOwner": ""}},
            {"id": "n3", "type": "promptNode", "position": {"x": 590, "y": 150}, "data": {"label": "Rapport", "criticite": "normale", "nodeType": "prompt", "promptText": "Synthétise l'analyse en un rapport exécutif clair avec conclusions et recommandations actionnables.", "agentOwner": ""}},
        ]),
        "edges": _j([
            {"id": "e1-2", "source": "n1", "target": "n2", "animated": True},
            {"id": "e2-3", "source": "n2", "target": "n3", "animated": True},
        ]),
    },
    {
        "id": "sys-onboarding-client",
        "userId": None,
        "nom": "Onboarding Client",
        "description": "Accueil, configuration parallèle et formation, puis suivi post-onboarding.",
        "icon": "🤝",
        "categorie": "Commercial",
        "isPublic": True,
        "nodes": _j([
            {"id": "n1", "type": "promptNode", "position": {"x": 50, "y": 200}, "data": {"label": "Accueil", "criticite": "haute", "nodeType": "prompt", "promptText": "Prépare le message d'accueil personnalisé et le kit de bienvenue pour le nouveau client.", "agentOwner": ""}},
            {"id": "n2", "type": "agentNode", "position": {"x": 320, "y": 80}, "data": {"label": "Configuration", "criticite": "haute", "nodeType": "agent", "promptText": "", "agentOwner": "Agent Tech Lead"}},
            {"id": "n3", "type": "agentNode", "position": {"x": 320, "y": 320}, "data": {"label": "Formation", "criticite": "normale", "nodeType": "agent", "promptText": "", "agentOwner": "Agent RH"}},
            {"id": "n4", "type": "promptNode", "position": {"x": 590, "y": 200}, "data": {"label": "Suivi J+30", "criticite": "normale", "nodeType": "prompt", "promptText": "Rédige le compte-rendu de suivi J+30 : satisfaction client, points bloquants, actions correctives.", "agentOwner": ""}},
        ]),
        "edges": _j([
            {"id": "e1-2", "source": "n1", "target": "n2", "animated": True},
            {"id": "e1-3", "source": "n1", "target": "n3", "animated": True},
            {"id": "e2-4", "source": "n2", "target": "n4", "animated": True},
            {"id": "e3-4", "source": "n3", "target": "n4", "animated": True},
        ]),
    },
    {
        "id": "sys-code-review",
        "userId": None,
        "nom": "Code Review Pipeline",
        "description": "Lecture du code, analyse qualité et sécurité en parallèle, rapport de review final.",
        "icon": "🔍",
        "categorie": "Technique",
        "isPublic": True,
        "nodes": _j([
            {"id": "n1", "type": "promptNode", "position": {"x": 50, "y": 200}, "data": {"label": "Lecture code", "criticite": "normale", "nodeType": "prompt", "promptText": "Lis et comprends le code soumis. Résume son fonctionnement, ses responsabilités et son périmètre.", "agentOwner": ""}},
            {"id": "n2", "type": "agentNode", "position": {"x": 320, "y": 80}, "data": {"label": "Qualité code", "criticite": "haute", "nodeType": "agent", "promptText": "", "agentOwner": "Agent Tech Lead"}},
            {"id": "n3", "type": "agentNode", "position": {"x": 320, "y": 320}, "data": {"label": "Analyse sécurité", "criticite": "haute", "nodeType": "agent", "promptText": "", "agentOwner": "Agent Juridique"}},
            {"id": "n4", "type": "promptNode", "position": {"x": 590, "y": 200}, "data": {"label": "Rapport review", "criticite": "haute", "nodeType": "prompt", "promptText": "Consolide les analyses qualité et sécurité en un rapport de review structuré avec priorités et corrections suggérées.", "agentOwner": ""}},
        ]),
        "edges": _j([
            {"id": "e1-2", "source": "n1", "target": "n2", "animated": True},
            {"id": "e1-3", "source": "n1", "target": "n3", "animated": True},
            {"id": "e2-4", "source": "n2", "target": "n4", "animated": True},
            {"id": "e3-4", "source": "n3", "target": "n4", "animated": True},
        ]),
    },
]

ASSISTANT_SYSTEM = """Tu es un expert en orchestration de workflows et de pipelines d'agents IA.
Tu aides l'utilisateur à concevoir, discuter et générer des pipelines DAG (graphes acycliques dirigés).

Chaque pipeline est composé de :
- Nœuds de type "prompt" : exécutent un prompt LLM libre
- Nœuds de type "agent" : délèguent à un agent Forge spécialisé
- Arêtes : transmettent l'output d'un nœud vers le suivant

Quand l'utilisateur te demande de GÉNÉRER un pipeline, produis un JSON valide dans ce format exact :
```json
{
  "nodes": [
    { "id": "n1", "type": "promptNode", "position": { "x": 50, "y": 150 }, "data": { "label": "Nom du nœud", "criticite": "normale", "nodeType": "prompt", "promptText": "Instructions pour ce nœud", "agentOwner": "" } }
  ],
  "edges": [
    { "id": "e1-2", "source": "n1", "target": "n2", "animated": true }
  ]
}
```

Types de criticité disponibles : faible, normale, haute, critique
Types de nœuds : promptNode (prompt libre) ou agentNode (agent Forge, remplis agentOwner avec le nom de l'agent)

Si l'utilisateur veut DISCUTER ou avoir des conseils, réponds naturellement sans JSON.
Réponds toujours dans la langue de l'utilisateur."""


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/pipeline-templates", dependencies=[Depends(get_current_user)])
async def list_templates(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(PipelineTemplates)
            .where(or_(PipelineTemplates.user_id == user.sub, PipelineTemplates.user_id.is_(None)))
            .order_by(desc(PipelineTemplates.created_at))
        )).scalars().all()
    return [*PIPELINE_TEMPLATES, *[pipeline_template(x) for x in rows]]


class CreateTemplate(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str | None = None
    icon: str | None = None
    categorie: str | None = None
    nodes: str
    edges: str


@router.post("/pipeline-templates", dependencies=[Depends(get_current_user)])
async def create_template(body: CreateTemplate, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        tpl = PipelineTemplates(
            user_id=user.sub, nom=body.nom, description=body.description or "",
            icon=body.icon or "🔄", categorie=body.categorie or "",
            nodes=body.nodes, edges=body.edges, is_public=False,
        )
        s.add(tpl)
        await s.commit()
        await s.refresh(tpl)
    return JSONResponse(status_code=201, content=pipeline_template(tpl))


@router.delete("/pipeline-templates/{tid}", dependencies=[Depends(get_current_user)])
async def delete_template(tid: str, user: UserContext = Depends(get_current_user)):
    tuid = _uuid(tid)
    async with SessionLocal() as s:
        if tuid:
            await s.execute(
                sa_delete(PipelineTemplates).where(
                    and_(PipelineTemplates.id == tuid, PipelineTemplates.user_id == user.sub)
                )
            )
            await s.commit()
    return {"ok": True}


class ImportBody(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    clearExisting: bool | None = None


@router.post("/poles/{pole_id}/dag/import", dependencies=[Depends(get_current_user)])
async def import_dag(pole_id: str, body: ImportBody, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        if body.clearExisting:
            await s.execute(
                sa_delete(TaskDagItems).where(and_(TaskDagItems.pole_id == puid, TaskDagItems.user_id == user.sub))
            )

        id_map: dict[str, str] = {}
        created = 0
        for node in body.nodes:
            data = node.get("data") or {}
            position = node.get("position") or {}
            item = TaskDagItems(
                pole_id=puid, user_id=user.sub,
                nom=data.get("label") or "Tâche",
                description=data.get("description") or "",
                agent_owner=data.get("agentOwner") or "",
                dependances="[]",
                criticite=data.get("criticite") or "normale",
                node_type=data.get("nodeType") or "prompt",
                pos_x=(position.get("x") if position.get("x") is not None else 0),
                pos_y=(position.get("y") if position.get("y") is not None else 0),
                prompt_text=data.get("promptText") or "",
            )
            s.add(item)
            await s.flush()
            id_map[node.get("id")] = str(item.id)
            created += 1
        await s.commit()

        deps_map: dict[str, list[str]] = {}
        for edge in body.edges:
            target_id = id_map.get(edge.get("target"))
            source_id = id_map.get(edge.get("source"))
            if target_id and source_id:
                deps_map.setdefault(target_id, []).append(source_id)

        for db_id, deps in deps_map.items():
            await s.execute(
                update(TaskDagItems).where(TaskDagItems.id == _uuid(db_id))
                .values(dependances=json.dumps(deps), updated_at=datetime.datetime.utcnow())
            )
        await s.commit()
    return {"ok": True, "created": created}


class AssistantChat(BaseModel):
    messages: list[dict]
    provider: str | None = None
    model: str | None = None


@router.post("/pipeline-assistant/chat", dependencies=[Depends(get_current_user)])
async def assistant_chat(body: AssistantChat):
    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)
    msgs = [{"role": "system", "content": ASSISTANT_SYSTEM}, *body.messages]

    async def gen():
        try:
            stream = await client.chat.completions.create(
                model=gateway_model(body.provider, body.model),
                messages=msgs,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield f"0:{json.dumps(delta)}\n"
        finally:
            yield f'd:{json.dumps({"finishReason": "stop"})}\n'

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
