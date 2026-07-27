"""Tests — front de l'atelier-veille servi PAR la brique (motif studio/test_front.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_racine_sert_le_front_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Atelier Veille</title>" in r.text


def test_alias_atelier_sert_le_meme_front():
    assert client.get("/atelier").text == client.get("/").text


def test_workplace_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_front_branche_la_carte_sur_config():
    html = client.get("/").text
    # Depuis 822ede1, les appels fetch sont préfixés par API_BASE en template
    # literal (`${API_BASE}/config`) au lieu de quotes simples/doubles.
    # On accepte les deux formes pour ne pas re-casser ce test au prochain
    # changement de style d'appel.
    assert (
        "fetch('/config'" in html
        or 'fetch("/config"' in html
        or "fetch(`${API_BASE}/config`" in html
    )
    assert "geo-iframe" in html


def test_front_couvre_la_gestion_des_sources():
    html = client.get("/").text
    for marqueur in ("chargerSources", "ajouterSource", "supprimerSource",
                     "/veille/sources"):
        assert marqueur in html


def test_front_couvre_les_digests_et_laudio():
    html = client.get("/").text
    for marqueur in ("chargerDigests", "genererDigest", "/veille/digests",
                     "/veille/digest/executer", "<audio"):
        assert marqueur in html


def test_front_avertit_que_la_generation_est_pour_tout_le_foyer():
    html = client.get("/").text
    assert "foyer" in html.lower()
