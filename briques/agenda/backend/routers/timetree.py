"""Pont TimeTree — /timetree/*.

Miroir du pont Google (`google_sync.py`), mais TimeTree n'a plus d'API officielle :
on se connecte par email/mot de passe (rangés chiffrés au coffre) et on lit l'agenda
partagé via l'API web interne non officielle. Lecture seule, pull one-way, révocable.

  POST   /timetree/connect     → valide le login, range les identifiants, liste les calendriers
  POST   /timetree/select      → choisit le calendrier partagé à synchroniser
  GET    /timetree/status      → connecté ? calendrier sélectionné ?
  POST   /timetree/sync        → pull les événements → calendrier « TimeTree »
  DELETE /timetree/disconnect  → purge les identifiants (révocation)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from services import timetree_calendar, timetree_client
from vault import delete_token, get_token_row, upsert_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/timetree", tags=["timetree"])


class ConnectBody(BaseModel):
    email: str
    password: str
    calendar_id: str | None = None


class SelectBody(BaseModel):
    calendar_id: str


@router.post("/connect")
async def timetree_connect(
    body: ConnectBody,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Valide les identifiants TimeTree (en listant les calendriers), puis les range
    chiffrés au coffre. Renvoie la liste des calendriers pour en choisir un à synchroniser."""
    try:
        cals = await asyncio.to_thread(
            timetree_client.list_calendars, body.email, body.password)
    except timetree_client.TimeTreeAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except timetree_client.TimeTreeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    await upsert_token(
        db,
        user["sub"],
        body.password,                 # access_token_enc = mot de passe (chiffré)
        provider="timetree",
        refresh_token=body.email,      # refresh_token_enc = email (chiffré)
        scope=body.calendar_id,        # scope = calendrier sélectionné (None possible ici)
    )
    return {"connected": True, "calendars": cals, "calendar_id": body.calendar_id}


@router.post("/select")
async def timetree_select(
    body: SelectBody,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Choisit le calendrier partagé à synchroniser (met à jour le coffre sans
    redemander le mot de passe)."""
    row = await get_token_row(db, user["sub"], "timetree")
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="TimeTree non connecté — fais /timetree/connect d'abord")
    row.scope = body.calendar_id
    await db.commit()
    return {"calendar_id": body.calendar_id}


@router.get("/status")
async def timetree_status(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    row = await get_token_row(db, user["sub"], "timetree")
    if row is None:
        return {"connected": False}
    return {"connected": True, "calendar_id": row.scope}


@router.post("/sync")
async def timetree_sync(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await timetree_calendar.sync_user(db, user["sub"])
    except timetree_calendar.TimeTreeSyncError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except timetree_client.TimeTreeAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except timetree_client.TimeTreeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.delete("/disconnect")
async def timetree_disconnect(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    existed = await delete_token(db, user["sub"], "timetree")
    return {"disconnected": existed}
