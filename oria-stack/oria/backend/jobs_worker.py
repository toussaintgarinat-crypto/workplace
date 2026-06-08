"""Worker durable Oria — indexation MemPalace des documents (S125).

Avant S125, l'upload déclenchait l'indexation via ``BackgroundTasks`` FastAPI :
in-process, perdue au restart, sans retry. On passe par un stream Redis durable
(``oria:jobs:docparse``) : le job survit au redémarrage du backend (repris via
``XAUTOCLAIM``) et est rejoué en cas d'échec transitoire, puis dirigé en DLQ.

Le statut du document (``index_status``) est persisté en DB :
``pending`` (empilé) → ``processing`` → ``done`` / ``error``.

Sans Redis (``REDIS_URL`` vide), ``JobWorker.enqueue`` retombe sur un
``asyncio.Task`` local — comportement équivalent à l'ancien ``BackgroundTasks``.
"""

from __future__ import annotations

import asyncio
import logging
import os

from redis_client import NAMESPACE

logger = logging.getLogger(__name__)

_JOB_STREAM = "docparse"
_JOB_GROUP = "workers"

_worker = None


def _set_status(doc_id: str, status: str, indexed: bool | None = None) -> None:
    from database import SessionLocal
    from models.document import Document
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(id=doc_id).first()
        if not doc:
            return
        doc.index_status = status
        if indexed is not None:
            doc.indexe_memory = indexed
        db.commit()
    finally:
        db.close()


def _load_doc(doc_id: str):
    from database import SessionLocal
    from models.document import Document
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(id=doc_id).first()
        if not doc:
            return None
        return {
            "content_md": doc.content_md or "",
            "nom": doc.nom,
            "owner_id": doc.owner_id,
        }
    finally:
        db.close()


async def _docparse_handler(payload: dict):
    """Indexe un document dans MemPalace. Idempotent et rejouable."""
    doc_id = payload.get("doc_id")
    if not doc_id:
        return

    info = await asyncio.to_thread(_load_doc, doc_id)
    if not info:
        logger.warning("docparse job %s : document introuvable — ignoré", doc_id)
        return
    content = info["content_md"]
    if not content.strip():
        await asyncio.to_thread(_set_status, doc_id, "done", False)
        return

    await asyncio.to_thread(_set_status, doc_id, "processing")

    import mempalace_client as mp
    await asyncio.to_thread(
        mp.sync_document, content, doc_id, info["nom"], info["owner_id"],
        payload.get("session_id"), payload.get("session_titre"),
    )

    await asyncio.to_thread(_set_status, doc_id, "done", True)


async def _on_docparse_dlq(payload: dict, error: str):
    doc_id = payload.get("doc_id")
    if doc_id:
        try:
            await asyncio.to_thread(_set_status, doc_id, "error")
        except Exception as e:  # noqa: BLE001
            logger.warning("docparse DLQ hook error: %s", e)


def _get_worker():
    global _worker
    if _worker is None:
        from agent_personnel_shared.jobs import JobWorker
        cap = max(1, int(os.getenv("ORIA_DOCPARSE_WORKERS", "2")))
        _worker = JobWorker(
            namespace=NAMESPACE,
            stream=_JOB_STREAM,
            group=_JOB_GROUP,
            handler=_docparse_handler,
            concurrency=cap,
            global_concurrency=cap,
            max_retries=int(os.getenv("ORIA_DOCPARSE_MAX_RETRIES", "3")),
            on_dlq=_on_docparse_dlq,
        )
    return _worker


async def enqueue_docparse(doc_id: str, session_id=None, session_titre=None):
    """Empile (ou exécute en local si pas de Redis) l'indexation d'un document."""
    _set_status(doc_id, "pending")
    await _get_worker().enqueue({
        "doc_id": doc_id,
        "session_id": session_id,
        "session_titre": session_titre,
    })


async def start_worker():
    await _get_worker().start()


async def stop_worker():
    if _worker is not None:
        await _worker.stop()
