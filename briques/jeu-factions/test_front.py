import pytest
from fastapi.testclient import TestClient

import jeton
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _vider_cookies_client():
    """`GET /` pose un cookie (Set-Cookie) que le client de test persiste automatiquement
    entre appels (httpx.Client._merge_cookies) — sans ça, un test qui pose un cookie valide
    ferait passer à tort le test suivant qui vérifie l'ABSENCE de cookie."""
    client.cookies.clear()
    yield


def _jeton_url(identite: str) -> str:
    return f"?j={jeton.emettre(identite, ttl=60)}"


def test_accueil_sert_le_html_avec_un_jeton_valide():
    r = client.get("/" + _jeton_url("front-tenant-1"))
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_accueil_refuse_sans_jeton_ni_cookie():
    r = client.get("/")
    assert r.status_code == 401
    assert "text/html" in r.headers["content-type"]


def test_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200


def test_front_contient_le_heartbeat_de_presence():
    r = client.get("/" + _jeton_url("front-tenant-2"))
    assert "/presence" in r.text


def test_front_ne_contient_plus_de_cle_api_localstorage():
    r = client.get("/" + _jeton_url("front-tenant-3"))
    assert "localStorage" not in r.text
    assert "jeu_factions_cle" not in r.text
    assert "X-API-Key" not in r.text


def test_front_gere_une_session_expiree():
    r = client.get("/" + _jeton_url("front-tenant-4"))
    assert "Session expirée" in r.text
