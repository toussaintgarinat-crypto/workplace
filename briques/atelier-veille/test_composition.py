"""Tests — composition de veille-info (sources RSS) par l'atelier-veille.

L'atelier ne stocke rien : il relaie tel quel vers veille-info et relaie les en-têtes
d'identité reçus du navigateur (pass-through pur, jamais fabriqués)."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False):
    class FauxRep:
        status_code = status
        def json(self): return rep_json

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("GET", url, headers)
            return FauxRep()
        async def post(self, url, headers=None, json=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("POST", url, headers, json)
            return FauxRep()
        async def delete(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("DELETE", url, headers)
            return FauxRep()
    return FauxClient


def test_lister_sources_proxifie_vers_veille_info(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json([{"id": 1, "nom": "Flux A", "url": "https://a.example/rss"}]))
    r = client.get("/veille/sources", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "nom": "Flux A", "url": "https://a.example/rss"}]


def test_lister_sources_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/sources", headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/sources"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_lister_sources_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/sources")
    _, _, headers = Faux.dernier_appel
    assert headers == {}


def test_lister_sources_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/veille/sources")
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


def test_creer_source_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 2, "nom": "Flux B", "url": "https://b.example/rss"}, status=201)
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/veille/sources", json={"nom": "Flux B", "url": "https://b.example/rss"})
    assert r.status_code == 201
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"nom": "Flux B", "url": "https://b.example/rss"}


def test_supprimer_source_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({"ok": True}))
    r = client.delete("/veille/sources/2")
    assert r.status_code == 200


def test_supprimer_source_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Source introuvable."}, status=404))
    r = client.delete("/veille/sources/999")
    assert r.status_code == 404
