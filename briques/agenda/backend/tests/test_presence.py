"""S179 — routeur présence : sub forcé (anti-usurpation), portée event gardée, TTL famille."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from routers import presence as R
from routers.presence import PresenceEntree


@pytest.mark.asyncio
async def test_partage_famille_ttl_defaut(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    out = await R.partager(PresenceEntree(lat=48.85, lon=2.35), db=db, user={"sub": "alice"})
    assert out["ok"] is True
    vis = await R.lister(db=db, user={"sub": "bob"})
    assert vis[0]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_partage_force_le_sub_ignore_le_corps(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    # Un user_id PIRATE injecté dans le corps est ignoré (extra='ignore' par défaut).
    body = PresenceEntree.model_validate({"lat": 1.0, "lon": 2.0, "user_id": "PIRATE"})
    assert not hasattr(body, "user_id")
    await R.partager(body, db=db, user={"sub": "alice"})
    vis = await R.lister(db=db, user={"sub": "alice"})
    assert {v["user_id"] for v in vis} == {"alice"}
    assert "PIRATE" not in str(vis)


@pytest.mark.asyncio
async def test_partage_event_exige_participation(db, monkeypatch):
    from models.orm import Calendar, Event

    monkeypatch.setattr(R, "publish_presence_change", _noop)
    cal = Calendar(user_id="owner", name="Perso")
    db.add(cal)
    await db.flush()
    evt = Event(calendar_id=cal.id, title="RDV", created_by="owner",
                start_at=datetime(2026, 7, 20, 9, 0, 0),
                end_at=datetime.utcnow() + timedelta(hours=2))
    db.add(evt)
    await db.commit()

    with pytest.raises(HTTPException) as exc:  # non-participant → 403
        await R.partager(PresenceEntree(lat=1.0, lon=2.0, scope="event", event_id=evt.id),
                         db=db, user={"sub": "intrus"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_partage_event_inconnu_404(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    with pytest.raises(HTTPException) as exc:
        await R.partager(PresenceEntree(lat=1.0, lon=2.0, scope="event", event_id="nope"),
                         db=db, user={"sub": "alice"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_arreter_supprime(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    await R.partager(PresenceEntree(lat=1.0, lon=2.0), db=db, user={"sub": "alice"})
    await R.arreter(db=db, user={"sub": "alice"})
    assert await R.lister(db=db, user={"sub": "alice"}) == []


async def _noop(*a, **k):
    return None
