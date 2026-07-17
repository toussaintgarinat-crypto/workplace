"""S180 — les colonnes sensibles sont chiffrées en base mais transparentes via l'ORM."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from models.orm import Calendar, Event, EventComment
import crypto


@pytest.mark.asyncio
async def test_event_title_location_chiffres(db):
    cal = Calendar(id="c1", user_id="perso", name="Fam")
    db.add(cal)
    db.add(Event(id="e1", calendar_id="c1", title="Coloscopie papa",
                 description="clinique St-Jean", location="12 rue Verte",
                 start_at=__import__("datetime").datetime(2026, 8, 1, 9),
                 end_at=__import__("datetime").datetime(2026, 8, 1, 10),
                 created_by="perso"))
    await db.commit()
    db.expire_all()

    ev = (await db.execute(select(Event).where(Event.id == "e1"))).scalar_one()
    assert ev.title == "Coloscopie papa"      # transparent
    assert ev.location == "12 rue Verte"

    brut = (await db.execute(
        text("SELECT title, location FROM events WHERE id='e1'"))).one()
    assert "Coloscopie" not in brut[0]         # illisible en base
    assert crypto.dechiffrer(brut[0]) == "Coloscopie papa"


@pytest.mark.asyncio
async def test_comment_content_chiffre(db):
    db.add(Calendar(id="c2", user_id="perso", name="Fam"))
    db.add(Event(id="e2", calendar_id="c2", title="x",
                 start_at=__import__("datetime").datetime(2026, 8, 1, 9),
                 end_at=__import__("datetime").datetime(2026, 8, 1, 10),
                 created_by="perso"))
    db.add(EventComment(id="k1", event_id="e2", user_id="perso",
                        content="j'apporte le gâteau"))
    await db.commit()
    db.expire_all()

    brut = (await db.execute(
        text("SELECT content FROM event_comments WHERE id='k1'"))).one()
    assert "gâteau" not in brut[0]
    assert crypto.dechiffrer(brut[0]) == "j'apporte le gâteau"
