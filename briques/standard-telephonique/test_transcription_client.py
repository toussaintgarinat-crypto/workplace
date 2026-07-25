"""Tests transcription_client : appel HTTP vers briques/transcription, mocké."""
import httpx
import pytest

import transcription_client


@pytest.mark.asyncio
async def test_transcrire_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcrire"
        return httpx.Response(200, json={"texte": "bonjour, ceci est un message",
                                        "place_holder": False})

    monkeypatch.setattr(transcription_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://transcription.test"))

    texte = await transcription_client.transcrire(b"faux-audio-wav")
    assert texte == "bonjour, ceci est un message"


@pytest.mark.asyncio
async def test_transcrire_repli_honnete_si_placeholder(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"texte": "", "place_holder": True})

    monkeypatch.setattr(transcription_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://transcription.test"))

    texte = await transcription_client.transcrire(b"faux-audio-wav")
    assert texte is None


@pytest.mark.asyncio
async def test_transcrire_repli_honnete_si_brique_injoignable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brique absente")

    monkeypatch.setattr(transcription_client, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://transcription.test"))

    texte = await transcription_client.transcrire(b"faux-audio-wav")
    assert texte is None
