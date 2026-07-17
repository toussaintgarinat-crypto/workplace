"""S179 — abonnement webcal : jeton (idempotent/révocable) + flux .ics par capacité."""
from __future__ import annotations

from datetime import datetime

import pytest

from routers import ics as R
from services import abonnement


async def _cal_avec_event(db, user_id):
    from models.orm import Calendar, Event
    cal = Calendar(user_id=user_id, name="Perso")
    db.add(cal)
    await db.flush()
    db.add(Event(calendar_id=cal.id, title="Dîner", created_by=user_id,
                 start_at=datetime(2026, 7, 20, 19, 0, 0),
                 end_at=datetime(2026, 7, 20, 21, 0, 0)))
    await db.commit()
    return cal


@pytest.mark.asyncio
async def test_token_idempotent(db):
    t1 = await abonnement.obtenir_ou_creer_token(db, "alice")
    t2 = await abonnement.obtenir_ou_creer_token(db, "alice")
    assert t1 and t1 == t2


@pytest.mark.asyncio
async def test_regenerer_revoque_lancien(db):
    t1 = await abonnement.obtenir_ou_creer_token(db, "alice")
    t2 = await abonnement.regenerer_token(db, "alice")
    assert t2 != t1
    assert await abonnement.user_pour_token(db, t1) is None
    assert await abonnement.user_pour_token(db, t2) == "alice"


def test_url_webcal_remplace_le_schema():
    assert abonnement.url_webcal("https://agenda.example.com", "AAA") == \
        "webcal://agenda.example.com/ics/AAA.ics"
    assert abonnement.url_https("https://agenda.example.com/", "AAA") == \
        "https://agenda.example.com/ics/AAA.ics"


@pytest.mark.asyncio
async def test_flux_token_inconnu_404(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await R.flux(token="nexistepas", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flux_ne_contient_que_les_events_visibles(db):
    await _cal_avec_event(db, "alice")
    # Un event d'un AUTRE utilisateur (calendrier non partagé) ne doit pas fuiter.
    await _cal_avec_event(db, "bob")
    token = await abonnement.obtenir_ou_creer_token(db, "alice")
    resp = await R.flux(token=token, db=db)
    corps = resp.body.decode("utf-8")
    assert resp.media_type.startswith("text/calendar")
    assert corps.count("BEGIN:VEVENT") == 1
    assert "SUMMARY:Dîner" in corps
