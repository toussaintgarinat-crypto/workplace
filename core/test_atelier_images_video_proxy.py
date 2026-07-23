"""Proxy atelier-images-video du Cœur : vue native /atelier-images-video-app/*, isolée
PAR PERSONNE. Motif copié de core/test_studio_proxy.py. Sans réseau : httpx.AsyncClient est
remplacé par un faux client qui enregistre les appels (méthode, url, en-têtes). Vérifie que
l'identité forwardée à la brique vient de LA SESSION (contexte de tenant), jamais de ce
que le navigateur a lui-même posé sur sa requête au Cœur."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ["ATELIER_IMAGES_VIDEO_KEY"] = "cle-coeur-atelier-iv"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import atelier_images_video_proxy  # noqa: E402

client = TestClient(main.app)

APPELS = []


class _Resp:
    def __init__(self, texte="", status=200, content_type="application/json"):
        self._texte = texte
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = texte.encode() if texte else b"{}"

    @property
    def text(self):
        return self._texte


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, content=None):
        APPELS.append((method, url, headers))
        return _Resp()

    async def get(self, url, headers=None):
        APPELS.append(("GET", url, headers))
        if url.endswith("/") or url.endswith("/atelier"):
            return _Resp(texte="<html><head></head><body></body></html>")
        return _Resp()


def _setup(monkeypatch):
    APPELS.clear()
    monkeypatch.setattr(atelier_images_video_proxy, "_base", lambda: "http://atelier-iv")
    monkeypatch.setattr(atelier_images_video_proxy, "httpx",
                        type("_H", (), {"AsyncClient": _FakeClient}))


def test_racine_injecte_le_prefixe(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/atelier-images-video-app/", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert "window.ATELIER_IV_API_BASE='/atelier-images-video-app';" in r.text


def test_identite_de_session_forwardee_pas_celle_du_navigateur(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/atelier-images-video-app/studio/series", headers={
        "X-User-Id": "claire", "X-API-Key": "cle-volee-par-le-navigateur",
    })
    assert r.status_code == 200
    methode, url, entetes = APPELS[-1]
    assert url == "http://atelier-iv/studio/series"
    assert entetes["X-User-Id"] == "claire"
    assert entetes["X-API-Key"] == "cle-coeur-atelier-iv"


def test_deux_personnes_appels_distincts(monkeypatch):
    _setup(monkeypatch)
    client.get("/atelier-images-video-app/galerie", headers={"X-User-Id": "claire"})
    client.get("/atelier-images-video-app/galerie", headers={"X-User-Id": "marina"})
    identites = [e["X-User-Id"] for _, _, e in APPELS]
    assert identites == ["claire", "marina"]
