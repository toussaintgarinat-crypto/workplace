"""Abonnement webcal (S179) : l'utilisateur récupère/régénère son lien (auth Bearer) ; le
flux `.ics` est PUBLIC — le jeton dans l'URL EST la capacité (motif SSE sondages). Lecture
seule : aucune écriture entrante."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from db import get_db
from models.orm import Event
from services import abonnement, ics
from services.agregation import calendriers_accessibles

router = APIRouter(tags=["ics"])


def _base(request: Request) -> str:
    return (settings.AGENDA_URL_PUBLIQUE or str(request.base_url)).rstrip("/")


def _liens(base: str, token: str) -> dict:
    return {"token": token, "https": abonnement.url_https(base, token),
            "webcal": abonnement.url_webcal(base, token)}


@router.get("/ics/cle")
async def cle(request: Request, db: AsyncSession = Depends(get_db),
              user: dict = Depends(get_current_user)):
    """Renvoie (en le créant au besoin) le lien d'abonnement webcal de l'appelant."""
    token = await abonnement.obtenir_ou_creer_token(db, user["sub"])
    return _liens(_base(request), token)


@router.post("/ics/regenerer")
async def regenerer(request: Request, db: AsyncSession = Depends(get_db),
                    user: dict = Depends(get_current_user)):
    """Régénère le jeton (révoque l'ancien) et renvoie le nouveau lien."""
    token = await abonnement.regenerer_token(db, user["sub"])
    return _liens(_base(request), token)


@router.get("/ics/{token}.ics")
async def flux(token: str, db: AsyncSession = Depends(get_db)):
    """Flux VCALENDAR des calendriers accessibles de l'utilisateur résolu par le jeton.
    PUBLIC (jeton = capacité) ; 404 si jeton inconnu (ne divulgue rien)."""
    uid = await abonnement.user_pour_token(db, token)
    if uid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flux introuvable")
    cals = await calendriers_accessibles(db, uid)
    ids = [c.id for c in cals]
    events = []
    if ids:
        events = (await db.execute(
            select(Event).where(Event.calendar_id.in_(ids)))).scalars().all()
    corps = ics.generer_ics([ics.event_en_vevent(e) for e in events])
    return Response(corps, media_type="text/calendar; charset=utf-8")
