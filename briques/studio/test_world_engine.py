"""Tests — pont vers world-engine : _appeler_world_engine + wrappers. Même motif que
test_images.py (monkeypatch de httpx.AsyncClient, pas respx — absent des dépendances de
cette brique)."""
import asyncio

import studio as A


class _FauxRep:
    def __init__(self, data): self._data = data
    def raise_for_status(self): pass
    def json(self): return self._data


class _FauxClient:
    def __init__(self, reponse=None, leve=None):
        self._reponse, self._leve = reponse, leve
    def __call__(self, *a, **k): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def request(self, methode, url, json=None, headers=None):
        if self._leve:
            raise self._leve
        return _FauxRep(self._reponse)


def test_appeler_world_engine_succes(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(reponse={"id": "m1"}))
    res = asyncio.run(A._appeler_world_engine("POST", "/spatial/mondes", {"nb_cellules": 10}))
    assert res == {"id": "m1"}


def test_appeler_world_engine_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    assert asyncio.run(A._appeler_world_engine("GET", "/sante")) is None


def test_pont_creer_monde_appelle_spatial_mondes(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(reponse={"id": "m2", "nb_cellules": 10}))
    assert asyncio.run(A._pont_creer_monde()) == {"id": "m2", "nb_cellules": 10}


def test_pont_fonder_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    assert asyncio.run(A._pont_fonder("m1", "une description", "Elara")) is None


def test_pont_tick_ne_leve_jamais(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    asyncio.run(A._pont_tick("m1"))   # ne lève pas, pas de valeur de retour à vérifier


def test_pont_lire_enfant_succes(monkeypatch):
    monkeypatch.setattr(A.httpx, "AsyncClient", _FauxClient(reponse={"id": "e1", "simulation": None}))
    assert asyncio.run(A._pont_lire_enfant("e1")) == {"id": "e1", "simulation": None}


def test_appeler_world_engine_envoie_la_cle_si_configuree(monkeypatch):
    capture = {}
    class _ClientCapture(_FauxClient):
        async def request(self, methode, url, json=None, headers=None):
            capture['headers'] = headers
            return _FauxRep({"ok": True})
    monkeypatch.setattr(A, "WORLD_ENGINE_KEY", "cle-test")
    monkeypatch.setattr(A.httpx, "AsyncClient", _ClientCapture())
    asyncio.run(A._appeler_world_engine("GET", "/sante"))
    assert capture['headers'] == {"X-API-Key": "cle-test"}


def test_appeler_world_engine_aucun_header_sans_cle(monkeypatch):
    capture = {}
    class _ClientCapture(_FauxClient):
        async def request(self, methode, url, json=None, headers=None):
            capture['headers'] = headers
            return _FauxRep({"ok": True})
    monkeypatch.setattr(A, "WORLD_ENGINE_KEY", "")
    monkeypatch.setattr(A.httpx, "AsyncClient", _ClientCapture())
    asyncio.run(A._appeler_world_engine("GET", "/sante"))
    assert capture['headers'] == {}
