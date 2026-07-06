"""Cloisonnement multi-tenant : une clé API ne voit jamais les points d'une autre."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

BBOX = "43.55,2.10,43.70,2.35"


def test_les_objets_d_un_tenant_sont_invisibles_pour_un_autre():
    r = client.post("/objets", headers={"X-API-Key": "solution-A"},
                    json={"latitude": 43.606, "longitude": 2.24,
                          "metadata": {"nom": "Secret de A"}})
    assert r.status_code == 201
    vus_par_b = client.get("/objets", params={"bbox": BBOX},
                           headers={"X-API-Key": "solution-B"}).json()
    assert all(o["metadata"].get("nom") != "Secret de A" for o in vus_par_b["objets"])


def test_deux_cles_donnent_deux_tenants_stables():
    vus_par_a = client.get("/objets", params={"bbox": BBOX},
                           headers={"X-API-Key": "solution-A"}).json()
    assert any(o["metadata"].get("nom") == "Secret de A" for o in vus_par_a["objets"])
