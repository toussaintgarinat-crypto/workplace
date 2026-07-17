"""Digest quotidien/hebdo (S178) — `POST /digests/executer` : sélection des profils,
idempotence par (user, jour), heures calmes, push (connexion) + email (mail 6030).

On appelle la fonction de route DIRECTEMENT, comme test_push_appareils.py /
test_service_agenda.py — pas de TestClient. Le mock du POST sortant `/pousser` suit
respx (déjà utilisé côté monorepo pour les appels HTTP sortants mockés)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import respx
from fastapi import HTTPException
from httpx import Response
from zoneinfo import ZoneInfo

from config import settings
from models.orm import Calendar, Event, UserProfile
from routers import digests
from services.horaires import vers_utc_naif

PARIS = ZoneInfo("Europe/Paris")


async def _seed_quotidien(db, user_id="marina", titre="Dentiste",
                          digest_push=True, digest_email=False,
                          email=None, heures_calmes=None):
    """Sème un calendrier possédé par `user_id` + un event AUJOURD'HUI (dans la fenêtre
    du digest quotidien) + un UserProfile en cadence quotidienne."""
    cal = Calendar(user_id=user_id, name="Perso", color="#111111")
    db.add(cal)
    await db.flush()

    debut = vers_utc_naif(datetime.now(PARIS))  # « maintenant », converti à la convention de stockage
    evt = Event(calendar_id=cal.id, title=titre, start_at=debut,
                end_at=debut + timedelta(hours=1), created_by=user_id, rappels=[])
    db.add(evt)

    prof = UserProfile(user_id=user_id, display_name="Marina", email=email,
                       digest_cadence="quotidien", digest_push=digest_push,
                       digest_email=digest_email, heures_calmes=heures_calmes)
    db.add(prof)
    await db.commit()
    return cal, evt, prof


# ── Garde (clé) ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executer_sans_cle_digest_configuree_renvoie_503(db, monkeypatch):
    monkeypatch.setattr(settings, "DIGEST_KEY", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        await digests.executer(x_api_key=None, db=db)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_executer_mauvaise_cle_renvoie_403(db, monkeypatch):
    monkeypatch.setattr(settings, "DIGEST_KEY", "dk", raising=False)
    with pytest.raises(HTTPException) as exc:
        await digests.executer(x_api_key="mauvaise-cle", db=db)
    assert exc.value.status_code == 403


# ── Trop tôt (avant DIGEST_HEURE) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executer_avant_lheure_configuree_est_un_noop(db, monkeypatch):
    monkeypatch.setattr(settings, "DIGEST_KEY", "dk", raising=False)
    monkeypatch.setattr(settings, "DIGEST_HEURE", 23, raising=False)  # jamais atteint en test
    out = await digests.executer(x_api_key="dk", db=db)
    assert out == {"traites": 0, "envoyes_push": 0, "envoyes_email": 0}


# ── Flux complet : push + idempotence ───────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_executer_pousse_et_marque_idempotent(db, monkeypatch):
    monkeypatch.setattr(settings, "DIGEST_KEY", "dk", raising=False)
    monkeypatch.setattr(settings, "DIGEST_HEURE", 0, raising=False)     # toujours l'heure en test
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion", raising=False)
    monkeypatch.setattr(settings, "CONNEXION_KEY", "", raising=False)

    await _seed_quotidien(db, titre="Dentiste")

    pousser = respx.post("http://connexion/pousser").mock(return_value=Response(200, json={"ok": True}))

    out1 = await digests.executer(x_api_key="dk", db=db)
    assert out1["traites"] >= 1
    assert out1["envoyes_push"] >= 1
    assert pousser.call_count >= 1

    # Preuve que la fenêtre/_events_fenetre est correcte : le texte poussé porte
    # bien le titre de l'event seedé, pas juste « quelque chose ».
    import json
    dernier_appel = pousser.calls.last.request.content
    assert "Dentiste" in json.loads(dernier_appel)["texte"]

    n = pousser.call_count
    out2 = await digests.executer(x_api_key="dk", db=db)   # 2e exécution, même jour
    assert out2["traites"] == 0
    assert pousser.call_count == n   # idempotent : rien de re-poussé


# ── Heures calmes ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_executer_respecte_les_heures_calmes(db, monkeypatch):
    monkeypatch.setattr(settings, "DIGEST_KEY", "dk", raising=False)
    monkeypatch.setattr(settings, "DIGEST_HEURE", 0, raising=False)
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion", raising=False)
    monkeypatch.setattr(settings, "CONNEXION_KEY", "", raising=False)

    # Plage couvrant toute la journée (sauf la dernière minute) : « maintenant » y
    # tombe toujours pendant le test, quelle que soit l'heure d'exécution du run.
    await _seed_quotidien(db, titre="Dentiste", heures_calmes="00:00-23:59")

    pousser = respx.post("http://connexion/pousser").mock(return_value=Response(200, json={"ok": True}))

    out = await digests.executer(x_api_key="dk", db=db)
    assert out == {"traites": 0, "envoyes_push": 0, "envoyes_email": 0}
    assert pousser.call_count == 0
