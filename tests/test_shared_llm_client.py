"""Tests de shared.llm_client (S118) — la plomberie Gateway mutualisée.

Couvre l'extraction JSON, le calcul d'attente (Retry-After), le succès nominal, le
backoff sur 429 puis succès, et l'épuisement réseau → RuntimeError. Aucun réseau réel :
on injecte un faux client httpx.
"""
import asyncio

import httpx
import pytest

from shared import llm_client


# ── Faux client httpx : rejoue une file de réponses / exceptions ────────────────
class _Resp:
    def __init__(self, status, contenu="", headers=None):
        self.status_code = status
        self._contenu = contenu
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return {"choices": [{"message": {"content": self._contenu}}]}


class _FauxClient:
    def __init__(self, file):
        self._file = list(file)
        self.appels = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.appels += 1
        item = self._file.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def _no_sleep(*_a, **_k):
    return None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "test-cle")
    monkeypatch.setenv("GATEWAY_URL", "http://gw.test:4001")
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)            # neutralise le backoff


def _brancher(monkeypatch, faux):
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: faux)
    return faux


def test_extraire_json_tolere_le_markdown_autour():
    assert llm_client.extraire_json('Voici : ```json\n{"a": 1}\n``` fin') == {"a": 1}


def test_extraire_json_leve_si_absent():
    with pytest.raises(ValueError):
        llm_client.extraire_json("aucun json ici")


def test_attente_respecte_retry_after():
    r = _Resp(429, headers={"retry-after": "12"})
    assert llm_client._attente(r, 5) == 12
    assert llm_client._attente(_Resp(429), 5) == 5             # pas d'en-tête → défaut
    assert llm_client._attente(_Resp(429, headers={"retry-after": "999"}), 5) == 60  # plafonné


def test_appel_nominal_renvoie_le_json(monkeypatch):
    faux = _brancher(monkeypatch, _FauxClient([_Resp(200, '{"ok": true}')]))
    out = asyncio.run(llm_client.appeler_json("salut", system_prompt="sys"))
    assert out == {"ok": True}
    assert faux.appels == 1


def test_backoff_sur_429_puis_succes(monkeypatch):
    faux = _brancher(monkeypatch, _FauxClient([
        _Resp(429, headers={"retry-after": "0"}),
        _Resp(200, '{"resultat": 42}'),
    ]))
    out = asyncio.run(llm_client.appeler_json("x", system_prompt="sys"))
    assert out == {"resultat": 42}
    assert faux.appels == 2                                    # a bien retenté


def test_epuisement_reseau_leve_runtimeerror(monkeypatch):
    faux = _brancher(monkeypatch, _FauxClient(
        [httpx.ConnectError("injoignable")] * llm_client.MAX_TENTATIVES))
    with pytest.raises(RuntimeError, match="indisponible"):
        asyncio.run(llm_client.appeler_json("x", system_prompt="sys"))
    assert faux.appels == llm_client.MAX_TENTATIVES


def test_modele_et_url_lus_de_l_env(monkeypatch):
    monkeypatch.setenv("GATEWAY_MODEL", "openai/gpt-4o-mini")
    assert llm_client.modele_defaut() == "openai/gpt-4o-mini"
    assert llm_client.url_gateway() == "http://gw.test:4001"
