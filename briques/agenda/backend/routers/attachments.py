"""Pièces jointes — /events/{event_id}/attachments."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from db import get_db
from models.orm import Event, EventAttachment
from models.schemas import AttachmentOut

router = APIRouter(tags=["attachments"])

MAX_SIZE = 50 * 1024 * 1024  # 50 MB


async def _get_event(event_id: str, db: AsyncSession) -> Event:
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return evt


@router.get("/events/{event_id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _get_event(event_id, db)
    result = await db.execute(
        select(EventAttachment).where(EventAttachment.event_id == event_id)
    )
    return result.scalars().all()


@router.post("/events/{event_id}/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    event_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _get_event(event_id, db)
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large (max 50 MB)")

    dest_dir = Path(settings.ATTACHMENTS_DIR) / event_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (file.filename or "file")
    dest.write_bytes(content)

    att = EventAttachment(
        event_id=event_id,
        filename=file.filename or "file",
        mimetype=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        storage_path=str(dest),
        uploaded_by=user["sub"],
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)
    return att


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    att = await db.get(EventAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if not os.path.exists(att.storage_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return FileResponse(att.storage_path, filename=att.filename, media_type=att.mimetype)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    att = await db.get(EventAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    try:
        os.remove(att.storage_path)
    except FileNotFoundError:
        pass
    await db.delete(att)
    await db.commit()
