"""S241 — route /recherche du Cœur et outil chercher_documents.

$ cd core && python3 -m pytest test_recherche_route.py -v
"""
import asyncio
import json
import os
import tempfile
import time

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import recherche_unifiee  # noqa: E402
import session_registre  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    ancien = session_registre.DB
    session_registre.DB = os.path.join(tempfile.mkdtemp(), "session_registre.db")
    auth._cache_access_token.clear()
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    yield
    session_registre.DB = ancien
    auth._cache_access_token.clear()


def _cookie(sub):
    auth._cache_access_token[sub] = ("at-cache", time.time() + 60)
    return {auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": sub, "refresh_token": "rt-1"})}


def test_sans_session_401():
    assert client.get("/recherche", params={"q": "x"}).status_code == 401


def test_avec_session_relaie_au_service(monkeypatch):
    vus = {}

    async def _faux(q, registre, limite=10, sources=None, transport=None):
        vus.update(q=q, limite=limite, sources=sources)
        return {"resultats": [], "modes": {}, "sources_indisponibles": ["forge"]}

    monkeypatch.setattr(recherche_unifiee, "rechercher", _faux)
    r = client.get("/recherche", params={"q": "toiture", "limite": 5, "sources": "forge,memoire"},
                   cookies=_cookie("marina"))
    assert r.status_code == 200 and r.json()["sources_indisponibles"] == ["forge"]
    assert vus == {"q": "toiture", "limite": 5, "sources": {"forge", "memoire"}}


def test_toutes_sources_en_panne_503(monkeypatch):
    async def _panne(*a, **k):
        raise recherche_unifiee.ToutesSourcesIndisponibles(["forge", "ingestion", "memoire"])

    monkeypatch.setattr(recherche_unifiee, "rechercher", _panne)
    r = client.get("/recherche", params={"q": "x"}, cookies=_cookie("marina"))
    assert r.status_code == 503


def test_source_inconnue_422():
    r = client.get("/recherche", params={"q": "x", "sources": "foo"}, cookies=_cookie("marina"))
    assert r.status_code == 422 and "source inconnue" in r.json()["detail"]


def test_outil_avec_q_passe_par_la_recherche_unifiee(monkeypatch):
    import outils_domaines.documents as documents

    async def _faux(q, registre, limite=10, sources=None, transport=None):
        return {"resultats": [{"source": "ingestion", "id": "i1"}], "modes": {}, "sources_indisponibles": []}

    monkeypatch.setattr(recherche_unifiee, "rechercher", _faux)
    sortie = asyncio.run(documents.dispatch("chercher_documents", {"q": "toiture"}, None, None))
    assert json.loads(sortie)["resultats"][0]["id"] == "i1"


def test_outil_toutes_sources_en_panne_message_clair(monkeypatch):
    import outils_domaines.documents as documents

    async def _panne(*a, **k):
        raise recherche_unifiee.ToutesSourcesIndisponibles(["forge"])

    monkeypatch.setattr(recherche_unifiee, "rechercher", _panne)
    sortie = json.loads(asyncio.run(documents.dispatch("chercher_documents", {"q": "x"}, None, None)))
    assert sortie["ok"] is False and "indisponible" in sortie["message"]
