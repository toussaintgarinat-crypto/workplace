"""S227 : GET /objets/{id} — lecture d'un objet géo par id (n'existait pas)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

CLE_PROSPECTEUR = {"X-API-Key": "prospecteur"}


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


def test_lire_objet_d_un_autre_tenant_404():
    """Isolation tenant : un objet créé par un tenant ne peut pas être lu par un autre.
    Crée un objet avec une clé API, puis essaie de le lire avec une autre clé.
    Doit retourner 404 (fail-closed, aucune révélation d'existence entre tenants)."""
    # Crée l'objet avec la clé "prospecteur"
    creation = client.post("/objets", headers=CLE_PROSPECTEUR, json={
        "type": "entreprise", "latitude": 43.606, "longitude": 2.24,
        "metadata": {"nom": "Entreprise Secrète"},
    })
    assert creation.status_code == 201
    objet_id = creation.json()["id"]

    # Essaie de lire avec une clé différente "un-autre"
    lecture = client.get(f"/objets/{objet_id}", headers={"X-API-Key": "un-autre"})
    assert lecture.status_code == 404
