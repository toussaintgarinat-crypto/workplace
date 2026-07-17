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


@pytest.mark.asyncio
async def test_live_position_latlon_chiffres(db):
    from datetime import datetime, timedelta
    from models.orm import LivePosition

    db.add(LivePosition(user_id="perso", latitude=48.8566, longitude=2.3522,
                        scope="famille",
                        expires_at=datetime.utcnow() + timedelta(minutes=30)))
    await db.commit()
    db.expire_all()

    pos = (await db.execute(
        select(LivePosition).where(LivePosition.user_id == "perso"))).scalar_one()
    assert pos.latitude == 48.8566 and pos.longitude == 2.3522   # transparent, float

    brut = (await db.execute(
        text("SELECT latitude FROM live_positions WHERE user_id='perso'"))).one()
    assert "48.8566" not in str(brut[0])       # illisible en base
    assert float(crypto.dechiffrer(brut[0])) == 48.8566


@pytest.mark.asyncio
async def test_profil_email_chiffre(db):
    from models.orm import UserProfile
    db.add(UserProfile(user_id="perso", display_name="Papa",
                       email="papa@example.com"))
    await db.commit()
    db.expire_all()
    prof = (await db.execute(
        select(UserProfile).where(UserProfile.user_id == "perso"))).scalar_one()
    assert prof.email == "papa@example.com"
    brut = (await db.execute(
        text("SELECT email FROM user_profiles WHERE user_id='perso'"))).one()
    assert "papa@example.com" not in brut[0]


@pytest.mark.asyncio
async def test_loyalty_numero_chiffre(db):
    from models.orm import LoyaltyCard
    db.add(LoyaltyCard(id="l1", user_id="perso", enseigne="Carrefour",
                       numero="9876543210123", note="carte de Marina"))
    await db.commit()
    db.expire_all()
    brut = (await db.execute(
        text("SELECT enseigne, numero FROM loyalty_cards WHERE id='l1'"))).one()
    assert brut[0] == "Carrefour"              # enseigne EN CLAIR (triée)
    assert "9876543210123" not in brut[1]      # numero chiffré
    assert crypto.dechiffrer(brut[1]) == "9876543210123"


@pytest.mark.asyncio
async def test_activity_log_details_json_chiffre(db):
    from models.orm import EventActivityLog
    db.add(EventActivityLog(id="a1", event_id="zz", user_id="perso",
                            user_nom="Papa", action="update",
                            details={"champ": "titre", "avant": "A", "apres": "B"}))
    await db.commit()
    db.expire_all()
    log = (await db.execute(
        select(EventActivityLog).where(EventActivityLog.id == "a1"))).scalar_one()
    assert log.details == {"champ": "titre", "avant": "A", "apres": "B"}
    assert log.user_nom == "Papa"
    brut = (await db.execute(
        text("SELECT user_nom, details FROM event_activity_log WHERE id='a1'"))).one()
    assert brut[0] != "Papa"
    assert "titre" not in brut[1]
