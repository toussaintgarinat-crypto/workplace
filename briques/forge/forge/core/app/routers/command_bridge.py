"""Router command-bridge. Portage de routes/command-bridge.ts (S133).

Monté /api/command-bridge, protégé. Poste de pilotage fondateur : overview des
pôles (décisions en attente, membres, kill-switch), décisions N0 (créer / approuver
/ rejeter avec injection blackboard), toggle pause par pôle, et flux blackboard.

Quirk : ``kill_switches`` est mappé par sqlacodegen en héritage joint sur ``Poles``
(PK = FK). On opère donc dessus via SQLAlchemy Core (``KillSwitches.__table__``)
pour éviter la sémantique d'héritage ORM sur insert/update.
"""

from __future__ import annotations

import datetime
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy import insert as core_insert
from sqlalchemy import update as core_update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import BlackboardEvents, DecisionsN0, KillSwitches, PoleMembers, Poles, Ventures
from app.serde import blackboard_event, decision_n0

router = APIRouter()

_KS = KillSwitches.__table__  # table kill_switches (héritage ORM contourné)


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v) if v else None
    except (ValueError, TypeError):
        return None


@router.get("/overview", dependencies=[Depends(get_current_user)])
async def overview(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        user_poles = (await s.execute(select(Poles).where(Poles.owner_id == user.sub))).scalars().all()
        if not user_poles:
            return {"poles": [], "ventures": [], "totalDecisions": 0, "totalPoles": 0}

        user_ventures = (await s.execute(select(Ventures).where(Ventures.owner_id == user.sub))).scalars().all()
        pole_ids = [p.id for p in user_poles]

        dec_rows = (await s.execute(
            select(DecisionsN0.pole_id, func.count())
            .where(and_(DecisionsN0.statut == "en_attente", DecisionsN0.pole_id.in_(pole_ids)))
            .group_by(DecisionsN0.pole_id)
        )).all()
        mem_rows = (await s.execute(
            select(PoleMembers.pole_id, func.count())
            .where(PoleMembers.pole_id.in_(pole_ids))
            .group_by(PoleMembers.pole_id)
        )).all()
        sw_rows = (await s.execute(
            select(_KS.c.pole_id, _KS.c.en_pause).where(_KS.c.pole_id.in_(pole_ids))
        )).all()

        dec_map = {r[0]: int(r[1]) for r in dec_rows}
        mem_map = {r[0]: int(r[1]) for r in mem_rows}
        sw_map = {r[0]: r[1] for r in sw_rows}
        venture_map = {v.id: v for v in user_ventures}

        poles_data = []
        for p in user_poles:
            vid = _uuid(p.venture_id)
            vobj = venture_map.get(vid) if vid else None
            poles_data.append({
                "id": str(p.id),
                "nom": p.nom,
                "emoji": p.emoji,
                "couleur": p.couleur,
                "ventureId": p.venture_id or None,
                "ventureNom": (vobj.nom if vobj else None) if p.venture_id else None,
                "ventureEmoji": (vobj.emoji if vobj else None) if p.venture_id else None,
                "nbMembres": mem_map.get(p.id, 0),
                "nbDecisions": dec_map.get(p.id, 0),
                "enPause": sw_map.get(p.id, False),
            })

        return {
            "poles": poles_data,
            "ventures": [
                {"id": str(v.id), "nom": v.nom, "emoji": v.emoji, "couleur": v.couleur, "type": v.type}
                for v in user_ventures
            ],
            "totalDecisions": sum(dec_map.values()),
            "totalPoles": len(user_poles),
        }


@router.get("/decisions", dependencies=[Depends(get_current_user)])
async def list_decisions(statut: str = "en_attente"):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(DecisionsN0).where(DecisionsN0.statut == statut)
            .order_by(desc(DecisionsN0.created_at)).limit(200)
        )).scalars().all()
    return [decision_n0(x) for x in rows]


class CreateDecision(BaseModel):
    poleId: str | None = None
    poleNom: str
    agentNom: str
    action: str
    niveau: str = "N0"
    urgence: str = "normale"


@router.post("/decisions", dependencies=[Depends(get_current_user)])
async def create_decision(body: CreateDecision):
    async with SessionLocal() as s:
        decision = DecisionsN0(
            pole_id=_uuid(body.poleId), pole_nom=body.poleNom, agent_nom=body.agentNom,
            action=body.action, niveau=body.niveau, urgence=body.urgence,
        )
        s.add(decision)
        await s.commit()
        await s.refresh(decision)
        s.add(BlackboardEvents(
            pole_id=_uuid(body.poleId), pole_nom=body.poleNom, agent_nom=body.agentNom,
            type="decision_created", payload=f"[{body.niveau}] {body.action[:200]}", niveau=body.niveau,
        ))
        await s.commit()
    return JSONResponse(status_code=201, content={"id": str(decision.id), "statut": decision.statut})


async def _resolve_decision(did: str, user_sub: str, statut: str, bb_type: str, bb_prefix: str):
    duid = _uuid(did)
    async with SessionLocal() as s:
        decision = None
        if duid:
            await s.execute(
                core_update(DecisionsN0.__table__).where(DecisionsN0.id == duid)
                .values(statut=statut, resolved_at=datetime.datetime.utcnow(), resolved_by=user_sub)
            )
            await s.commit()
            decision = (await s.execute(select(DecisionsN0).where(DecisionsN0.id == duid))).scalar_one_or_none()
        if decision is None:
            raise HTTPException(status_code=404, detail="Not found")
        s.add(BlackboardEvents(
            pole_id=decision.pole_id, pole_nom=decision.pole_nom, agent_nom=decision.agent_nom,
            type=bb_type, payload=f"{bb_prefix} {decision.action[:200]}", niveau="N1",
        ))
        await s.commit()
    return decision


@router.post("/decisions/{did}/approuver", dependencies=[Depends(get_current_user)])
async def approve_decision(did: str, user: UserContext = Depends(get_current_user)):
    decision = await _resolve_decision(did, user.sub, "approuve", "decision_approuvee", "[N0 APPROUVÉ]")
    return {"ok": True, "statut": "approuve", "action": decision.action}


@router.post("/decisions/{did}/rejeter", dependencies=[Depends(get_current_user)])
async def reject_decision(did: str, user: UserContext = Depends(get_current_user)):
    await _resolve_decision(did, user.sub, "rejete", "decision_rejetee", "[N0 REJETÉ]")
    return {"ok": True, "statut": "rejete"}


@router.post("/poles/{pole_id}/toggle-pause", dependencies=[Depends(get_current_user)])
async def toggle_pause(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        pole = (await s.execute(
            select(Poles.id).where(and_(Poles.id == puid, Poles.owner_id == user.sub))
        )).first() if puid else None
        if pole is None:
            raise HTTPException(status_code=404, detail="Not found")

        existing = (await s.execute(select(_KS.c.en_pause).where(_KS.c.pole_id == puid))).first()
        if existing is None:
            await s.execute(core_insert(_KS).values(pole_id=puid, en_pause=True, updated_by=user.sub))
            await s.commit()
            return {"poleId": pole_id, "enPause": True}

        new_val = not existing[0]
        await s.execute(
            core_update(_KS).where(_KS.c.pole_id == puid)
            .values(en_pause=new_val, updated_at=datetime.datetime.utcnow(), updated_by=user.sub)
        )
        await s.commit()
    return {"poleId": pole_id, "enPause": new_val}


@router.get("/blackboard", dependencies=[Depends(get_current_user)])
async def blackboard(niveau: str | None = None, limit: int = 30):
    lim = min(limit, 100)
    async with SessionLocal() as s:
        q = select(BlackboardEvents)
        if niveau:
            q = q.where(BlackboardEvents.niveau == niveau)
        q = q.order_by(desc(BlackboardEvents.created_at)).limit(lim)
        rows = (await s.execute(q)).scalars().all()
    return [blackboard_event(x) for x in rows]
