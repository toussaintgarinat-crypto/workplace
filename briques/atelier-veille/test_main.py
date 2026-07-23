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


def test_config_bascule_en_https_port_decale_depuis_lhote_mesh(monkeypatch):
    """MESH_HOST posé (Caddy termine le TLS du mesh, cf. core/urls_ui.py) : /config doit
    renvoyer du HTTPS sur GEO_PORT+MESH_PORT_OFFSET, sinon la carte est bloquée en mixed
    content dès que l'atelier est ouvert en HTTPS via le mesh."""
    monkeypatch.setenv("MESH_HOST", "workplaceagenda.duckdns.org")
    import importlib
    importlib.reload(main)
    r = TestClient(main.app).get("/config", headers={"host": "workplaceagenda.duckdns.org:16130"})
    assert r.json()["geo_url"] == "https://workplaceagenda.duckdns.org:16110/"


def test_config_garde_le_lan_direct_quand_lhote_nest_pas_le_mesh(monkeypatch):
    monkeypatch.setenv("MESH_HOST", "workplaceagenda.duckdns.org")
    import importlib
    importlib.reload(main)
    r = TestClient(main.app).get("/config", headers={"host": "192.168.1.89:6130"})
    assert r.json()["geo_url"] == "http://192.168.1.89:6110/"
