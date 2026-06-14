"""
Agents IA — définitions, CRUD, et pont vers Forge (streaming ReAct).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import os, httpx, json

from models.agent import AgentDefinition
from routers.auth import get_current_user
from services.agents_service import AgentsService, get_agents_service

router = APIRouter()

# ── Pont direct Gateway Workplace (OpenAI-compatible) ────────────
# Le port Python de Forge n'expose plus /api/agents/react/stream (il a /api/agents/run,
# qui ignore le systemOverride). Pour qu'un agent réponde EN PERSONNAGE, on court-circuite
# Forge quand forge_provider == "gateway" : appel direct de la Gateway LiteLLM avec le
# system_prompt de l'agent. forge_url porte la base Gateway (ex http://host.docker.internal:4001).
GATEWAY_KEY = os.getenv("GATEWAY_KEY") or os.getenv("LLM_API_KEY") or ""

# Cascade GRATUITE (priorité coût Workplace) : on essaie d'abord le modèle de l'agent,
# puis des modèles gratuits servis par la Gateway si l'un est rate-limité (429) ou KO.
# Le payant n'arrive qu'en tout dernier recours.
FREE_CASCADE = [
    "free/google/gemma-4-31b-it",
    "free/google/gemma-4-26b-a4b-it",
    "free/qwen/qwen3-next-80b-a3b-instruct",
    "free/moonshotai/kimi-k2.6",
    "openai/gpt-4o-mini",  # repli payant ultime
]


def _is_gateway(agent) -> bool:
    return (getattr(agent, "forge_provider", "") or "").lower() == "gateway"


async def _gateway_answer(base: str, model: str, system: str, message: str) -> str:
    candidats = []
    for m in [model] + FREE_CASCADE:
        if m and m not in candidats:
            candidats.append(m)
    url = f"{base.rstrip('/')}/v1/chat/completions"
    dernier = "aucune tentative"
    async with httpx.AsyncClient(timeout=90.0) as client:
        for m in candidats:
            try:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
                    json={
                        "model": m,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": message},
                        ],
                    },
                )
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                dernier = f"{m}: HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                dernier = f"{m}: {str(e)[:80]}"
    raise RuntimeError(f"Cascade Gateway épuisée ({dernier})")


async def _gateway_stream(base: str, model: str, system: str, message: str):
    try:
        content = await _gateway_answer(base, model, system, message)
        yield f"data: {json.dumps({'type': 'answer', 'content': content})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)[:200]})}\n\n"


# ── Helpers ──────────────────────────────────────────────────────


def _agent_dict(a: AgentDefinition) -> dict:
    return {
        "id": a.id, "world_id": a.world_id, "nom": a.nom,
        "avatar_emoji": a.avatar_emoji, "description": a.description,
        "system_prompt": a.system_prompt,
        "map_x": a.map_x, "map_y": a.map_y,
        "forge_url": a.forge_url, "forge_provider": a.forge_provider,
        "forge_model": a.forge_model,
        "can_read_docs": a.can_read_docs, "use_memory": a.use_memory,
        "use_ipcra": a.use_ipcra, "is_active": a.is_active,
        "wake_word": a.wake_word or "",
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


# ── CRUD ─────────────────────────────────────────────────────────

class CreateAgent(BaseModel):
    world_id:       str
    nom:            str
    avatar_emoji:   str = "🤖"
    description:    str = ""
    system_prompt:  str = "Tu es un assistant IA utile et bienveillant."
    map_x:          float = 5.0
    map_y:          float = 5.0
    forge_url:      str = "http://localhost:3001"
    forge_provider: str = "ollama"
    forge_model:    str = ""
    can_read_docs:  bool = True
    use_memory:     bool = True
    use_ipcra:      bool = False
    wake_word:      str = ""


class UpdateAgent(BaseModel):
    nom:            Optional[str] = None
    avatar_emoji:   Optional[str] = None
    description:    Optional[str] = None
    system_prompt:  Optional[str] = None
    map_x:          Optional[float] = None
    map_y:          Optional[float] = None
    forge_url:      Optional[str] = None
    forge_provider: Optional[str] = None
    forge_model:    Optional[str] = None
    can_read_docs:  Optional[bool] = None
    use_memory:     Optional[bool] = None
    use_ipcra:      Optional[bool] = None
    is_active:      Optional[bool] = None
    wake_word:      Optional[str] = None


@router.get("/world/{world_id}")
def list_agents(
    world_id: str,
    svc: AgentsService = Depends(get_agents_service),
    user=Depends(get_current_user),
):
    svc.check_world_access(world_id, user["id"])
    agents = svc.list_world_agents(world_id)
    return [_agent_dict(a) for a in agents]


@router.post("/")
def create_agent(
    body: CreateAgent,
    svc: AgentsService = Depends(get_agents_service),
    user=Depends(get_current_user),
):
    svc.check_world_access(body.world_id, user["id"], require_owner=True)
    agent = svc.create_agent(
        world_id=body.world_id, owner_id=user["id"],
        nom=body.nom, avatar_emoji=body.avatar_emoji,
        description=body.description, system_prompt=body.system_prompt,
        map_x=body.map_x, map_y=body.map_y,
        forge_url=body.forge_url, forge_provider=body.forge_provider,
        forge_model=body.forge_model,
        can_read_docs=body.can_read_docs, use_memory=body.use_memory,
        use_ipcra=body.use_ipcra, wake_word=body.wake_word,
    )
    return _agent_dict(agent)


@router.patch("/{agent_id}")
def update_agent(
    agent_id: str,
    body: UpdateAgent,
    svc: AgentsService = Depends(get_agents_service),
    user=Depends(get_current_user),
):
    agent = svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404)
    svc.check_world_access(agent.world_id, user["id"], require_owner=True)
    agent = svc.update_agent(agent, body.model_dump(exclude_none=True))
    return _agent_dict(agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: str,
    svc: AgentsService = Depends(get_agents_service),
    user=Depends(get_current_user),
):
    agent = svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404)
    svc.check_world_access(agent.world_id, user["id"], require_owner=True)
    svc.delete_agent(agent)


# ── Chat — pont vers Forge (streaming) ───────────────────────────

class ChatBody(BaseModel):
    message:    str
    session_id: Optional[str] = None


@router.post("/{agent_id}/chat")
async def chat_with_agent(
    agent_id: str,
    body: ChatBody,
    svc: AgentsService = Depends(get_agents_service),
    user=Depends(get_current_user),
):
    agent = svc.get_active_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent introuvable ou inactif")
    svc.check_world_access(agent.world_id, user["id"])

    # Construire le contexte docs si l'agent peut les lire
    docs_context = ""
    if agent.can_read_docs:
        docs = svc.list_user_documents(user["id"], limit=5)
        if docs:
            docs_context = "\n\n## Documents disponibles de l'utilisateur\n" + "\n\n---\n".join(
                f"### {d.nom}\n{d.content_md[:2000]}" for d in docs if d.content_md
            )

    full_system = agent.system_prompt + docs_context

    forge_url = agent.forge_url.rstrip("/")
    session_id = body.session_id or f"oria-{user['id']}-{agent_id}"

    # Pont Gateway : réponse en personnage via la Gateway LLM, sans passer par Forge.
    if _is_gateway(agent):
        return StreamingResponse(
            _gateway_stream(forge_url, agent.forge_model, full_system, body.message),
            media_type="text/event-stream",
        )

    payload = {
        "message": body.message,
        "sessionId": session_id,
        "provider": agent.forge_provider or None,
        "model": agent.forge_model or None,
        "systemOverride": full_system,
    }

    async def stream_forge():
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", f"{forge_url}/api/agents/react/stream", json=payload) as r:
                    if r.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Forge error {r.status_code}'})}\n\n"
                        return
                    async for line in r.aiter_lines():
                        if line:
                            yield f"{line}\n\n"
        except httpx.ConnectError:
            # Forge inaccessible — fallback direct LLM
            yield f"data: {json.dumps({'type': 'answer', 'content': '[Forge non disponible — vérifie que le service est démarré sur ' + forge_url + ']'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)[:200]})}\n\n"

    return StreamingResponse(stream_forge(), media_type="text/event-stream")


# ── Chat simple (non-streaming, pour tests) ──────────────────────

@router.post("/{agent_id}/chat/simple")
async def chat_simple(
    agent_id: str,
    body: ChatBody,
    svc: AgentsService = Depends(get_agents_service),
    user=Depends(get_current_user),
):
    agent = svc.get_active_agent(agent_id)
    if not agent:
        raise HTTPException(404)
    svc.check_world_access(agent.world_id, user["id"])

    docs_context = ""
    if agent.can_read_docs:
        docs = svc.list_user_documents(user["id"], limit=3)
        if docs:
            docs_context = "\n\nDocs : " + " | ".join(d.nom for d in docs if d.content_md)

    full_system = agent.system_prompt + docs_context
    forge_url = agent.forge_url.rstrip("/")
    session_id = body.session_id or f"oria-{user['id']}-{agent_id}"

    # Pont Gateway : réponse en personnage via la Gateway LLM, sans passer par Forge.
    if _is_gateway(agent):
        try:
            content = await _gateway_answer(forge_url, agent.forge_model, full_system, body.message)
            return {"answer": content, "steps": []}
        except Exception as e:
            return {"answer": f"[Erreur Gateway : {str(e)[:150]}]", "steps": []}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{forge_url}/api/agents/react",
                json={
                    "message": body.message,
                    "sessionId": session_id,
                    "provider": agent.forge_provider or None,
                    "model": agent.forge_model or None,
                    "systemOverride": full_system,
                },
            )
            if r.status_code == 200:
                data = r.json()
                return {"answer": data.get("answer", ""), "steps": data.get("steps", [])}
            return {"answer": f"[Erreur Forge {r.status_code}]", "steps": []}
    except httpx.ConnectError:
        return {"answer": f"[Forge non disponible sur {forge_url}]", "steps": []}
    except Exception as e:
        return {"answer": f"[Erreur : {str(e)[:150]}]", "steps": []}
