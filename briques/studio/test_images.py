"""Tests — Synergie Studio ↔ brique images, repris hors Oria (S51).

Le pont `_appeler_images` (URL absolue + repli honnête) et la fonction d'URL. Les endpoints
(portrait/couverture/import) sont prouvés ailleurs en LIVE ; ici les fonctions pures + le
repli quand la brique images est injoignable."""
import asyncio

import studio as A


# ── URL d'image rendue affichable ────────────────────────────────
def test_url_absolue_prefixe_les_relatives():
    out = A._url_image_absolue("/fichiers/abc.png")
    assert out.endswith("/fichiers/abc.png")
    assert out.startswith("http")


def test_url_absolue_laisse_les_absolues():
    assert A._url_image_absolue("http://x/y.png") == "http://x/y.png"


def test_url_absolue_vide():
    assert A._url_image_absolue("") == ""


# ── Pont vers la brique images : succès + repli honnête ──────────
def test_appeler_images_rend_url_absolue(monkeypatch):
    class FauxRep:
        def raise_for_status(self): pass
        def json(self): return {"url": "/fichiers/p.svg", "place_holder": True}

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return FauxRep()

    monkeypatch.setattr(A.httpx, "AsyncClient", FauxClient)
    res = asyncio.run(A._appeler_images("/portrait", {"fiche": {}}))
    assert res["place_holder"] is True
    assert res["url"].startswith("http") and res["url"].endswith("/fichiers/p.svg")


def test_appeler_images_repli_none_si_injoignable(monkeypatch):
    class ClientKO:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("connection refused")

    monkeypatch.setattr(A.httpx, "AsyncClient", ClientKO)
    assert asyncio.run(A._appeler_images("/couverture", {})) is None
