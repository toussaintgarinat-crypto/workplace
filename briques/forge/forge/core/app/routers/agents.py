"""Router agents. Portage de agents.ts (S128). Monté /api/agents, protégé.

GET /api/agents : liste statique. POST /api/agents/run : exécute via le ReAct
executor (remplace l'orchestrateur VoltAgent — supprimé).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import UserContext, get_current_user
from app.react_executor import run_react

router = APIRouter()

_AGENTS = [
    {"id": "orchestrator", "name": "Orchestrator", "description": "Routes tasks to the right pole agent"},
    {"id": "finance", "name": "Finance & Strategy", "pole": "finance"},
    {"id": "marketing", "name": "Growth & Marketing", "pole": "marketing"},
    {"id": "sales", "name": "Sales & Customer", "pole": "sales"},
    {"id": "ops", "name": "Ops & Tech", "pole": "ops"},
    {"id": "legal", "name": "Sentinel & Legal", "pole": "legal"},
]

# Instructions de l'orchestrateur (ex-VoltAgent agents/index.ts), injectées en system.
_ORCHESTRATOR_PROMPT = (
    "You are the central orchestrator of Swarm-Sentinel.\n"
    "Analyze the user's request and delegate to the most relevant pole agent:\n"
    "- Finance & Strategy: budgets, ROI, decisions\n"
    "- Growth & Marketing: SEO, content, campaigns\n"
    "- Sales & Customer: pipeline, leads, support\n"
    "- Ops & Tech: sprints, deployments, incidents\n"
    "- Sentinel & Legal: alerts, contracts, compliance\n"
    "Maximum delegation depth: 3 levels.\n"
    "Always respond in the same language as the user."
)


@router.get("")
async def list_agents(user: UserContext = Depends(get_current_user)):
    return {"agents": _AGENTS}


class CorpsRunAgent(BaseModel):
    task: str = ""


@router.post("/run")
async def run_agent(body: CorpsRunAgent, user: UserContext = Depends(get_current_user)):
    result = await run_react(
        body.task, session_id=f"agents-run:{user.sub}", user_id=user.sub,
        personality_prompt=_ORCHESTRATOR_PROMPT, agent_name="Orchestrator",
    )
    return {"result": result.answer}
