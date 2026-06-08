"""
Jardin Secret — assistant personnel avec mémoire MemPalace par utilisateur.

Chaque utilisateur a :
  - Un agent personnel configurable (provider/model/system_prompt)
  - Un palace MemPalace privé : palaces/{user_id}/
  - Ses documents convertis en Markdown via markitdown (original conservé)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import httpx, json, os, uuid

from models.agent import AgentDefinition
from models.document import Document
from routers.auth import get_current_user
from services.jardin_service import JardinService, get_jardin_service
import mempalace_client as mp

router = APIRouter()

UPLOAD_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "uploads", "jardin")
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _agent_dict(a: AgentDefinition) -> dict:
    return {
        "id": a.id, "nom": a.nom, "avatar_emoji": a.avatar_emoji,
        "description": a.description, "system_prompt": a.system_prompt,
        "forge_url": a.forge_url, "forge_provider": a.forge_provider,
        "forge_model": a.forge_model, "wake_word": a.wake_word or "",
        "is_active": a.is_active,
    }


def _convert_to_md(file_path: str) -> str:
    try:
        from markitdown import MarkItDown
        result = MarkItDown().convert(file_path)
        return result.text_content or ""
    except Exception:
        return ""


def _index_doc_background(doc_id: str, nom: str, content_md: str, user_id: str):
    mp.sync_document(
        content=content_md,
        doc_id=doc_id,
        doc_name=nom,
        owner_id=user_id,
        user_id=user_id,
    )


# ── Agent personnel ───────────────────────────────────────────────────────────

@router.get("/agent")
def get_agent(
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    agent = svc.get_personal_agent(user["id"])
    if not agent:
        raise HTTPException(404, "Agent personnel introuvable")
    return _agent_dict(agent)


class UpdateJardinAgent(BaseModel):
    nom:           Optional[str] = None
    avatar_emoji:  Optional[str] = None
    description:   Optional[str] = None
    system_prompt: Optional[str] = None
    forge_url:     Optional[str] = None
    forge_provider: Optional[str] = None
    forge_model:   Optional[str] = None
    wake_word:     Optional[str] = None
    is_active:     Optional[bool] = None


@router.patch("/agent")
def update_agent(
    body: UpdateJardinAgent,
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    agent = svc.get_personal_agent(user["id"])
    if not agent:
        raise HTTPException(404)
    agent = svc.update_personal_agent(agent, body.model_dump(exclude_none=True))
    return _agent_dict(agent)


# ── Chat streaming ────────────────────────────────────────────────────────────

class JardinChatBody(BaseModel):
    message:        str
    session_id:     Optional[str] = None
    save_to_memory: bool = True


@router.post("/chat")
async def jardin_chat(
    body: JardinChatBody,
    background_tasks: BackgroundTasks,
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    agent = svc.get_personal_agent(user["id"])
    if not agent or not agent.is_active:
        raise HTTPException(404, "Agent personnel non configuré ou inactif")

    # Prefetch du palace personnel
    memories = mp.prefetch(body.message, n=6, user_id=user["id"])
    memory_block = mp.format_context_block(memories)
    full_system = agent.system_prompt + memory_block

    forge_url = agent.forge_url.rstrip("/")
    session_id = body.session_id or f"jardin-{user['id']}"

    payload = {
        "message":        body.message,
        "sessionId":      session_id,
        "provider":       agent.forge_provider or None,
        "model":          agent.forge_model or None,
        "systemOverride": full_system,
    }

    # Sauvegarde du message utilisateur en arrière-plan
    if body.save_to_memory:
        background_tasks.add_task(
            mp.sync_conversation_turn,
            user_message=body.message,
            assistant_response="",
            user_id=user["id"],
        )

    async def stream_forge():
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream("POST", f"{forge_url}/api/agents/react/stream", json=payload) as r:
                    if r.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Forge {r.status_code}'})}\n\n"
                        return
                    async for line in r.aiter_lines():
                        if line:
                            yield f"{line}\n\n"
        except httpx.ConnectError:
            yield f"data: {json.dumps({'type': 'answer', 'content': '[Forge indisponible — vérifie que le service tourne sur ' + forge_url + ']'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)[:200]})}\n\n"

    return StreamingResponse(stream_forge(), media_type="text/event-stream", background=background_tasks)


# ── Sauvegarde explicite réponse assistant ────────────────────────────────────

class MemorySaveBody(BaseModel):
    user_message:       str
    assistant_response: str


@router.post("/memory")
async def save_memory(
    body: MemorySaveBody,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
):
    background_tasks.add_task(
        mp.sync_conversation_turn,
        user_message=body.user_message,
        assistant_response=body.assistant_response,
        user_id=user["id"],
    )
    return {"ok": True}


# ── Upload de fichier ─────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    user_dir = os.path.join(UPLOAD_BASE, user["id"])
    os.makedirs(user_dir, exist_ok=True)

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "")[1]
    saved_path = os.path.join(user_dir, f"{file_id}{ext}")

    raw = await file.read()
    with open(saved_path, "wb") as f:
        f.write(raw)

    content_md = _convert_to_md(saved_path)

    doc = Document(
        id=file_id,
        owner_id=user["id"],
        nom=file.filename or file_id,
        nom_original=file.filename or file_id,
        type_mime=file.content_type or "application/octet-stream",
        taille=len(raw),
        file_path=saved_path,
        content_md=content_md,
        indexe_memory=False,
    )
    svc.add_document(doc)

    if content_md.strip():
        background_tasks.add_task(
            _index_doc_background,
            doc_id=file_id,
            nom=file.filename or file_id,
            content_md=content_md,
            user_id=user["id"],
        )

    preview_md = content_md[:500] + "…" if len(content_md) > 500 else content_md
    return {
        "id":         doc.id,
        "nom":        doc.nom,
        "type_mime":  doc.type_mime,
        "taille":     doc.taille,
        "content_md": preview_md,
        "created_at": doc.created_at.isoformat(),
    }


# ── Liste des fichiers ────────────────────────────────────────────────────────

@router.get("/files")
def list_files(
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    docs = svc.list_user_documents(user["id"])
    return [
        {
            "id":         d.id,
            "nom":        d.nom,
            "type_mime":  d.type_mime,
            "taille":     d.taille,
            "has_md":     bool(d.content_md),
            "created_at": d.created_at.isoformat(),
            "url":        f"/uploads/jardin/{user['id']}/{os.path.basename(d.file_path)}",
        }
        for d in docs
    ]


@router.get("/files/{doc_id}/markdown")
def get_file_markdown(
    doc_id: str,
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    doc = svc.get_user_document(doc_id, user["id"])
    if not doc:
        raise HTTPException(404)
    return {"id": doc.id, "nom": doc.nom, "content_md": doc.content_md}


@router.delete("/files/{doc_id}", status_code=204)
def delete_file(
    doc_id: str,
    svc: JardinService = Depends(get_jardin_service),
    user=Depends(get_current_user),
):
    doc = svc.get_user_document(doc_id, user["id"])
    if not doc:
        raise HTTPException(404)
    try:
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except Exception:
        pass
    svc.delete_document(doc)


# ── Recherche sémantique ──────────────────────────────────────────────────────

@router.get("/search")
def search_palace(
    q: str = Query(..., min_length=1),
    n: int = Query(8, le=20),
    user=Depends(get_current_user),
):
    hits = mp.prefetch(q, n=n, user_id=user["id"])
    return {"query": q, "results": hits}
