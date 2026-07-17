"""S178 — profils : semis de l'email depuis les claims + défauts push/digest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import NotifPrefsEntree
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


# ── C7 : PATCH /profiles/me/notifs (préférences digest) ────────────────────────

@pytest.mark.asyncio
async def test_patch_notifs(db):
    await profils.upsert(db, "marina", "Marina", email="marina@example.org")
    body = await R.patch_notifs(
        NotifPrefsEntree(digest_cadence="hebdo", digest_email=True,
                         heures_calmes="22:00-07:00"),
        db=db, user={"sub": "marina"},
    )
    assert body["digest_cadence"] == "hebdo"
    assert body["digest_email"] is True
    assert body["heures_calmes"] == "22:00-07:00"


@pytest.mark.asyncio
async def test_patch_notifs_cree_le_profil_si_absent(db):
    """Aucun profil pour cet utilisateur → la route le crée via profils.upsert."""
    body = await R.patch_notifs(
        NotifPrefsEntree(digest_cadence="quotidien"),
        db=db, user={"sub": "perso", "name": "Perso"},
    )
    assert body["digest_cadence"] == "quotidien"


def test_notif_prefs_cadence_invalide():
    with pytest.raises(ValidationError):
        NotifPrefsEntree(digest_cadence="toujours")
