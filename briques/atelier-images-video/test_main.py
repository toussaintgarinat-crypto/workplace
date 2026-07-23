"""Tests API de la brique atelier-images-video : santé + front (voir aussi
test_front.py, test_images_video.py, test_synergies_studio.py, test_galerie.py)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"
