"""S177 — vote par lien : invité (guest_key stable + réédition) et membre (attribué)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from models.orm import AvailabilityPoll, UserProfile
from models.schemas import BallotIn, PollCreate, PollSlotIn, VoteIn
from routers import polls as R

ORG = {"sub": "perso"}


async def _poll(db, n=2):
    slots = [PollSlotIn(start_at=datetime(2026, 8, d, 18), end_at=datetime(2026, 8, d, 20))
             for d in range(1, n + 1)]
    return await R.create_poll(PollCreate(title="Dîner", slots=slots), db=db, user=ORG)


@pytest.mark.asyncio
async def test_vote_invite_renvoie_guest_key(db):
    poll = await _poll(db)
    s = poll.slots
    res = await R.vote(poll.share_token, BallotIn(
        nom="Marina", votes=[VoteIn(slot_id=s[0].id, value="oui"),
                              VoteIn(slot_id=s[1].id, value="non")]), db=db, user=None)
    assert res["guest_key"]
    detail = await R.get_poll_public(poll.share_token, db=db)
    assert detail.share_token is None  # jamais exposé côté votant
    assert detail.tallies[s[0].id]["oui"] == 1
    assert detail.tallies[s[1].id]["non"] == 1
    assert len(detail.voters) == 1 and detail.voters[0].is_guest


@pytest.mark.asyncio
async def test_vote_invite_reedition_remplace(db):
    poll = await _poll(db)
    s = poll.slots
    r1 = await R.vote(poll.share_token, BallotIn(
        nom="Marina", votes=[VoteIn(slot_id=s[0].id, value="oui")]), db=db, user=None)
    gk = r1["guest_key"]
    # Même invité change d'avis (réutilise guest_key) → bulletin remplacé, pas cumulé.
    await R.vote(poll.share_token, BallotIn(
        nom="Marina", guest_key=gk, votes=[VoteIn(slot_id=s[0].id, value="non")]),
        db=db, user=None)
    detail = await R.get_poll_public(poll.share_token, db=db)
    assert detail.tallies[s[0].id]["oui"] == 0 and detail.tallies[s[0].id]["non"] == 1
    assert len(detail.voters) == 1


@pytest.mark.asyncio
async def test_vote_invite_sans_nom_refuse(db):
    poll = await _poll(db)
    with pytest.raises(HTTPException) as exc:
        await R.vote(poll.share_token, BallotIn(
            votes=[VoteIn(slot_id=poll.slots[0].id, value="oui")]), db=db, user=None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_vote_membre_attribue_au_profil(db):
    db.add(UserProfile(user_id="marina", display_name="Marina D."))
    await db.commit()
    poll = await _poll(db)
    res = await R.vote(poll.share_token, BallotIn(
        votes=[VoteIn(slot_id=poll.slots[0].id, value="oui")]), db=db, user={"sub": "marina"})
    assert res["guest_key"] is None and res["voter_name"] == "Marina D."
    detail = await R.get_poll_public(poll.share_token, db=db)
    assert detail.voters[0].voter_id == "marina" and not detail.voters[0].is_guest


@pytest.mark.asyncio
async def test_vote_creneau_inconnu_refuse(db):
    poll = await _poll(db)
    with pytest.raises(HTTPException) as exc:
        await R.vote(poll.share_token, BallotIn(
            nom="X", votes=[VoteIn(slot_id="bidon", value="oui")]), db=db, user=None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_vote_lien_expire_refuse(db):
    poll = await _poll(db)
    orm = await db.get(AvailabilityPoll, poll.id)
    orm.expires_at = datetime.utcnow() - timedelta(hours=1)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.vote(poll.share_token, BallotIn(
            nom="X", votes=[VoteIn(slot_id=poll.slots[0].id, value="oui")]), db=db, user=None)
    assert exc.value.status_code == 410
