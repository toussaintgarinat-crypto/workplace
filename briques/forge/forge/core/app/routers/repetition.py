"""Router repetition. Portage de routes/repetition.ts (S133). Monté /api, protégé.

Détection d'actions répétées → suggestion d'automatisation (HITL → Pôle Dev).
Config par pôle (seuil/période/silence), log d'événements, et flux respond qui
crée une `pole_dev_requests` (approve) ou met l'action en silence (reject).

Parité fine : les conditions jsonb du Bun (``payload::jsonb->>'actionKey'``) sont
répliquées via ``cast(payload, JSONB)[...].astext``.
"""

from __future__ import annotations

import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import (
    HitlRequests,
    Poles,
    PoleDevRequests,
    RepetitionConfigs,
    RepetitionEvents,
    RepetitionSilences,
)
from app.serde import hitl_request, repetition_config

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/repetition-config", dependencies=[Depends(get_current_user)])
async def get_config(pole_id: str):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        cfg = (await s.execute(
            select(RepetitionConfigs).where(RepetitionConfigs.pole_id == puid)
        )).scalar_one_or_none() if puid else None
    if cfg is not None:
        return repetition_config(cfg)
    return {"poleId": pole_id, "seuilOccurrences": 3, "periodeJours": 7, "silenceDays": 30, "actif": True}


class PutConfig(BaseModel):
    seuilOccurrences: int | None = Field(default=None, ge=1, le=50)
    periodeJours: int | None = Field(default=None, ge=1, le=90)
    silenceDays: int | None = Field(default=None, ge=0, le=365)
    actif: bool | None = None


_CFG_COLMAP = {
    "seuilOccurrences": "seuil_occurrences",
    "periodeJours": "periode_jours",
    "silenceDays": "silence_days",
    "actif": "actif",
}


@router.put("/poles/{pole_id}/repetition-config", dependencies=[Depends(get_current_user)])
async def put_config(pole_id: str, body: PutConfig):
    puid = _uuid(pole_id)
    raw = body.model_dump(exclude_unset=True)
    cols = {_CFG_COLMAP[k]: v for k, v in raw.items() if k in _CFG_COLMAP}
    async with SessionLocal() as s:
        existing = (await s.execute(
            select(RepetitionConfigs.id).where(RepetitionConfigs.pole_id == puid)
        )).scalar_one_or_none() if puid else None
        if existing is not None:
            cols["updated_at"] = datetime.datetime.utcnow()
            await s.execute(update(RepetitionConfigs).where(RepetitionConfigs.pole_id == puid).values(**cols))
            await s.commit()
            cfg = (await s.execute(
                select(RepetitionConfigs).where(RepetitionConfigs.pole_id == puid)
            )).scalar_one()
            return repetition_config(cfg)
        cfg = RepetitionConfigs(pole_id=puid, **cols)
        s.add(cfg)
        await s.commit()
        await s.refresh(cfg)
    return repetition_config(cfg)


class EventBody(BaseModel):
    poleId: str
    actionKey: str = Field(min_length=1)
    actionLabel: str = Field(min_length=1)


@router.post("/repetition/event", dependencies=[Depends(get_current_user)])
async def log_event(body: EventBody, user: UserContext = Depends(get_current_user)):
    puid = _uuid(body.poleId)
    async with SessionLocal() as s:
        cfg = (await s.execute(
            select(RepetitionConfigs).where(RepetitionConfigs.pole_id == puid)
        )).scalar_one_or_none()
        seuil = cfg.seuil_occurrences if cfg and cfg.seuil_occurrences is not None else 3
        periode_j = cfg.periode_jours if cfg and cfg.periode_jours is not None else 7
        actif = cfg.actif if cfg and cfg.actif is not None else True

        if not actif:
            return {"triggered": False}

        now = datetime.datetime.utcnow()
        silence = (await s.execute(
            select(RepetitionSilences).where(and_(
                RepetitionSilences.pole_id == puid,
                RepetitionSilences.action_key == body.actionKey,
                RepetitionSilences.silence_until >= now,
            ))
        )).scalars().first()
        if silence is not None:
            return {"triggered": False, "silenced": True}

        pending = (await s.execute(
            select(HitlRequests.id).where(and_(
                HitlRequests.statut == "pending",
                cast(HitlRequests.payload, JSONB)["actionKey"].astext == body.actionKey,
                cast(HitlRequests.payload, JSONB)["poleId"].astext == body.poleId,
            ))
        )).first()
        if pending is not None:
            return {"triggered": False, "alreadyPending": True}

        s.add(RepetitionEvents(pole_id=puid, user_id=user.sub, action_key=body.actionKey, action_label=body.actionLabel))
        await s.commit()

        since = now - datetime.timedelta(days=periode_j)
        total = (await s.execute(
            select(func.count()).select_from(RepetitionEvents).where(and_(
                RepetitionEvents.pole_id == puid,
                RepetitionEvents.action_key == body.actionKey,
                RepetitionEvents.created_at >= since,
            ))
        )).scalar_one()

        if total >= seuil:
            hitl = HitlRequests(
                user_id=user.sub, niveau=1, action="repetition_suggest",
                payload=json.dumps({
                    "poleId": body.poleId, "actionKey": body.actionKey,
                    "actionLabel": body.actionLabel, "count": total, "periodeJours": periode_j,
                }),
                statut="pending",
            )
            s.add(hitl)
            await s.commit()
            await s.refresh(hitl)
            return {"triggered": True, "hitlId": str(hitl.id), "count": total}

    return {"triggered": False, "count": total, "remaining": seuil - total}


@router.get("/repetition/pending/{pole_id}", dependencies=[Depends(get_current_user)])
async def pending_for_pole(pole_id: str):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(HitlRequests).where(and_(
                HitlRequests.statut == "pending",
                HitlRequests.action == "repetition_suggest",
                cast(HitlRequests.payload, JSONB)["poleId"].astext == pole_id,
            ))
        )).scalars().all()
    return [hitl_request(x) for x in rows]


class RespondBody(BaseModel):
    decision: str  # 'approve' | 'reject'


@router.post("/repetition/respond/{hitl_id}", dependencies=[Depends(get_current_user)])
async def respond(hitl_id: str, body: RespondBody, user: UserContext = Depends(get_current_user)):
    from fastapi import HTTPException

    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid decision")
    huid = _uuid(hitl_id)
    async with SessionLocal() as s:
        hitl = (await s.execute(
            select(HitlRequests).where(HitlRequests.id == huid)
        )).scalar_one_or_none() if huid else None
        if hitl is None or hitl.statut != "pending":
            raise HTTPException(status_code=404, detail="Not found or already resolved")

        payload = json.loads(hitl.payload or "{}")
        pole_id = payload.get("poleId")
        action_key = payload.get("actionKey")
        action_label = payload.get("actionLabel")
        count = payload.get("count")
        periode_jours = payload.get("periodeJours")
        puid = _uuid(pole_id)

        await s.execute(
            update(HitlRequests).where(HitlRequests.id == huid).values(
                statut="approved" if body.decision == "approve" else "rejected",
                decide_par=user.sub, decide_at=datetime.datetime.utcnow(),
            )
        )

        if body.decision == "approve":
            pole = (await s.execute(
                select(Poles.nom, Poles.emoji).where(Poles.id == puid)
            )).first() if puid else None
            s.add(PoleDevRequests(
                source_pole_id=puid,
                source_pole_name=(pole.nom if pole else "Pôle"),
                source_pole_emoji=(pole.emoji if pole else "📌"),
                title=f"Automatiser : {action_label}",
                description=(
                    f'Action "{action_label}" répétée {count} fois en {periode_jours} jours. '
                    "Soumis automatiquement par le système de détection."
                ),
                frequency="on_event", priority="medium", user_id=user.sub,
            ))
        else:
            cfg = (await s.execute(
                select(RepetitionConfigs.silence_days).where(RepetitionConfigs.pole_id == puid)
            )).scalar_one_or_none() if puid else None
            silence_days = cfg if cfg is not None else 30
            silence_until = datetime.datetime.utcnow() + datetime.timedelta(days=silence_days)
            stmt = pg_insert(RepetitionSilences.__table__).values(
                pole_id=puid, action_key=action_key, silence_until=silence_until,
            ).on_conflict_do_update(
                index_elements=["pole_id", "action_key"],
                set_={"silence_until": silence_until},
            )
            await s.execute(stmt)

        await s.commit()
    return {"ok": True, "decision": body.decision}
