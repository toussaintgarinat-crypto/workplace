"""S177 — finalisation : crée l'événement + pré-ajoute les votants « oui » membres."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.orm import AvailabilityPoll, Event, EventParticipant
from models.schemas import BallotIn, PollCreate, PollSlotIn, VoteIn
from routers import polls as R
from routers.polls import FinalizeIn

ORG = {"sub": "perso"}


async def _poll(db):
    slots = [PollSlotIn(start_at=datetime(2026, 8, d, 18), end_at=datetime(2026, 8, d, 20))
             for d in (1, 2)]
    return await R.create_poll(
        PollCreate(title="Dîner", location="Chez Paul", slots=slots), db=db, user=ORG)


@pytest.mark.asyncio
async def test_finalize_cree_event_et_participants(db):
    poll = await _poll(db)
    s0 = poll.slots[0].id
    # Un membre vote oui, un invité vote oui (pas de compte → non participant), un membre non.
    await R.vote(poll.share_token, BallotIn(votes=[VoteIn(slot_id=s0, value="oui")]),
                 db=db, user={"sub": "marina"})
    await R.vote(poll.share_token, BallotIn(nom="Invité", votes=[VoteIn(slot_id=s0, value="oui")]),
                 db=db, user=None)
    await R.vote(poll.share_token, BallotIn(votes=[VoteIn(slot_id=s0, value="non")]),
                 db=db, user={"sub": "bob"})

    res = await R.finalize_poll(poll.id, FinalizeIn(slot_id=s0), db=db, user=ORG)
    evt = await db.get(Event, res["event_id"])
    assert evt.title == "Dîner" and evt.location == "Chez Paul"
    assert evt.start_at == datetime(2026, 8, 1, 18)

    parts = (await db.execute(select(EventParticipant).where(
        EventParticipant.event_id == evt.id))).scalars().all()
    uids = {p.user_id for p in parts}
    assert "perso" in uids and "marina" in uids  # organisateur + oui membre
    assert "bob" not in uids  # a voté non
    assert "Invité" not in uids  # invité anonyme, pas de compte

    orm = await db.get(AvailabilityPoll, poll.id)
    assert orm.status == "closed" and orm.final_event_id == evt.id


@pytest.mark.asyncio
async def test_finalize_deux_fois_refuse(db):
    poll = await _poll(db)
    await R.finalize_poll(poll.id, FinalizeIn(slot_id=poll.slots[0].id), db=db, user=ORG)
    with pytest.raises(HTTPException) as exc:
        await R.finalize_poll(poll.id, FinalizeIn(slot_id=poll.slots[0].id), db=db, user=ORG)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_finalize_creneau_etranger_refuse(db):
    poll = await _poll(db)
    with pytest.raises(HTTPException) as exc:
        await R.finalize_poll(poll.id, FinalizeIn(slot_id="bidon"), db=db, user=ORG)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_finalize_non_organisateur_refuse(db):
    poll = await _poll(db)
    with pytest.raises(HTTPException) as exc:
        await R.finalize_poll(poll.id, FinalizeIn(slot_id=poll.slots[0].id),
                              db=db, user={"sub": "marina"})
    assert exc.value.status_code == 404
