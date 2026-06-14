"""Tests — Synergie Studio ↔ brique video (5970), miroir de test_images.py (S55).

Le pont `_appeler_video` (URL absolue + repli honnête) et la fonction d'URL. Les endpoints
(teaser/animer) sont prouvés ailleurs en LIVE ; ici les fonctions pures + le repli quand
la brique video est injoignable."""
import asyncio

import studio as A


# ── URL de vidéo rendue affichable ───────────────────────────────
def test_url_absolue_prefixe_les_relatives():
    out = A._url_video_absolue("/fichiers/clip.mp4")
    assert out.endswith("/fichiers/clip.mp4")
    assert out.startswith("http")


def test_url_absolue_laisse_les_absolues():
    assert A._url_video_absolue("http://x/y.mp4") == "http://x/y.mp4"


def test_url_absolue_vide():
    assert A._url_video_absolue("") == ""


# ── Pont vers la brique video : succès + repli honnête ──────────
def test_appeler_video_rend_url_absolue(monkeypatch):
    class FauxRep:
        def raise_for_status(self): pass
        def json(self): return {"url": "/fichiers/ph.svg", "place_holder": True}

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return FauxRep()

    monkeypatch.setattr(A.httpx, "AsyncClient", FauxClient)
    res = asyncio.run(A._appeler_video("/teaser", {"titre": "T"}))
    assert res["place_holder"] is True
    assert res["url"].startswith("http") and res["url"].endswith("/fichiers/ph.svg")


def test_appeler_video_repli_none_si_injoignable(monkeypatch):
    class ClientKO:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("connection refused")

    monkeypatch.setattr(A.httpx, "AsyncClient", ClientKO)
    assert asyncio.run(A._appeler_video("/animer", {"fiche": {}})) is None
