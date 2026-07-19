"""Dialecte S2S Workplace (S168) sur `get_current_user`.

Le Cœur pilote l'agenda par le manifest : il envoie `X-API-Key == AGENDA_KEY` +
`X-Compte-Id` (jamais de JWT). On vérifie :
- S182 : si le Cœur forwarde `X-User-Id`, l'identité de calendrier est CET utilisateur
  (chacun son agenda) ; la clé fait le gage de confiance.
- sans `X-User-Id`, repli sur le pin `AGENDA_USER_ID` (« perso ») — jobs de fond /
  synchro OAuth sans session, sinon l'agenda paraîtrait vide et TimeTree/Google déconnectés.
- la clé fait autorité (mauvaise clé → 401), sans casser les dialectes existants (JWT
  désactivé, service token historique).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import auth
from config import settings


@pytest.fixture
def _cle_service(monkeypatch):
    """AGENDA_KEY configurée + AUTH_ENABLED (pour prouver que le dialecte S2S passe
    AVANT la porte JWT), identité pinnée sur « perso »."""
    monkeypatch.setattr(settings, "AGENDA_KEY", "clef-agenda-test", raising=False)
    monkeypatch.setattr(settings, "AGENDA_USER_ID", "perso", raising=False)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    yield


@pytest.mark.asyncio
async def test_cle_valide_pinne_sur_perso(_cle_service):
    # Ce que le Cœur envoie réellement : X-API-Key + X-Compte-Id=admin, pas de JWT.
    u = await auth.get_current_user(token=None, x_user_id=None,
                                    x_api_key="clef-agenda-test", x_compte_id="admin")
    # L'identité de CALENDRIER reste « perso » (les données y sont keyées), pas « admin ».
    assert u["sub"] == "perso"
    assert u["service_call"] is True
    assert u["compte_id"] == "admin"           # tracé comme crochet multi-tenant


@pytest.mark.asyncio
async def test_identite_forwardee_honoree(_cle_service):
    """S182 « chacun son agenda » : le Cœur (détenteur de la clé) forwarde le sub de
    l'utilisateur connecté → l'agenda sert SES données, pas « perso »."""
    u = await auth.get_current_user(token=None, x_user_id="kc-sub-marina",
                                    x_api_key="clef-agenda-test", x_compte_id="admin")
    assert u["sub"] == "kc-sub-marina"
    assert u["service_call"] is True
    assert u["compte_id"] == "admin"


@pytest.mark.asyncio
async def test_identite_forwardee_exige_la_cle(_cle_service):
    """Frontière de sécurité : un X-User-Id SANS la bonne clé n'usurpe rien (401)."""
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(token=None, x_user_id="kc-sub-marina",
                                    x_api_key="mauvaise-clef", x_compte_id="admin")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_cle_invalide_rejetee(_cle_service):
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(token=None, x_user_id=None,
                                    x_api_key="mauvaise-clef", x_compte_id="admin")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_sans_cle_configuree_pas_de_dialecte_s2s(monkeypatch):
    # AGENDA_KEY vide ⇒ un X-API-Key qui traîne ne doit PAS engager le dialecte S2S :
    # on retombe sur le comportement historique (AUTH_ENABLED=False ⇒ X-User-Id).
    monkeypatch.setattr(settings, "AGENDA_KEY", "", raising=False)
    monkeypatch.setattr(settings, "AUTH_ENABLED", False, raising=False)
    u = await auth.get_current_user(token=None, x_user_id="perso",
                                    x_api_key="peu-importe", x_compte_id="admin")
    assert u["sub"] == "perso"
    assert "service_call" not in u


@pytest.mark.asyncio
async def test_service_token_historique_intact(monkeypatch):
    # Rétro-compat : sans X-API-Key, le CALENDAR_SERVICE_TOKEN + X-User-Id marche encore.
    monkeypatch.setattr(settings, "AGENDA_KEY", "clef-agenda-test", raising=False)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CALENDAR_SERVICE_TOKEN", "jeton-s2s-historique", raising=False)
    u = await auth.get_current_user(token="jeton-s2s-historique", x_user_id="perso",
                                    x_api_key=None, x_compte_id=None)
    assert u["sub"] == "perso" and u["service_call"] is True
