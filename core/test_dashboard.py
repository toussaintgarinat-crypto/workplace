"""Tests du dashboard du Cœur — onglet « Créations » (Hub des briques créatives).

Le Hub Créations a migré d'Oria vers le Cœur : le dashboard sert désormais le Studio
(brique 6060) et l'atelier Personnages (5900) en iframe. On vérifie que l'onglet existe
et que les URLs des briques sont bien INJECTÉES au service (placeholders remplacés).
"""

import os

# Secrets requis AVANT l'import du Cœur (main importe le coffre, la Gateway, etc.).
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_dashboard_repond():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_onglet_creations_present():
    html = client.get("/dashboard").text
    assert 'data-vue="creations"' in html
    assert "vue-creations" in html


def test_urls_briques_injectees():
    """Les placeholders __STUDIO_UI_URL__ / __PERSONNAGES_UI_URL__ doivent être remplacés."""
    html = client.get("/dashboard").text
    assert "__STUDIO_UI_URL__" not in html
    assert "__PERSONNAGES_UI_URL__" not in html
    # Valeurs par défaut (usage perso) injectées dans les onclick des tuiles.
    assert "localhost:6060/atelier" in html
    assert "localhost:5900/atelier" in html


def test_url_studio_surchargeable_par_env(monkeypatch):
    """L'URL du Studio est paramétrable (déploiement) et bien réinjectée."""
    monkeypatch.setattr(main, "STUDIO_UI_URL", "https://studio.exemple.test/atelier")
    monkeypatch.setattr(main, "STUDIO_KEY", "")
    html = client.get("/dashboard").text
    assert "https://studio.exemple.test/atelier" in html


def test_cle_studio_injectee_dans_iframe(monkeypatch):
    """Avec un compte Studio (STUDIO_KEY), l'iframe transporte la clé en ?api_key=."""
    monkeypatch.setattr(main, "STUDIO_UI_URL", "http://localhost:6060/atelier")
    monkeypatch.setattr(main, "STUDIO_KEY", "cle-de-service-123")
    html = client.get("/dashboard").text
    assert "http://localhost:6060/atelier?api_key=cle-de-service-123" in html


def test_sans_cle_pas_dapi_key(monkeypatch):
    """Sans compte Studio, l'URL de l'iframe reste nue (aucune fuite ?api_key=)."""
    monkeypatch.setattr(main, "STUDIO_UI_URL", "http://localhost:6060/atelier")
    monkeypatch.setattr(main, "STUDIO_KEY", "")
    html = client.get("/dashboard").text
    assert "api_key=" not in html
