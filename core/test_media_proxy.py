"""Proxy de fichiers de brique media (images/video/export) — S196. Sans réseau : httpx est
remplacé par un faux client qui rejoue une réponse fixe. Vérifie que le Cœur rejoue bien
`/fichiers/{nom}` de la brique demandée, refuse les briques non listées, et propage un
404 amont."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import media_proxy  # noqa: E402

client = TestClient(main.app)


class _Resp:
    def __init__(self, content=b"donnees-image", status=200, content_type="image/png"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        APPELS.append(url)
        if "/introuvable" in url:
            return _Resp(content=b"", status=404, content_type="text/plain")
        return _Resp()


APPELS = []


def _setup(monkeypatch):
    APPELS.clear()
    monkeypatch.setattr(media_proxy.orchestrateur, "_brique_base",
                        lambda registre, nom: f"http://{nom}-interne")
    monkeypatch.setattr(media_proxy, "httpx",
                        type("_H", (), {"AsyncClient": _FakeClient}))


def test_rejoue_le_fichier_de_la_brique(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/brique-fichiers/images/img-abc123.png")
    assert r.status_code == 200
    assert r.content == b"donnees-image"
    assert APPELS == ["http://images-interne/fichiers/img-abc123.png"]


def test_brique_non_autorisee_refusee(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/brique-fichiers/memoire/img-abc123.png")
    assert r.status_code == 404
    assert APPELS == []


def test_404_amont_propage(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/brique-fichiers/images/introuvable.png")
    assert r.status_code == 404
