"""Router documents. Portage de routes/documents.ts (S135).

Monté /api, protégé. Upload d'un document (texte déjà extrait côté client) →
analyse LLM (résumé structuré) + ingestion Qdrant best-effort (fire-and-forget,
via le module mémoire S129). Lecture/suppression par utilisateur.
"""

from __future__ import annotations

import asyncio
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import and_, desc, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.llm import generate_text
from app.memory import delete_by_source, ingest
from app.models import Documents
from app.serde import document_full, document_list

router = APIRouter()


def _uuid(v):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _ingest_bg(text: str, source_id: str, user_id: str, pole_id: str | None, title: str) -> None:
    async def _run():
        try:
            await ingest(text=text, source_id=source_id, source_type="document",
                         user_id=user_id, pole_id=pole_id or None, title=title)
        except Exception:  # noqa: BLE001
            pass
    asyncio.create_task(_run())


@router.post("/documents/upload", dependencies=[Depends(get_current_user)])
async def upload_document(body: dict, response: Response,
                          user: UserContext = Depends(get_current_user)):
    nom = body.get("nom")
    contenu = body.get("contenu")
    if not nom or not contenu:
        response.status_code = 400
        return {"error": "nom and contenu required"}
    type_ = body.get("type") or "pdf"
    pole_id = body.get("poleId")
    session_id = body.get("sessionId")

    try:
        analyse = await generate_text(
            prompt=("Analyse ce document et donne un résumé structuré (points clés, "
                    f"risques, actions recommandées) :\n\n{contenu[:8000]}"),
            max_tokens=1024,
        )
    except Exception:  # noqa: BLE001
        analyse = "Analyse non disponible"

    async with SessionLocal() as s:
        doc = Documents(
            user_id=user.sub, nom=nom, type=type_, contenu=contenu,
            analyse=analyse, taille=len(contenu),
            pole_id=_uuid(pole_id) if pole_id else None,
            session_id=_uuid(session_id) if session_id else None,
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)

    _ingest_bg(contenu, str(doc.id), user.sub, pole_id, nom)
    response.status_code = 201
    return document_full(doc)


@router.get("/documents", dependencies=[Depends(get_current_user)])
async def list_documents(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Documents).where(Documents.user_id == user.sub)
            .order_by(desc(Documents.created_at))
        )).scalars().all()
    return [document_list(r) for r in rows]


@router.get("/documents/{did}", dependencies=[Depends(get_current_user)])
async def get_document(did: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(did)
    async with SessionLocal() as s:
        row = (await s.execute(
            select(Documents).where(and_(
                Documents.id == u, Documents.user_id == user.sub,
            ))
        )).scalar_one_or_none() if u else None
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return document_full(row)


@router.delete("/documents/{did}", dependencies=[Depends(get_current_user)])
async def delete_document(did: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(did)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(Documents).where(and_(
                Documents.id == u, Documents.user_id == user.sub,
            )))
            await s.commit()
    asyncio.create_task(delete_by_source(did))
    return {"ok": True}
