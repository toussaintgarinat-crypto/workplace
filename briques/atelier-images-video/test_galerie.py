"""Tests — galerie (POST/GET/DELETE /galerie), proxy vers la brique mémoire (5600) avec
secret de service (MEMOIRE_KEY) + identité relayée."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False):
    class FauxReponse:
        status_code = status
        def json(self):
            return rep_json

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, methode, url, headers=None, json=None, params=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = (methode, url, headers, json, params)
            return FauxReponse()
    return FauxClient


def test_galerie_ajouter_construit_le_souvenir_ressource(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    Faux = _client_json({"retenu": True, "id": "n1", "titre": "un chat", "type": "ressource",
                         "wing": "atelier-images-video", "room": "image"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/galerie", json={
        "titre": "un chat", "prompt": "un chat qui dort au soleil",
        "medium": "image", "url": "/fichiers/img-1.png",
        "fournisseur": "fal", "place_holder": False,
    }, headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    methode, url, entetes, corps, _ = Faux.dernier_appel
    assert url == f"{M.MEMOIRE_URL}/retenir"
    assert entetes == {"X-API-Key": "cle-memoire", "X-User-Id": "claire"}
    assert corps == {
        "type": "ressource", "titre": "un chat", "contenu": "un chat qui dort au soleil",
        "wing": "atelier-images-video", "room": "image",
        "metadata": {"url": "/fichiers/img-1.png", "fournisseur": "fal", "place_holder": False},
    }


def test_galerie_lister_filtre_par_wing_et_medium(monkeypatch):
    Faux = _client_json({"total": 1, "souvenirs": [{"id": "n1", "titre": "un chat"}]})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/galerie", params={"medium": "image"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    _, url, _, _, params = Faux.dernier_appel
    assert url == f"{M.MEMOIRE_URL}/souvenirs"
    assert params == {"wing": "atelier-images-video", "room": "image"}


def test_galerie_lister_sans_filtre_medium(monkeypatch):
    Faux = _client_json({"total": 0, "souvenirs": []})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/galerie")
    _, _, _, _, params = Faux.dernier_appel
    assert params == {"wing": "atelier-images-video"}


def test_galerie_supprimer_proxifie(monkeypatch):
    Faux = _client_json({"supprime": True, "id": "n1"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.delete("/galerie/n1")
    assert r.status_code == 200
    methode, url, _, _, _ = Faux.dernier_appel
    assert methode == "DELETE"
    assert url == f"{M.MEMOIRE_URL}/souvenir/n1"


def test_galerie_memoire_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/galerie")
    assert r.status_code == 502
    assert "mémoire" in r.json()["detail"]
