"""Script one-off (S172) : relie un compte Keycloak réel aux calendriers "perso"."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from lier_compte_perso import lier_compte_perso
from models.orm import Calendar, CalendarMember


async def _cal(db, user_id="perso", name="Perso") -> Calendar:
    cal = Calendar(user_id=user_id, name=name, is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_lie_uniquement_les_calendriers_perso(db):
    perso = await _cal(db, user_id="perso", name="Perso")
    autre = await _cal(db, user_id="quelqu-un-d-autre", name="PasMoi")

    lies = await lier_compte_perso("mon-sub-reel", db)

    assert lies == [perso.id]
    membres = (await db.execute(select(CalendarMember))).scalars().all()
    assert len(membres) == 1
    assert membres[0].calendar_id == perso.id
    assert membres[0].user_id == "mon-sub-reel"
    assert membres[0].role == "owner"


@pytest.mark.asyncio
async def test_idempotent(db):
    perso = await _cal(db, user_id="perso", name="Perso")

    premier = await lier_compte_perso("mon-sub-reel", db)
    second = await lier_compte_perso("mon-sub-reel", db)

    assert premier == [perso.id]
    assert second == []  # déjà lié, rien à refaire
    membres = (await db.execute(select(CalendarMember))).scalars().all()
    assert len(membres) == 1  # pas de doublon
