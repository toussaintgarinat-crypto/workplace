"""Tests API (TestClient) : santé, catalogue, garde-fous, repli honnête, succès binaire."""
from fastapi.testclient import TestClient

import main
import moteur

client = TestClient(main.app)


def test_sante_mode_placeholder():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "piper" in data["fournisseurs"]
    assert data["configures"] == []           # conftest : rien de configuré
    assert data["backend"] == "placeholder"
    assert data["souverain"] is False


def test_liste_voix():
    r = client.get("/voix")
    noms = [f["nom"] for f in r.json()["fournisseurs"]]
    assert noms[0] == "piper"                  # souverain en tête
    assert all(f["configure"] is False for f in r.json()["fournisseurs"])


def test_synthetiser_texte_vide_422():
    r = client.post("/synthetiser", json={"texte": "   "})
    assert r.status_code == 422


def test_synthetiser_repli_honnete():
    # Aucun moteur configuré → JSON placeholder honnête, pas d'audio, JAMAIS de fausse voix.
    r = client.post("/synthetiser", json={"texte": "Bonjour"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert data["place_holder"] is True
    assert "audio" not in data                  # l'audio (None) n'est pas sérialisé


def test_synthetiser_succes_binaire(monkeypatch):
    async def faux(texte, voix=None, langue=None, format=None, fournisseur=None):
        return {"audio": b"OGG-OCTETS", "format": "ogg", "backend": "faux",
                "place_holder": False}

    monkeypatch.setattr(moteur, "synthetiser", faux)
    r = client.post("/synthetiser", json={"texte": "Bonjour"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/ogg"
    assert r.headers["x-backend"] == "faux" and r.headers["x-format"] == "ogg"
    assert r.content == b"OGG-OCTETS"
