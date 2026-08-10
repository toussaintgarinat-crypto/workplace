"""S227 : GET /objets/{id} — lecture d'un objet géo par id (n'existait pas)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_lire_objet_existant():
    """Lecture d'un objet existant retourne 200 avec le même shape que POST."""
    creation = client.post("/objets", json={
        "type": "entreprise", "latitude": 48.85, "longitude": 2.35,
        "metadata": {"nom": "Acme SARL"},
    })
    assert creation.status_code == 201
    objet_id = creation.json()["id"]

    lecture = client.get(f"/objets/{objet_id}")
    assert lecture.status_code == 200
    assert lecture.json()["id"] == objet_id
    assert lecture.json()["metadata"]["nom"] == "Acme SARL"


def test_lire_objet_inexistant_retourne_404():
    """Lecture d'un objet inexistant retourne 404."""
    resp = client.get("/objets/inexistant-xyz")
    assert resp.status_code == 404
