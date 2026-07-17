"""S178 — profils : semis de l'email depuis les claims + défauts push/digest."""

from __future__ import annotations

import pytest

from routers import profiles as R
from services import profils


@pytest.mark.asyncio
async def test_upsert_seme_email_et_defauts(db):
    p = await profils.upsert(db, "marina", "Marina", email="marina@example.org")
    assert p.email == "marina@example.org"
    assert p.digest_cadence == "off"
    assert p.digest_push is True and p.digest_email is False
    assert p.heures_calmes is None
    assert p.dernier_digest_quotidien is None
    assert p.dernier_digest_hebdo is None


@pytest.mark.asyncio
async def test_upsert_sans_email_laisse_email_absent(db):
    p = await profils.upsert(db, "perso", "Perso")
    assert p.email is None


@pytest.mark.asyncio
async def test_upsert_ne_vide_pas_email_existant(db):
    await profils.upsert(db, "marina", "Marina", email="marina@example.org")
    p2 = await profils.upsert(db, "marina", "Marina D.")
    assert p2.email == "marina@example.org"  # email non fourni → conservé


@pytest.mark.asyncio
async def test_post_profiles_me_seme_email_depuis_claims(db):
    out = await R.upsert_me(db=db, user={"sub": "marina", "name": "Marina",
                                         "email": "marina@example.org"})
    assert out.email == "marina@example.org"
