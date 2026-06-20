"""Proxys du pont Google Agenda côté Cœur (consenti, lecture seule, OAuth).

Sans réseau : faux httpx.AsyncClient. Vérifie que chaque helper tape le bon contrat de
la brique (status / connect / sync / disconnect) et remonte l'URL de consentement.
    $ cd core && python3 test_agenda_google_proxys.py
"""
import asyncio
import sys, os

sys.path.insert(0, os.path.dirname(__file__))
import agenda  # noqa: E402

APPELS = []


class _Resp:
    def __init__(self, payload=None, status=200):
        self._p = payload if payload is not None else {}
        self.status_code = status
        self.headers = {"content-type": "application/json"}
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, headers=None, params=None):
        APPELS.append(("GET", url))
        if url.endswith("/google/status"):
            return _Resp({"connected": True, "scope": "calendar.readonly"})
        if url.endswith("/google/connect"):
            return _Resp({"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?x=1"})
        return _Resp([])
    async def post(self, url, headers=None, json=None, params=None):
        APPELS.append(("POST", url, params))
        return _Resp({"created": 3, "updated": 1})
    async def delete(self, url, headers=None):
        APPELS.append(("DELETE", url))
        return _Resp({}, status=204)


def _setup():
    APPELS.clear()
    agenda._base = lambda registre: "http://agenda"
    agenda.httpx.AsyncClient = _FakeClient


def _run(c): return asyncio.new_event_loop().run_until_complete(c)


def test_google_etat():
    _setup()
    r = _run(agenda.google_etat(None))
    assert ("GET", "http://agenda/google/status") in APPELS
    assert r["connected"] is True


def test_google_url_consentement():
    _setup()
    r = _run(agenda.google_url_consentement(None))
    assert ("GET", "http://agenda/google/connect") in APPELS
    assert r["ok"] is True and r["authorization_url"].startswith("https://accounts.google.com")


def test_google_synchroniser():
    _setup()
    r = _run(agenda.google_synchroniser(None, "2030-01-01T00:00:00Z", "2030-02-01T00:00:00Z"))
    appel = next(a for a in APPELS if a[0] == "POST")
    assert appel[1] == "http://agenda/google/sync"
    assert appel[2] == {"time_min": "2030-01-01T00:00:00Z", "time_max": "2030-02-01T00:00:00Z"}
    assert r["ok"] is True and r["created"] == 3


def test_google_deconnecter():
    _setup()
    assert _run(agenda.google_deconnecter(None)) is True
    assert ("DELETE", "http://agenda/google/disconnect") in APPELS


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
