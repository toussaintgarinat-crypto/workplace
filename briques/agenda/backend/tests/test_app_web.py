"""Smoke test de la page /app (S172) — HTML bien formé, pas de dépendance réseau."""

from __future__ import annotations

import pytest

from routers.app_web import app_page


@pytest.mark.asyncio
async def test_app_page_contient_la_config_keycloak():
    resp = await app_page()
    assert resp.status_code == 200
    corps = resp.body.decode()
    assert "calendar-app" in corps
    assert "<title>" in corps


@pytest.mark.asyncio
async def test_app_page_contient_le_chargement_des_calendriers():
    resp = await app_page()
    corps = resp.body.decode()
    assert "chargerCalendriers" in corps
    assert "/calendars" in corps


@pytest.mark.asyncio
async def test_app_page_contient_la_modale_evenement():
    resp = await app_page()
    corps = resp.body.decode()
    assert "ouvrirModaleEvent" in corps
    assert "enregistrerEvent" in corps
