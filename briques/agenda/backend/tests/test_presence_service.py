"""S179 — logique présence : upsert (une ligne/personne), purge, portée de visibilité."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from services import presence

FUTUR = datetime.utcnow() + timedelta(hours=1)
PASSE = datetime.utcnow() - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_upsert_remplace_une_seule_ligne(db):
    from models.orm import LivePosition
    from sqlalchemy import select

    await presence.upsert_position(db, "alice", latitude=1.0, longitude=2.0, expires_at=FUTUR)
    await presence.upsert_position(db, "alice", latitude=3.0, longitude=4.0, expires_at=FUTUR)
    rows = (await db.execute(select(LivePosition))).scalars().all()
    assert len(rows) == 1
    assert rows[0].latitude == 3.0


@pytest.mark.asyncio
async def test_positions_visibles_filtre_et_purge_les_expires(db):
    from models.orm import LivePosition
    from sqlalchemy import select

    await presence.upsert_position(db, "vieux", latitude=1.0, longitude=1.0, expires_at=PASSE)
    await presence.upsert_position(db, "alice", latitude=2.0, longitude=2.0, expires_at=FUTUR)
    vis = await presence.positions_visibles(db, "bob")
    ids = {v["user_id"] for v in vis}
    assert ids == {"alice"}  # 'vieux' expiré → absent
    restants = (await db.execute(select(LivePosition))).scalars().all()
    assert {r.user_id for r in restants} == {"alice"}  # purgé de la base


@pytest.mark.asyncio
async def test_portee_event_visible_seulement_des_participants(db):
    from models.orm import Calendar, Event, EventParticipant

    cal = Calendar(user_id="alice", name="Perso")
    db.add(cal)
    await db.flush()
    evt = Event(calendar_id=cal.id, title="RDV", created_by="alice",
                start_at=datetime(2026, 7, 20, 9, 0, 0), end_at=FUTUR)
    db.add(evt)
    await db.flush()
    db.add(EventParticipant(event_id=evt.id, user_id="carol", status="accepted"))
    await db.commit()

    await presence.upsert_position(db, "alice", latitude=1.0, longitude=1.0,
                                   expires_at=FUTUR, scope="event", event_id=evt.id)

    vu_par_carol = {v["user_id"] for v in await presence.positions_visibles(db, "carol")}
    vu_par_dave = {v["user_id"] for v in await presence.positions_visibles(db, "dave")}
    assert "alice" in vu_par_carol       # participant → voit
    assert "alice" not in vu_par_dave    # non-participant → ne voit pas


@pytest.mark.asyncio
async def test_position_enrichie_du_profil(db):
    from services import profils

    await profils.upsert(db, "alice", "Alice", avatar_color="#123456")
    await presence.upsert_position(db, "alice", latitude=1.0, longitude=2.0, expires_at=FUTUR)
    vis = await presence.positions_visibles(db, "bob")
    assert vis[0]["display_name"] == "Alice"
    assert vis[0]["avatar_color"] == "#123456"


@pytest.mark.asyncio
async def test_supprimer_position(db):
    await presence.upsert_position(db, "alice", latitude=1.0, longitude=2.0, expires_at=FUTUR)
    await presence.supprimer_position(db, "alice")
    assert await presence.positions_visibles(db, "alice") == []
