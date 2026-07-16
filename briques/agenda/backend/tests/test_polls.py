"""S177 — sondages : CRUD organisateur + gate 404 + créneaux."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.schemas import PollCreate, PollSlotIn, PollUpdate
from routers import polls as R

ORG = {"sub": "perso"}
AUTRE = {"sub": "marina"}


def _slots(*paires):
    from datetime import datetime
    return [PollSlotIn(start_at=datetime(2026, 8, d, 18), end_at=datetime(2026, 8, d, 20))
            for d in paires]


@pytest.mark.asyncio
async def test_create_renvoie_detail_et_token(db):
    out = await R.create_poll(
        PollCreate(title="Dîner", slots=_slots(1, 2)), db=db, user=ORG)
    assert out.title == "Dîner" and len(out.slots) == 2
    assert out.share_token  # exposé à l'organisateur
    assert out.status == "open"


@pytest.mark.asyncio
async def test_create_sans_creneau_refuse(db):
    with pytest.raises(HTTPException) as exc:
        await R.create_poll(PollCreate(title="Vide", slots=[]), db=db, user=ORG)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_poll_reserve_organisateur(db):
    poll = await R.create_poll(PollCreate(title="X", slots=_slots(1)), db=db, user=ORG)
    with pytest.raises(HTTPException) as exc:
        await R.get_poll(poll.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_polls_compte_votants(db):
    poll = await R.create_poll(PollCreate(title="X", slots=_slots(1)), db=db, user=ORG)
    sid = poll.slots[0].id
    from models.schemas import BallotIn, VoteIn
    await R.vote(poll.share_token, BallotIn(nom="Marina", votes=[VoteIn(slot_id=sid, value="oui")]),
                 db=db, user=None)
    mes = await R.list_polls(db=db, user=ORG)
    assert mes[0].nb_voters == 1 and mes[0].nb_slots == 1


@pytest.mark.asyncio
async def test_ajout_creneau_et_suppression(db):
    poll = await R.create_poll(PollCreate(title="X", slots=_slots(1)), db=db, user=ORG)
    s = await R.add_slot(poll.id, _slots(3)[0], db=db, user=ORG)
    detail = await R.get_poll(poll.id, db=db, user=ORG)
    assert len(detail.slots) == 2
    await R.delete_slot(poll.id, s.id, db=db, user=ORG)
    detail = await R.get_poll(poll.id, db=db, user=ORG)
    assert len(detail.slots) == 1


@pytest.mark.asyncio
async def test_update_titre(db):
    poll = await R.create_poll(PollCreate(title="X", slots=_slots(1)), db=db, user=ORG)
    out = await R.update_poll(poll.id, PollUpdate(title="Y", location="Chez moi"), db=db, user=ORG)
    assert out.title == "Y" and out.location == "Chez moi"
