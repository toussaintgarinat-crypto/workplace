"""S177 — surface /service sondage_* (contrat français piloté par le Cœur)."""
from __future__ import annotations

from datetime import datetime

import pytest
from starlette.requests import Request

from routers import service as S
from routers.service import ServiceSondageCreate, ServiceSondageFinalize, _CreneauServiceIn

USER = {"sub": "perso"}


def _req() -> Request:
    return Request({"type": "http", "headers": [], "scheme": "http",
                    "server": ("agenda", 8400), "path": "/service/polls", "query_string": b""})


@pytest.mark.asyncio
async def test_creer_puis_consulter_sondage(db):
    corps = ServiceSondageCreate(
        titre="Réunion", lieu="Visio",
        creneaux=[_CreneauServiceIn(debut=datetime(2026, 9, 1, 10), fin=datetime(2026, 9, 1, 11)),
                  _CreneauServiceIn(debut=datetime(2026, 9, 2, 10), fin=datetime(2026, 9, 2, 11))])
    out = await S.service_creer_sondage(corps, _req(), db=db, user=USER)
    assert out["id"] and out["share_token"]
    assert out["lien"].endswith("/polls/p/" + out["share_token"])

    liste = await S.service_lister_sondages(db=db, user=USER)
    assert liste[0]["titre"] == "Réunion" and liste[0]["nb_creneaux"] == 2


@pytest.mark.asyncio
async def test_finaliser_sondage_cree_event(db):
    corps = ServiceSondageCreate(
        titre="Réunion",
        creneaux=[_CreneauServiceIn(debut=datetime(2026, 9, 1, 10), fin=datetime(2026, 9, 1, 11))])
    out = await S.service_creer_sondage(corps, _req(), db=db, user=USER)
    detail = await __import__("routers.polls", fromlist=["get_poll"]).get_poll(
        out["id"], db=db, user=USER)
    creneau_id = detail.slots[0].id
    res = await S.service_finaliser_sondage(
        out["id"], ServiceSondageFinalize(creneau_id=creneau_id), db=db, user=USER)
    assert res["event_id"] and res["slot_id"] == creneau_id
