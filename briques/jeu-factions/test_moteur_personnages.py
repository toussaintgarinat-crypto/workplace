import httpx
import pytest
from fastapi import HTTPException

import moteur_personnages as MP


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_portrait_relaie_le_resultat():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/holistique/portrait"
        return httpx.Response(200, json={"traditions": {}, "portrait": {"archetype": "Le Sage Contemplatif"}, "empreinte": []})

    async with _client(handler) as c:
        r = await MP.portrait({"date_naissance": "1990-09-05"}, client=c)
    assert r["portrait"]["archetype"] == "Le Sage Contemplatif"


@pytest.mark.asyncio
async def test_portrait_leve_503_si_injoignable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _client(handler) as c:
        with pytest.raises(HTTPException) as exc:
            await MP.portrait({"date_naissance": "1990-09-05"}, client=c)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_portrait_propage_lerreur_amont():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Fiche insuffisante"})

    async with _client(handler) as c:
        with pytest.raises(HTTPException) as exc:
            await MP.portrait({}, client=c)
    assert exc.value.status_code == 422
    assert "Fiche insuffisante" in exc.value.detail


@pytest.mark.asyncio
async def test_recherche_inverse_relaie_le_resultat():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/holistique/recherche-inverse"
        return httpx.Response(200, json={"exemple_date": "1990-04-01", "signes": []})

    async with _client(handler) as c:
        r = await MP.recherche_inverse("guerrier colérique et solitaire", client=c)
    assert r["exemple_date"] == "1990-04-01"
