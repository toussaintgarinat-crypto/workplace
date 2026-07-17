def test_png_icone_signature():
    from services.icones import png_icone
    data = png_icone(192)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 100


# S178 B3 — routes /app/manifest.webmanifest, /app/sw.js, /app/icone-{taille}.png.
# Cette brique n'a pas de fixture `client`/TestClient (monter main.app déclenche le
# lifespan + la DB) : on appelle directement les fonctions de route async et on
# inspecte la Response retournée.

import json

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_manifest_servi():
    from routers.pwa import manifest

    resp = await manifest()
    assert resp.media_type == "application/manifest+json"
    m = json.loads(resp.body)
    assert m["start_url"] == "/app"
    assert m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])
    assert any(s["url"].startswith("/app") for s in m["shortcuts"])


@pytest.mark.asyncio
async def test_sw_servi_avec_scope():
    from routers.pwa import service_worker

    resp = await service_worker()
    assert resp.media_type == "application/javascript"
    assert resp.headers["service-worker-allowed"] == "/"
    assert b"addEventListener" in resp.body and b"push" in resp.body


@pytest.mark.asyncio
async def test_icone_png():
    from routers.pwa import icone

    resp = await icone("192")
    assert resp.media_type == "image/png"
    assert resp.body[:8] == b"\x89PNG\r\n\x1a\n"

    resp_maskable = await icone("maskable")
    assert resp_maskable.media_type == "image/png"
    assert resp_maskable.body[:8] == b"\x89PNG\r\n\x1a\n"

    with pytest.raises(HTTPException) as exc_info:
        await icone("999")
    assert exc_info.value.status_code == 404
