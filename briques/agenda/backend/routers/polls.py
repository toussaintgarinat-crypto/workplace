"""Sondages de disponibilité (S177, façon Doodle) — /polls.

L'organisateur crée un sondage avec des créneaux, chacun vote par créneau (oui /
si_besoin / non), puis on finalise sur un créneau — ce qui crée un `Event` dans l'agenda
avec les votants « oui » (qui ont un compte) pré-ajoutés comme participants. Le vote passe
par `share_token` (capacité du lien public) : un invité vote sans compte, un membre
connecté voit son vote attribué à son profil. Cf. design
docs/superpowers/specs/2026-07-16-s177-sondages-disponibilite-design.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, get_optional_user
from config import settings
from db import get_db
from models.orm import AvailabilityPoll, Event, PollSlot, PollVote, UserProfile
from models.schemas import (
    VOTE_VALEURS,
    BallotIn,
    PollCreate,
    PollDetailOut,
    PollSlotIn,
    PollSlotOut,
    PollSummaryOut,
    PollUpdate,
    VoterLineOut,
)
from pydantic import BaseModel
from services import agregation
from services.participants_auto import assurer_participant
from services.pubsub import publish_change, publish_poll_change
from templates import page_sondage
from utils.access import require_calendar_access, require_owned_poll

router = APIRouter(tags=["polls"])


class FinalizeIn(BaseModel):
    slot_id: str
    calendar_id: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _slots(db: AsyncSession, poll_id: str) -> list[PollSlot]:
    rows = (await db.execute(
        select(PollSlot).where(PollSlot.poll_id == poll_id)
        .order_by(PollSlot.position, PollSlot.start_at))).scalars().all()
    return list(rows)


async def _detail(db: AsyncSession, poll: AvailabilityPoll, *, expose_token: bool) -> PollDetailOut:
    """Assemble la vue complète : créneaux + grille (votant × créneau) + tallies."""
    slots = await _slots(db, poll.id)
    votes = (await db.execute(
        select(PollVote).where(PollVote.poll_id == poll.id))).scalars().all()

    tallies: dict[str, dict[str, int]] = {
        s.id: {"oui": 0, "si_besoin": 0, "non": 0} for s in slots}
    lignes: dict[str, VoterLineOut] = {}
    for v in votes:
        cle = v.voter_id or f"guest:{v.guest_key}"
        ligne = lignes.get(cle)
        if ligne is None:
            ligne = VoterLineOut(
                voter_name=v.voter_name, voter_id=v.voter_id,
                is_guest=v.voter_id is None, votes={})
            lignes[cle] = ligne
        ligne.voter_name = v.voter_name  # snapshot le plus récent parcouru
        ligne.votes[v.slot_id] = v.value
        if v.slot_id in tallies and v.value in tallies[v.slot_id]:
            tallies[v.slot_id][v.value] += 1

    return PollDetailOut(
        id=poll.id, title=poll.title, description=poll.description,
        location=poll.location, status=poll.status, created_by=poll.created_by,
        share_token=poll.share_token if expose_token else None,
        final_slot_id=poll.final_slot_id, final_event_id=poll.final_event_id,
        expires_at=poll.expires_at,
        slots=[PollSlotOut.model_validate(s) for s in slots],
        voters=list(lignes.values()), tallies=tallies)


async def _poll_par_token(db: AsyncSession, share_token: str) -> AvailabilityPoll:
    poll = (await db.execute(
        select(AvailabilityPoll).where(
            AvailabilityPoll.share_token == share_token))).scalar_one_or_none()
    if poll is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sondage introuvable")
    return poll


# ── Gestion (organisateur) ────────────────────────────────────────────────────

@router.get("/polls", response_model=list[PollSummaryOut])
async def list_polls(db: AsyncSession = Depends(get_db),
                     user: dict = Depends(get_current_user)):
    polls = (await db.execute(
        select(AvailabilityPoll).where(AvailabilityPoll.created_by == user["sub"])
        .order_by(AvailabilityPoll.created_at.desc()))).scalars().all()
    sortie: list[PollSummaryOut] = []
    for p in polls:
        slots = await _slots(db, p.id)
        votes = (await db.execute(
            select(PollVote).where(PollVote.poll_id == p.id))).scalars().all()
        nb_voters = len({v.voter_id or f"guest:{v.guest_key}" for v in votes})
        sortie.append(PollSummaryOut(
            id=p.id, title=p.title, status=p.status, nb_slots=len(slots),
            nb_voters=nb_voters, share_token=p.share_token, final_slot_id=p.final_slot_id))
    return sortie


@router.post("/polls", response_model=PollDetailOut, status_code=status.HTTP_201_CREATED)
async def create_poll(body: PollCreate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    if not body.slots:
        raise HTTPException(status_code=422, detail="Au moins un créneau requis")
    expires_at = None
    if body.expire_heures:
        expires_at = datetime.utcnow() + timedelta(hours=body.expire_heures)
    poll = AvailabilityPoll(
        title=body.title, description=body.description, location=body.location,
        calendar_id=body.calendar_id, created_by=user["sub"], expires_at=expires_at)
    db.add(poll)
    await db.flush()
    for i, s in enumerate(body.slots):
        if s.start_at >= s.end_at:
            raise HTTPException(status_code=422, detail="fin doit être après debut")
        db.add(PollSlot(poll_id=poll.id, start_at=s.start_at, end_at=s.end_at, position=i))
    await db.commit()
    await db.refresh(poll)
    return await _detail(db, poll, expose_token=True)


@router.get("/polls/{poll_id}", response_model=PollDetailOut)
async def get_poll(poll_id: str, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    poll = await require_owned_poll(db, poll_id, user["sub"])
    return await _detail(db, poll, expose_token=True)


@router.patch("/polls/{poll_id}", response_model=PollDetailOut)
async def update_poll(poll_id: str, body: PollUpdate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    poll = await require_owned_poll(db, poll_id, user["sub"])
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(poll, k, v)
    await db.commit()
    await db.refresh(poll)
    return await _detail(db, poll, expose_token=True)


@router.post("/polls/{poll_id}/slots", response_model=PollSlotOut, status_code=status.HTTP_201_CREATED)
async def add_slot(poll_id: str, body: PollSlotIn, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    poll = await require_owned_poll(db, poll_id, user["sub"])
    if poll.status != "open":
        raise HTTPException(status_code=409, detail="Sondage clôturé")
    if body.start_at >= body.end_at:
        raise HTTPException(status_code=422, detail="fin doit être après debut")
    existants = await _slots(db, poll_id)
    slot = PollSlot(poll_id=poll_id, start_at=body.start_at, end_at=body.end_at,
                    position=len(existants))
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    await publish_poll_change(poll_id, "poll.slot_added", {"slot_id": slot.id})
    return PollSlotOut.model_validate(slot)


@router.delete("/polls/{poll_id}/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(poll_id: str, slot_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    poll = await require_owned_poll(db, poll_id, user["sub"])
    if poll.status != "open":
        raise HTTPException(status_code=409, detail="Sondage clôturé")
    slot = await db.get(PollSlot, slot_id)
    if slot is None or slot.poll_id != poll_id:
        raise HTTPException(status_code=404, detail="Créneau introuvable")
    await db.delete(slot)  # cascade → les votes de ce créneau partent aussi
    await db.commit()
    await publish_poll_change(poll_id, "poll.slot_removed", {"slot_id": slot_id})


@router.delete("/polls/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_poll(poll_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    poll = await require_owned_poll(db, poll_id, user["sub"])
    await db.delete(poll)
    await db.commit()


@router.post("/polls/{poll_id}/finalize")
async def finalize_poll(poll_id: str, body: FinalizeIn, db: AsyncSession = Depends(get_db),
                        user: dict = Depends(get_current_user)):
    """Retient un créneau : crée l'événement agenda + pré-ajoute les votants « oui »
    (membres), clôture le sondage. C'est le plus vs Doodle : la boucle sondage→agenda."""
    poll = await require_owned_poll(db, poll_id, user["sub"])
    if poll.status != "open":
        raise HTTPException(status_code=409, detail="Sondage déjà clôturé")
    slot = await db.get(PollSlot, body.slot_id)
    if slot is None or slot.poll_id != poll_id:
        raise HTTPException(status_code=404, detail="Créneau introuvable")

    # Résolution du calendrier cible : explicite (droit editor) sinon défaut de l'organisateur.
    cal_id = body.calendar_id or poll.calendar_id
    if cal_id:
        await require_calendar_access(db, cal_id, user["sub"], min_role="editor")
    else:
        cal_id = (await agregation.calendrier_defaut(db, user["sub"])).id

    evt = Event(
        calendar_id=cal_id, title=poll.title, description=poll.description,
        start_at=slot.start_at, end_at=slot.end_at, location=poll.location,
        created_by=user["sub"])
    db.add(evt)
    await db.flush()
    # Pré-ajout des participants : l'organisateur + les membres ayant voté « oui » sur ce
    # créneau. Les invités anonymes (voter_id NULL) n'ont pas de compte → non ajoutés.
    await assurer_participant(db, evt.id, user["sub"])
    oui = (await db.execute(
        select(PollVote.voter_id).where(
            PollVote.slot_id == slot.id, PollVote.value == "oui",
            PollVote.voter_id.is_not(None)))).scalars().all()
    for vid in {v for v in oui if v}:
        await assurer_participant(db, evt.id, vid)

    poll.status = "closed"
    poll.final_slot_id = slot.id
    poll.final_event_id = evt.id
    await db.commit()
    await publish_change(cal_id, "event.created", {"id": evt.id})
    await publish_poll_change(poll_id, "poll.finalized",
                              {"slot_id": slot.id, "event_id": evt.id})
    return {"event_id": evt.id, "calendar_id": cal_id, "slot_id": slot.id}


# ── Vote (public, par jeton — attribue au membre si connecté) ──────────────────

@router.get("/polls/token/{share_token}", response_model=PollDetailOut)
async def get_poll_public(share_token: str, db: AsyncSession = Depends(get_db)):
    """Vue votant par lien : sondage + créneaux + grille. N'expose PAS le share_token."""
    poll = await _poll_par_token(db, share_token)
    return await _detail(db, poll, expose_token=False)


@router.post("/polls/token/{share_token}/vote")
async def vote(share_token: str, body: BallotIn, db: AsyncSession = Depends(get_db),
               user: dict | None = Depends(get_optional_user)):
    poll = await _poll_par_token(db, share_token)
    if poll.status != "open":
        raise HTTPException(status_code=409, detail="Sondage clôturé")
    if poll.expires_at and poll.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Lien de vote expiré")

    # Identité du votant : membre connecté (attribué) sinon invité (nom requis).
    if user and user.get("sub") and user["sub"] != "anonymous":
        voter_id = user["sub"]
        guest_key = None
        prof = await db.get(UserProfile, voter_id)
        voter_name = (prof.display_name if prof else None) or user.get("name") or voter_id
    else:
        voter_id = None
        nom = (body.nom or "").strip()
        if not nom:
            raise HTTPException(status_code=422, detail="nom requis pour voter en invité")
        voter_name = nom
        guest_key = body.guest_key or str(uuid.uuid4())

    slots = {s.id for s in await _slots(db, poll.id)}
    for v in body.votes:
        if v.slot_id not in slots:
            raise HTTPException(status_code=422, detail=f"créneau inconnu : {v.slot_id}")
        if v.value not in VOTE_VALEURS:
            raise HTTPException(status_code=422, detail=f"valeur invalide : {v.value}")

    # Remplace le bulletin de cette identité (delete + insert) → un bulletin par personne.
    if voter_id is not None:
        anciens = (await db.execute(select(PollVote).where(
            PollVote.poll_id == poll.id, PollVote.voter_id == voter_id))).scalars().all()
    else:
        anciens = (await db.execute(select(PollVote).where(
            PollVote.poll_id == poll.id, PollVote.guest_key == guest_key))).scalars().all()
    for a in anciens:
        await db.delete(a)
    for v in body.votes:
        db.add(PollVote(
            poll_id=poll.id, slot_id=v.slot_id, voter_id=voter_id,
            voter_name=voter_name, guest_key=guest_key, value=v.value))
    await db.commit()
    await publish_poll_change(poll.id, "poll.voted", {"voter_name": voter_name})
    return {"guest_key": guest_key, "voter_name": voter_name}


@router.get("/polls/p/{share_token}", response_class=HTMLResponse, include_in_schema=False)
async def vote_page(share_token: str):
    """Page HTML autonome de vote (transmise à l'invité). Charge le sondage côté client."""
    return page_sondage(share_token)
