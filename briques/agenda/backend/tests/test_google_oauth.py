"""Service OAuth Google — URL de consentement + échange de code (HTTP mocké)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from config import settings
from services import google_oauth


@pytest.fixture(autouse=True)
def _google_creds():
    settings.GOOGLE_CLIENT_ID = "client-abc.apps.googleusercontent.com"
    settings.GOOGLE_CLIENT_SECRET = "secret-xyz"
    settings.GOOGLE_REDIRECT_URI = "http://localhost:8400/google/callback"
    yield


def test_is_configured():
    assert google_oauth.is_configured() is True
    settings.GOOGLE_CLIENT_ID = ""
    assert google_oauth.is_configured() is False


def test_build_auth_url_carries_offline_and_state():
    url = google_oauth.build_auth_url(state="user-42")
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["user-42"]
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["client-abc.apps.googleusercontent.com"]


class _FakeResponse:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.is_success = ok
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._response


@pytest.mark.asyncio
async def test_exchange_code_normalizes(monkeypatch):
    resp = _FakeResponse(
        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "s"}
    )
    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))
    out = await google_oauth.exchange_code("the-code")
    assert out["access_token"] == "at"
    assert out["refresh_token"] == "rt"
    assert out["expires_at"] is not None


@pytest.mark.asyncio
async def test_exchange_code_error_raises(monkeypatch):
    resp = _FakeResponse({"error": "invalid_grant"}, ok=False, status_code=400)
    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))
    with pytest.raises(google_oauth.GoogleOAuthError):
        await google_oauth.exchange_code("bad-code")


@pytest.mark.asyncio
async def test_refresh_access_token(monkeypatch):
    resp = _FakeResponse({"access_token": "fresh", "expires_in": 3600})
    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))
    out = await google_oauth.refresh_access_token("rt")
    assert out["access_token"] == "fresh"
    assert out["expires_at"] is not None
