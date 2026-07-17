"""S179 — surface /service : consultation présence + lien webcal (identité pinnée perso)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from routers import service as S

PERSO = {"sub": "perso"}


class _Req:
    base_url = "http://agenda.local/"


@pytest.mark.asyncio
async def test_service_presence_consulter(db):
    from services import presence
    await presence.upsert_position(db, "perso", latitude=1.0, longitude=2.0,
                                   expires_at=datetime.utcnow() + timedelta(hours=1))
    out = await S.service_presence_consulter(db=db, user=PERSO)
    assert any(p["user_id"] == "perso" for p in out)


@pytest.mark.asyncio
async def test_service_ics_lien(db):
    out = await S.service_ics_lien(request=_Req(), db=db, user=PERSO)
    assert out["token"]
    assert out["webcal"].startswith("webcal://")
    assert out["webcal"].endswith(f"/ics/{out['token']}.ics")


def test_manifest_v140_contient_les_capacites():
    manifest = json.loads((Path(__file__).resolve().parents[2] / "manifest.json").read_text())
    assert manifest["version"] == "1.4.0"
    noms = {c["nom"] for c in manifest["capacites"]}
    assert {"presence_consulter", "ics_lien"} <= noms
