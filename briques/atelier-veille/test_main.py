"""Tests API de la brique atelier-veille : config + composition (voir aussi
test_composition.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_config_renvoie_url_geo_par_defaut():
    r = client.get("/config")
    assert r.status_code == 200
    assert r.json()["geo_url"] == "http://localhost:6110/"


def test_config_respecte_la_surcharge_env(monkeypatch):
    monkeypatch.setenv("GEO_PUBLIC_URL", "https://mesh.example/geo/")
    import importlib
    importlib.reload(main)
    r = TestClient(main.app).get("/config")
    assert r.json()["geo_url"] == "https://mesh.example/geo/"
