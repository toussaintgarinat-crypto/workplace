"""Jeton signé Cœur→mémoire + bootstrap SPA / proxy /api/v1 PAR PERSONNE (S186).

Le navigateur ne peut PAS poser d'en-tête custom sur une simple navigation d'iframe : the
identité voyage donc en jeton d'URL (1re navigation, posé par le Cœur) puis en cookie signé
(navigations suivantes) — jamais un en-tête que le navigateur pourrait forger lui-même.
"""
import time

import httpx
import pytest
import respx

import main

API = main.MEMORY_API
WORKPLACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    main._session["token"] = None
    main._espaces.clear()
    main._sessions_personne.clear()
    main._espaces_personne.clear()
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur-memoire")
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>x</title></head><body></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "UI_DIR", tmp_path)
    yield


async def _appel(method: str, url: str, **kw):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://brique") as c:
        return await c.request(method, url, **kw)


def _cablage(rsx: respx.MockRouter):
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))

    def _login(request):
        import json
        email = json.loads(request.content)["email"]
        jwt = "jwt-service" if email == main.EMAIL else f"jwt-{email.split('@')[0]}"
        return httpx.Response(200, json={"access_token": jwt})

    rsx.post(f"{API}/api/v1/auth/login").mock(side_effect=_login)
    rsx.get(f"{API}/api/v1/spaces").mock(
        return_value=httpx.Response(200, json=[{"id": WORKPLACE_ID, "name": "Workplace"}]))
    rsx.post(f"{API}/api/v1/spaces/{WORKPLACE_ID}/invite").mock(
        return_value=httpx.Response(200, json={"detail": "invited"}))


# ── Jeton : intégrité, expiration ────────────────────────────────────────────────

def test_jeton_round_trip():
    jeton = main._emettre_jeton("claire", ttl=60)
    assert main._verifier_jeton(jeton) == "claire"


def test_jeton_expire_refuse():
    jeton = main._emettre_jeton("claire", ttl=-1)
    assert main._verifier_jeton(jeton) is None


def test_jeton_trafique_refuse():
    jeton = main._emettre_jeton("claire", ttl=60)
    trafique = jeton.replace("claire", "marina", 1)
    assert main._verifier_jeton(trafique) is None


def test_sans_cle_aucun_jeton_valide(monkeypatch):
    jeton = main._emettre_jeton("claire", ttl=60)
    monkeypatch.delenv("MEMOIRE_KEY", raising=False)
    assert main._verifier_jeton(jeton) is None


# ── Bootstrap SPA (/memory) : jeton d'URL → cookie posé + JWT de LA personne ─────

@pytest.mark.asyncio
@respx.mock
async def test_bootstrap_avec_jeton_injecte_le_jwt_de_la_personne():
    _cablage(respx.mock)
    jeton = main._emettre_jeton("claire")
    r = await _appel("GET", f"/memory?m={jeton}")
    assert r.status_code == 200
    assert "jwt-claire" in r.text
    assert WORKPLACE_ID in r.text
    assert r.cookies.get(main.COOKIE_MEMOIRE) is not None


@pytest.mark.asyncio
@respx.mock
async def test_bootstrap_sans_jeton_reste_sur_le_service():
    _cablage(respx.mock)
    r = await _appel("GET", "/memory")
    assert r.status_code == 200
    assert "jwt-service" in r.text
    assert r.cookies.get(main.COOKIE_MEMOIRE) is None


@pytest.mark.asyncio
@respx.mock
async def test_bootstrap_cookie_seul_reste_identifie():
    """Navigation suivante (pas de ?m=, le jeton d'URL a expiré) : le cookie SUFFIT."""
    _cablage(respx.mock)
    cookie_valide = main._emettre_jeton("claire", ttl=3600)
    r = await _appel("GET", "/memory", cookies={main.COOKIE_MEMOIRE: cookie_valide})
    assert r.status_code == 200
    assert "jwt-claire" in r.text


@pytest.mark.asyncio
@respx.mock
async def test_bootstrap_jeton_trafique_retombe_sur_le_service():
    _cablage(respx.mock)
    jeton = main._emettre_jeton("claire").replace("claire", "marina", 1)
    r = await _appel("GET", f"/memory?m={jeton}")
    assert r.status_code == 200
    assert "jwt-service" in r.text


# ── Proxy /api/v1 : identité PAR REQUÊTE (cookie), jamais celle du front lui-même ────

@pytest.mark.asyncio
@respx.mock
async def test_proxy_avec_cookie_utilise_le_jwt_de_la_personne():
    _cablage(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces/{WORKPLACE_ID}/graph").mock(
        return_value=httpx.Response(200, json={"nodes": [], "edges": []}))
    cookie = main._emettre_jeton("claire", ttl=3600)
    r = await _appel("GET", f"/api/v1/spaces/{WORKPLACE_ID}/graph",
                     cookies={main.COOKIE_MEMOIRE: cookie},
                     headers={"Authorization": "Bearer perime-du-front"})
    assert r.status_code == 200
    # Le jwt du front (potentiellement périmé) est ignoré ; celui de LA PERSONNE prime.
    assert route.calls.last.request.headers["authorization"] == "Bearer jwt-claire"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_sans_cookie_reste_le_compte_de_service():
    _cablage(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces/{WORKPLACE_ID}/graph").mock(
        return_value=httpx.Response(200, json={"nodes": [], "edges": []}))
    await _appel("GET", f"/api/v1/spaces/{WORKPLACE_ID}/graph")
    assert route.calls.last.request.headers["authorization"] == "Bearer jwt-service"
