"""Tests — front de l'atelier-images-video servi PAR la brique (motif atelier-veille/
test_front.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_racine_sert_le_front_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Atelier Images & Vidéo</title>" in r.text


def test_alias_atelier_sert_le_meme_front():
    assert client.get("/atelier").text == client.get("/").text


def test_workplace_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_front_utilise_le_prefixe_api_base_du_proxy_coeur():
    html = client.get("/").text
    assert "window.ATELIER_IV_API_BASE" in html
    assert "const API_BASE = window.ATELIER_IV_API_BASE || '';" in html


def test_front_couvre_la_generation_libre():
    html = client.get("/").text
    for marqueur in ("genererImage", "genererVideo", "/images/generer", "/video/generer",
                     "chargerFournisseurs"):
        assert marqueur in html


def test_front_couvre_les_synergies_studio():
    html = client.get("/").text
    for marqueur in ("chargerSeries", "genererPortrait", "genererAnimation",
                     "genererCouverture", "genererTeaser", "/studio/series"):
        assert marqueur in html


def test_front_couvre_la_galerie():
    html = client.get("/").text
    for marqueur in ("chargerGalerie", "ajouterGalerie", "supprimerGalerie", "/galerie"):
        assert marqueur in html


def test_front_couvre_les_presets_localstorage():
    html = client.get("/").text
    for marqueur in ("sauverPreset", "chargerPreset", "localStorage", "atelier_iv_presets_"):
        assert marqueur in html
