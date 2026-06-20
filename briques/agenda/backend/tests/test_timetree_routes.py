"""Routes du pont TimeTree, client NON OFFICIEL monkeypatché (jamais de réseau réel).

On appelle les fonctions de route directement avec la session de test, en remplaçant
`timetree_client.list_calendars` / `fetch_events` par des stubs. Vérifie le cycle
connect → select → status → sync (idempotent) → disconnect, et le rejet des creds KO.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.orm import Event
from routers import timetree as R
from services import timetree_client
from vault import get_token_row


USER = {"sub": "perso"}


def _raw(uuid, title="RDV"):
    return {"uuid": uuid, "title": title, "start_at": 1751371200000,
            "end_at": 1751374800000, "all_day": False, "note": None,
            "location": None, "type": 0, "category": 1}


@pytest.mark.asyncio
async def test_cycle_complet(db, monkeypatch):
    monkeypatch.setattr(timetree_client, "list_calendars",
                        lambda email, password: [{"id": "111", "name": "Famille"}])
    monkeypatch.setattr(timetree_client, "fetch",
                        lambda email, password, cal: {
                            "events": [_raw("a"), _raw("b", "Médecin")],
                            "labels": {}})

    # connect → range les creds chiffrés + renvoie les calendriers
    r = await R.timetree_connect(R.ConnectBody(email="me@x.fr", password="secret"), db=db, user=USER)
    assert r["connected"] is True and r["calendars"][0]["name"] == "Famille"
    row = await get_token_row(db, "perso", "timetree")
    assert row is not None and row.scope is None          # pas encore de calendrier choisi

    # select → fixe le calendrier
    await R.timetree_select(R.SelectBody(calendar_id="111"), db=db, user=USER)
    assert (await R.timetree_status(db=db, user=USER)) == {"connected": True, "calendar_id": "111"}

    # sync → importe (idempotent)
    s1 = await R.timetree_sync(db=db, user=USER)
    assert s1["created"] == 2 and s1["fetched"] == 2
    s2 = await R.timetree_sync(db=db, user=USER)
    assert s2["created"] == 0 and s2["updated"] == 2
    evts = (await db.execute(select(Event).where(Event.source == "timetree"))).scalars().all()
    assert len(evts) == 2

    # disconnect → purge
    assert (await R.timetree_disconnect(db=db, user=USER))["disconnected"] is True
    assert (await R.timetree_status(db=db, user=USER)) == {"connected": False}


@pytest.mark.asyncio
async def test_connect_identifiants_invalides(db, monkeypatch):
    def _boom(email, password):
        raise timetree_client.TimeTreeAuthError("Email ou mot de passe TimeTree invalide")
    monkeypatch.setattr(timetree_client, "list_calendars", _boom)
    with pytest.raises(HTTPException) as exc:
        await R.timetree_connect(R.ConnectBody(email="x", password="y"), db=db, user=USER)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_sync_sans_calendrier(db, monkeypatch):
    monkeypatch.setattr(timetree_client, "list_calendars",
                        lambda email, password: [{"id": "1", "name": "A"}])
    await R.timetree_connect(R.ConnectBody(email="me@x.fr", password="secret"), db=db, user=USER)
    with pytest.raises(HTTPException) as exc:       # connecté mais aucun calendrier sélectionné
        await R.timetree_sync(db=db, user=USER)
    assert exc.value.status_code == 400
