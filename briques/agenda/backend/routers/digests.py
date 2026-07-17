"""Digest quotidien/hebdo (S178) : composé ici, poussé (connexion) et/ou emailé (mail
6030). Déclenché par l'horloge du Cœur (POST /digests/executer, clé interne DIGEST_KEY).
Idempotent par (user, jour). Anti-intrusif : off par défaut + heures calmes respectées."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import get_db
from models.orm import UserProfile
from services.digest import composer
from services.heures_calmes import dans_les_heures_calmes

router = APIRouter(tags=["digests"])


async def _events_fenetre(db, user_id, debut, fin) -> list[dict]:
    """Events où `user_id` participe entre debut/fin (triés). Réutilise l'agrégation
    existante (`services.agregation.evenements_agreges`) : tous calendriers accessibles,
    récurrence dépliée, overrides pris en compte. Sa sortie porte `title`/`start_at`
    (heure Paris) / `calendrier` ; `composer` attend `titre`/`debut`/`calendrier`."""
    from services import agregation

    evts = await agregation.evenements_agreges(db, user_id, debut, fin)
    return [{"titre": e["title"], "debut": e["start_at"], "calendrier": e.get("calendrier", "")}
            for e in evts]


def _garde(cle: str | None):
    if not settings.DIGEST_KEY:
        raise HTTPException(503, "Digest non configuré.")
    if cle != settings.DIGEST_KEY:
        raise HTTPException(403, "Clé digest invalide.")


@router.post("/digests/executer")
async def executer(x_api_key: str | None = Header(default=None),
                   db: AsyncSession = Depends(get_db)):
    _garde(x_api_key)
    tz = ZoneInfo(settings.DIGEST_TZ)
    maintenant = datetime.now(tz)
    if maintenant.hour < settings.DIGEST_HEURE:
        return {"traites": 0, "envoyes_push": 0, "envoyes_email": 0}
    aujourd = maintenant.date().isoformat()
    cle_sem = f"{maintenant.isocalendar().year}-W{maintenant.isocalendar().week}"

    profs = (await db.execute(
        select(UserProfile).where(UserProfile.digest_cadence != "off"))).scalars().all()
    traites = push_n = mail_n = 0
    for p in profs:
        if dans_les_heures_calmes(p.heures_calmes, maintenant):
            continue
        if p.digest_cadence == "quotidien":
            if p.dernier_digest_quotidien == aujourd:
                continue
            debut = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
            fin = debut + timedelta(days=1)
        else:  # hebdo
            if maintenant.weekday() != 0 or p.dernier_digest_hebdo == cle_sem:
                continue
            debut = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
            fin = debut + timedelta(days=7)
        events = await _events_fenetre(db, p.user_id, debut, fin)
        d = composer(p.display_name, events, p.digest_cadence)
        if p.digest_push and settings.CONNEXION_URL:
            if await _pousser(p.user_id, f"{d['sujet']}\n{d['texte']}"):
                push_n += 1
        if p.digest_email and p.email and settings.MAIL_URL:
            if await _emailer(p.email, d["sujet"], d["texte"], d["html"]):
                mail_n += 1
        if p.digest_cadence == "quotidien":
            p.dernier_digest_quotidien = aujourd
        else:
            p.dernier_digest_hebdo = cle_sem
        traites += 1
    await db.commit()
    return {"traites": traites, "envoyes_push": push_n, "envoyes_email": mail_n}


async def _pousser(user_id: str, texte: str) -> bool:
    ent = {"X-API-Key": settings.CONNEXION_KEY} if settings.CONNEXION_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{settings.CONNEXION_URL.rstrip('/')}/pousser",
                         json={"utilisateur": user_id, "texte": texte}, headers=ent)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _emailer(a: str, sujet: str, corps: str, html: str) -> bool:
    ent = {"X-API-Key": settings.MAIL_KEY} if settings.MAIL_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"{settings.MAIL_URL.rstrip('/')}/mail/envoyer",
                         json={"a": a, "sujet": sujet, "corps": corps, "corps_html": html},
                         headers=ent)
        return True
    except Exception:  # noqa: BLE001
        return False
