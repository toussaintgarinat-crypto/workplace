"""S174 — profils : résolution nom + couleur (défauts), upsert, endpoints."""

from __future__ import annotations

import pytest

from config import settings
from models.orm import UserProfile
from routers import profiles as R
from services import profils


def test_couleur_pour_est_deterministe():
    c1 = profils.couleur_pour("marina")
    assert c1 == profils.couleur_pour("marina")  # stable
    assert c1 in profils.PALETTE


def test_nom_affiche_defauts():
    settings.AGENDA_USER_ID = "perso"
    assert profils.nom_affiche("perso", None) == "Toi"       # propriétaire local
    assert profils.nom_affiche("marina", None) == "marina"   # inconnu → id brut
    p = UserProfile(user_id="marina", display_name="Marina", avatar_color="#ec4899")
    assert profils.nom_affiche("marina", p) == "Marina"      # profil connu


@pytest.mark.asyncio
async def test_upsert_cree_puis_met_a_jour(db):
    p = await profils.upsert(db, "marina", "Marina")
    assert p.display_name == "Marina" and p.avatar_color in profils.PALETTE
    p2 = await profils.upsert(db, "marina", "Marina D.")
    assert p2.display_name == "Marina D."  # même ligne, nom mis à jour


@pytest.mark.asyncio
async def test_resoudre_melange_connus_et_inconnus(db):
    await profils.upsert(db, "marina", "Marina")
    res = await profils.resoudre(db, ["marina", "perso"])
    assert res["marina"]["display_name"] == "Marina"
    assert res["perso"]["display_name"] == "Toi"  # défaut propriétaire


@pytest.mark.asyncio
async def test_post_profiles_me_depuis_claims(db):
    out = await R.upsert_me(db=db, user={"sub": "marina", "name": "Marina",
                                         "preferred_username": "marina_d"})
    assert out.display_name == "Marina" and out.user_id == "marina"


@pytest.mark.asyncio
async def test_post_profiles_me_repli_username(db):
    out = await R.upsert_me(db=db, user={"sub": "x", "preferred_username": "xx"})
    assert out.display_name == "xx"  # pas de `name` → preferred_username


@pytest.mark.asyncio
async def test_get_profiles_liste(db):
    await profils.upsert(db, "marina", "Marina")
    out = await R.list_profiles(user_ids="marina,perso", db=db,
                                user={"sub": "perso"})
    noms = {p.user_id: p.display_name for p in out}
    assert noms == {"marina": "Marina", "perso": "Toi"}
