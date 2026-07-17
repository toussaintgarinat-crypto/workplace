"""S179 — la table live_positions et la colonne ics_token existent et fonctionnent."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_live_position_upsert_une_ligne_par_personne(db):
    from models.orm import LivePosition

    p = LivePosition(user_id="alice", latitude=48.85, longitude=2.35,
                     scope="famille", expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(p)
    await db.commit()

    rows = (await db.execute(select(LivePosition))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == "alice"
    assert rows[0].scope == "famille"
    assert rows[0].accuracy_m is None


@pytest.mark.asyncio
async def test_userprofile_a_un_ics_token(db):
    from models.orm import UserProfile

    prof = UserProfile(user_id="alice", display_name="Alice", ics_token="jeton-secret")
    db.add(prof)
    await db.commit()

    got = await db.get(UserProfile, "alice")
    assert got.ics_token == "jeton-secret"
