"""Commentaires sur un événement — /events/{event_id}/comments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, EventComment
from models.schemas import CommentCreate, CommentOut, CommentUpdate

router = APIRouter(tags=["comments"])


async def _get_event(event_id: str, db: AsyncSession) -> Event:
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return evt


@router.get("/events/{event_id}/comments", response_model=list[CommentOut])
async def list_comments(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _get_event(event_id, db)
    result = await db.execute(
        select(EventComment).where(EventComment.event_id == event_id).order_by(EventComment.created_at)
    )
    return result.scalars().all()


@router.post("/events/{event_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_comment(
    event_id: str,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _get_event(event_id, db)
    c = EventComment(event_id=event_id, user_id=user["sub"], content=body.content)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: str,
    body: CommentUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    c = await db.get(EventComment, comment_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if c.user_id != user["sub"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your comment")
    c.content = body.content
    await db.commit()
    await db.refresh(c)
    return c


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    c = await db.get(EventComment, comment_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if c.user_id != user["sub"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your comment")
    await db.delete(c)
    await db.commit()
