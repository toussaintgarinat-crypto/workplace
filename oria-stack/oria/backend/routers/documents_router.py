"""
Gestion des documents utilisateur.
Upload → conversion Markitdown (Python API) → indexation MemPalace (via mempalace_client).
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import os, uuid

from config import config as oria_config
from models.document import Document
from routers.auth import get_current_user
from services.documents_service import DocumentsService, get_documents_service
from jobs_worker import enqueue_docparse
import mempalace_client as mp

router = APIRouter()

UPLOAD_DIR = oria_config.DOCUMENTS_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

SUPPORTED_PLAIN = {"text/plain", "text/markdown", "text/csv"}


# ── Conversion Markitdown ────────────────────────────────────────

def convert_to_markdown(file_path: str, mime_type: str) -> str:
    """
    Convertit n'importe quel fichier en Markdown via l'API Python markitdown.
    Fallback lecture texte brut pour les formats textuels simples.
    """
    try:
        from markitdown import MarkItDown  # noqa: PLC0415
        result = MarkItDown().convert(file_path)
        if result and result.text_content and result.text_content.strip():
            return result.text_content.strip()
    except ImportError:
        pass
    except Exception:
        pass

    if mime_type in SUPPORTED_PLAIN:
        try:
            with open(file_path, "r", errors="replace") as f:
                return f.read()
        except Exception:
            pass

    return f"[Conversion non disponible pour {mime_type} — installe markitdown : pip install markitdown]"


# ── Helpers ──────────────────────────────────────────────────────

def _doc_dict(d: Document) -> dict:
    return {
        "id": d.id, "nom": d.nom, "nom_original": d.nom_original,
        "type_mime": d.type_mime, "taille": d.taille,
        "world_id": d.world_id,
        "indexe_memory": d.indexe_memory,
        "index_status": getattr(d, "index_status", None) or "idle",
        "has_content": bool(d.content_md and d.content_md.strip()),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ── Routes ───────────────────────────────────────────────────────

@router.get("/")
def list_documents(
    world_id: Optional[str] = None,
    svc: DocumentsService = Depends(get_documents_service),
    user=Depends(get_current_user),
):
    docs = svc.list_user_documents(owner_id=user["id"], world_id=world_id)
    return [_doc_dict(d) for d in docs]


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    world_id: Optional[str] = Form(None),
    index_memory: bool = Form(True),   # True par défaut
    session_id: Optional[str] = Form(None),
    session_titre: Optional[str] = Form(None),
    svc: DocumentsService = Depends(get_documents_service),
    user=Depends(get_current_user),
):
    """
    Upload un fichier → conversion Markitdown → indexation MemPalace en arrière-plan.
    Paramètres optionnels session_id / session_titre pour lier le document à une session IPCRA.
    """
    user_dir = os.path.join(UPLOAD_DIR, user["id"])
    os.makedirs(user_dir, exist_ok=True)

    ext = os.path.splitext(file.filename or "")[1]
    safe_name = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(user_dir, safe_name)

    raw = await file.read()
    with open(file_path, "wb") as f:
        f.write(raw)

    mime = file.content_type or "application/octet-stream"
    md_content = convert_to_markdown(file_path, mime)

    doc = Document(
        owner_id=user["id"],
        world_id=world_id,
        nom=file.filename or safe_name,
        nom_original=file.filename or safe_name,
        type_mime=mime,
        taille=len(raw),
        file_path=file_path,
        content_md=md_content,
    )
    doc = svc.create_document(doc)

    # Indexation MemPalace via job durable (S125) — survit au restart, retry + DLQ.
    if index_memory and md_content.strip():
        await enqueue_docparse(doc.id, session_id, session_titre)

    return _doc_dict(doc)


@router.get("/{doc_id}/content")
def get_document_content(
    doc_id: str,
    svc: DocumentsService = Depends(get_documents_service),
    user=Depends(get_current_user),
):
    doc = svc.get_user_document(doc_id, user["id"])
    if not doc:
        raise HTTPException(404)
    return {"id": doc.id, "nom": doc.nom, "content_md": doc.content_md}


@router.post("/{doc_id}/index-memory")
async def index_document_memory(
    doc_id: str,
    session_id: Optional[str] = None,
    session_titre: Optional[str] = None,
    svc: DocumentsService = Depends(get_documents_service),
    user=Depends(get_current_user),
):
    """Indexe (ou réindexe) un document existant dans MemPalace (job durable S125)."""
    doc = svc.get_user_document(doc_id, user["id"])
    if not doc:
        raise HTTPException(404)
    if not doc.content_md or not doc.content_md.strip():
        raise HTTPException(400, "Document sans contenu Markdown")

    await enqueue_docparse(doc_id, session_id, session_titre)
    return {"ok": True, "doc_id": doc_id}


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    svc: DocumentsService = Depends(get_documents_service),
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


# ── Recherche sémantique dans MemPalace ──────────────────────────

class SearchBody(BaseModel):
    query: str
    limit: int = 5


@router.post("/memory/search")
def search_memory(body: SearchBody, user=Depends(get_current_user)):
    """Recherche sémantique directe dans MemPalace (room=documents)."""
    hits = mp.prefetch(body.query, n=body.limit, wing="wing_user")
    # Filtre sur la room documents pour cette route
    doc_hits = [h for h in hits if h.get("room") == "documents"]
    return {"query": body.query, "results": doc_hits or hits}
