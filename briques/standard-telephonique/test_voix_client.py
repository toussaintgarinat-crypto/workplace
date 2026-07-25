"""Tests voix_client : appel HTTP vers briques/voix, mocké (aucun réseau réel)."""
import httpx
import pytest

import voix_client


@pytest.mark.asyncio
async def test_synthetiser_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/synthetiser"
        assert request.method == "POST"
        return httpx.Response(200, content=b"FAUX-WAV-OCTETS",
                              headers={"content-type": "audio/wav"})

    monkeypatch.setattr(voix_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://voix.test"))
    monkeypatch.setenv("VOIX_URL", "http://voix.test")

    audio = await voix_client.synthetiser("Bonjour")
    assert audio == b"FAUX-WAV-OCTETS"


@pytest.mark.asyncio
async def test_synthetiser_repli_honnete_si_placeholder(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"place_holder": True, "backend": "aucun"})

    monkeypatch.setattr(voix_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://voix.test"))
    monkeypatch.setenv("VOIX_URL", "http://voix.test")

    audio = await voix_client.synthetiser("Bonjour")
    assert audio is None


@pytest.mark.asyncio
async def test_synthetiser_repli_honnete_si_brique_injoignable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brique absente")

    monkeypatch.setattr(voix_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://voix.test"))
    monkeypatch.setenv("VOIX_URL", "http://voix.test")

    audio = await voix_client.synthetiser("Bonjour")
    assert audio is None
