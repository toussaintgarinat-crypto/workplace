"""Tests API de la brique atelier-veille : config + composition (voir aussi
test_composition.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_config_derive_lurl_geo_de_lhote_de_la_requete():
    """Sans surcharge, /config construit l'URL de la carte depuis le scheme + l'hôte
    DE LA REQUÊTE (S128) — pas une valeur figée qui casserait hors localhost."""
    r = client.get("/config", headers={"host": "192.168.1.89:6130"})
    assert r.status_code == 200
    assert r.json()["geo_url"] == "http://192.168.1.89:6110/"


def test_config_derive_lurl_geo_en_localhost_par_defaut():
    r = client.get("/config")
    assert r.json()["geo_url"] == "http://testserver:6110/"


def test_config_respecte_la_surcharge_env(monkeypatch):
    monkeypatch.setenv("GEO_PUBLIC_URL", "https://mesh.example/geo/")
    import importlib
    importlib.reload(main)
    r = TestClient(main.app).get("/config")
    assert r.json()["geo_url"] == "https://mesh.example/geo/"
