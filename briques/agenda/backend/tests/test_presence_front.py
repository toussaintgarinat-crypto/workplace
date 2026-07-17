"""S179 — la page /app expose l'onglet Présence, charge Leaflet et montre le bloc webcal."""
from __future__ import annotations

from pathlib import Path

from templates_app import page_app

HTML = page_app("https://kc.local", "oria", "calendar-app")


def test_assets_leaflet_copies():
    base = Path(__file__).resolve().parents[1] / "static"
    for f in ("leaflet.js", "leaflet.css", "leaflet.markercluster.js"):
        assert (base / f).exists(), f"asset manquant : {f}"


def test_onglet_presence_present():
    assert 'data-vue="presence"' in HTML
    assert "📍" in HTML


def test_charge_leaflet_et_bloc_webcal():
    assert "/static/leaflet.js" in HTML
    assert "/static/leaflet.css" in HTML
    assert "Abonnement" in HTML  # bloc webcal dans Réglages
