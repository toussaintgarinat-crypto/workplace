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
