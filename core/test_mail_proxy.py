"""Proxy mail du Cœur (S185) : vue native /mail-app/*, isolée PAR PERSONNE.

Sans réseau : httpx.AsyncClient est remplacé par un faux client qui enregistre les appels
(méthode, url, en-têtes) — comme test_agenda_proxys.py. Vérifie que l'identité forwardée à
la brique mail vient de LA SESSION (contexte de tenant), jamais de ce que le navigateur a
lui-même posé sur sa requête au Cœur.
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ["MAIL_KEY"] = "cle-coeur-mail"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import mail_proxy  # noqa: E402

client = TestClient(main.app)

APPELS = []


class _Resp:
    def __init__(self, texte="", payload=None, status=200, content_type="application/json"):
        self._texte = texte
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = texte.encode() if texte else b'{"messages": []}'

    @property
    def text(self):
        return self._texte


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, content=None):
        APPELS.append((method, url, headers))
        return _Resp()

    async def get(self, url, headers=None):
        APPELS.append(("GET", url, headers))
        if url.endswith("/"):
            return _Resp(texte='<html><head></head><body>'
                                '<script src="/static/purify.min.js"></script>'
                                '</body></html>')
        return _Resp()


def _setup(monkeypatch):
    APPELS.clear()
    # `_base` est LOCAL à mail_proxy (comme agenda.py) : patcher ICI, jamais
    # `orchestrateur._brique_base` (fonction PARTAGÉE, pas restaurée entre tests → pollution).
    monkeypatch.setattr(mail_proxy, "_base", lambda: "http://mail")
    monkeypatch.setattr(mail_proxy, "httpx", type("_H", (), {"AsyncClient": _FakeClient}))


def test_racine_injecte_le_prefixe_et_reecrit_purify(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/mail-app/", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert "window.MAIL_API_BASE='/mail-app';" in r.text
    assert 'src="/mail-app/static/purify.min.js"' in r.text


def test_identite_de_session_forwardee_pas_celle_du_navigateur(monkeypatch):
    _setup(monkeypatch)
    # Le navigateur tente de se faire passer pour une autre clé de service : ignorée, la
    # clé forwardée reste TOUJOURS MAIL_KEY (posée côté serveur par _entetes_brique).
    r = client.get("/mail-app/mail", headers={
        "X-User-Id": "claire", "X-API-Key": "cle-volee-par-le-navigateur",
    })
    assert r.status_code == 200
    methode, url, entetes = APPELS[-1]
    assert url == "http://mail/mail"
    assert entetes["X-User-Id"] == "claire"
    assert entetes["X-API-Key"] == "cle-coeur-mail"


def test_deux_personnes_appels_distincts(monkeypatch):
    _setup(monkeypatch)
    client.get("/mail-app/mail", headers={"X-User-Id": "claire"})
    client.get("/mail-app/mail", headers={"X-User-Id": "marina"})
    identites = [e["X-User-Id"] for _, _, e in APPELS]
    assert identites == ["claire", "marina"]
