"""Tests de personnages_client.py — aucun appel réseau réel (respx intercepte tout)."""
import json

import httpx
import pytest
import respx

import personnages_client as pc


@respx.mock
@pytest.mark.asyncio
async def test_portrait_appelle_la_bonne_url_avec_la_fiche():
    route = respx.post(f"{pc.PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    fiche = {"prenoms": "Aria", "date_naissance": "1990-09-05"}
    r = await pc.portrait(fiche)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert json.loads(route.calls.last.request.content) == fiche


@respx.mock
@pytest.mark.asyncio
async def test_portrait_injoignable_leve_personnages_indisponible():
    respx.post(f"{pc.PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=httpx.ConnectError("connexion refusée"))
    with pytest.raises(pc.PersonnagesIndisponible):
        await pc.portrait({"date_naissance": "1990-09-05"})


@respx.mock
@pytest.mark.asyncio
async def test_recherche_inverse_appelle_la_bonne_url():
    route = respx.post(f"{pc.PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": []}))
    r = await pc.recherche_inverse("description de test")
    assert r.status_code == 200
    assert route.called
    envoye = json.loads(route.calls.last.request.content)
    assert envoye == {"description": "description de test", "combien": 1}
