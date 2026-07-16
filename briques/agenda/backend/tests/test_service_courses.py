"""Surface /service courses : identité perso, création/consultation/ajout/cochage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from routers import service as S

PERSO = {"sub": "perso"}


@pytest.mark.asyncio
async def test_service_cree_et_liste(db):
    liste = await S.service_creer_liste(S.ServiceListeCreate(nom="Maison"), db=db, user=PERSO)
    listes = await S.service_lister_listes(db=db, user=PERSO)
    assert any(l["name"] == "Maison" for l in listes)
    assert liste["created_by"] == "perso"


@pytest.mark.asyncio
async def test_service_ajoute_et_coche_item(db):
    liste = await S.service_creer_liste(S.ServiceListeCreate(nom="Maison"), db=db, user=PERSO)
    it = await S.service_ajouter_item(liste["id"], S.ServiceItemAjout(nom="Lait"), db=db, user=PERSO)
    assert it["name"] == "Lait" and it["checked"] is False
    coche = await S.service_cocher_item(liste["id"], it["id"], S.ServiceItemCoche(checked=True),
                                        db=db, user=PERSO)
    assert coche["checked"] is True


def test_manifest_contient_capacites_courses():
    manifest = json.loads((Path(__file__).resolve().parents[2] / "manifest.json").read_text())
    noms = {c["nom"] for c in manifest["capacites"]}
    assert {"courses_consulter", "courses_creer_liste", "courses_ajouter", "courses_cocher"} <= noms
