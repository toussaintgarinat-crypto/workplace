"""Proxys agenda du Cœur (CRUD événements + documents + commentaires).

Sans réseau : on remplace httpx.AsyncClient du module agenda par un faux client qui
enregistre les appels et renvoie des réponses canned. Vérifie que chaque helper tape
le bon contrat de la brique (méthode + chemin) et parse la réponse.
    $ cd core && python3 test_agenda_proxys.py
"""
import asyncio
import logging
import sys, os

sys.path.insert(0, os.path.dirname(__file__))
import agenda  # noqa: E402

APPELS = []


class _Resp:
    def __init__(self, payload=None, status=200, headers=None):
        self._p = payload if payload is not None else {}
        self.status_code = status
        self.headers = headers or {"content-type": "application/json"}
        self.content = b"octets"
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, headers=None, params=None):
        APPELS.append(("GET", url))
        if url.endswith("/attachments"): return _Resp([{"id": "a1", "filename": "f.pdf", "size_bytes": 2048}])
        if url.endswith("/comments"): return _Resp([{"id": "c1", "content": "salut", "created_at": "2026-06-20T10:00:00"}])
        if url.endswith("/download"): return _Resp({}, headers={"content-disposition": 'attachment; filename="f.pdf"', "content-type": "application/pdf"})
        return _Resp([])
    async def post(self, url, headers=None, json=None, files=None):
        APPELS.append(("POST", url, json, bool(files)))
        return _Resp({"id": "new", "echo": json, "files": bool(files)})
    async def patch(self, url, headers=None, json=None):
        APPELS.append(("PATCH", url, json))
        return _Resp({"id": url.rsplit("/", 1)[-1], "echo": json})
    async def delete(self, url, headers=None):
        APPELS.append(("DELETE", url))
        return _Resp({}, status=204)


def _setup():
    APPELS.clear()
    agenda._base = lambda registre: "http://agenda"
    agenda.httpx.AsyncClient = _FakeClient


def _run(c): return asyncio.new_event_loop().run_until_complete(c)


def test_creer_evenement_dans_calendrier():
    _setup()
    r = _run(agenda.creer_evenement_dans(None, "cal9", {"title": "RDV", "start_at": "x", "end_at": "y"}))
    assert ("POST", "http://agenda/calendars/cal9/events", {"title": "RDV", "start_at": "x", "end_at": "y"}, False) in APPELS
    assert r["id"] == "new"


def test_creer_agenda_partage():
    """S182b : proxy de création d'un calendrier partageable (POST /calendars)."""
    _setup()
    r = _run(agenda.creer_agenda(None, "Famille", "#22c55e"))
    assert ("POST", "http://agenda/calendars", {"name": "Famille", "color": "#22c55e"}, False) in APPELS
    assert r["id"] == "new"


def test_creer_invitation_via_service():
    """S182b : proxy d'invitation via la surface /service (qui renvoie le `lien`)."""
    _setup()
    _run(agenda.creer_invitation(None, "cal9", role="editor", expire_heures=48))
    assert ("POST", "http://agenda/service/calendars/cal9/invitations",
            {"role": "editor", "expire_heures": 48}, False) in APPELS


def test_accepter_invitation():
    """S182b : proxy d'acceptation (POST /invitations/{token}/accept) sous l'identité de session."""
    _setup()
    _run(agenda.accepter_invitation(None, "tok123"))
    assert ("POST", "http://agenda/invitations/tok123/accept", None, False) in APPELS


def test_modifier_evenement():
    _setup()
    r = _run(agenda.modifier_evenement(None, "e1", {"color": "#fff"}))
    assert ("PATCH", "http://agenda/events/e1", {"color": "#fff"}) in APPELS
    assert r["echo"] == {"color": "#fff"}


def test_documents_lister_upload_supprimer():
    _setup()
    docs = _run(agenda.lister_documents(None, "e1"))
    assert docs[0]["filename"] == "f.pdf"
    _run(agenda.televerser_document(None, "e1", "f.pdf", b"data", "application/pdf"))
    assert any(a[0] == "POST" and a[1].endswith("/events/e1/attachments") and a[3] for a in APPELS)
    assert _run(agenda.supprimer_document(None, "a1")) is True
    assert ("DELETE", "http://agenda/attachments/a1") in APPELS


def test_telecharger_document_lit_le_nom():
    _setup()
    octets, nom, mt = _run(agenda.telecharger_document(None, "a1"))
    assert octets == b"octets" and nom == "f.pdf" and mt == "application/pdf"


def test_commentaires_lister_ajouter_supprimer():
    _setup()
    cs = _run(agenda.lister_commentaires(None, "e1"))
    assert cs[0]["content"] == "salut"
    _run(agenda.ajouter_commentaire(None, "e1", "coucou"))
    assert ("POST", "http://agenda/events/e1/comments", {"content": "coucou"}, False) in APPELS
    assert _run(agenda.supprimer_commentaire(None, "c1")) is True


def test_erreur_agenda_loggee(monkeypatch, caplog):
    """Une panne de la brique agenda doit apparaître dans les logs serveur."""
    import os
    os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
    os.environ.setdefault("GATEWAY_KEY", "test")
    import main
    from fastapi.testclient import TestClient
    client_app = TestClient(main.app)

    async def _boom(*a, **k):
        raise RuntimeError("brique down")

    monkeypatch.setattr(agenda, "lister_evenements", _boom)
    with caplog.at_level(logging.WARNING, logger="core.routers.agenda"):
        resp = client_app.get("/agenda/evenements")
    assert resp.status_code == 200
    assert resp.json()["evenements"] == []
    assert "brique down" in caplog.text


def test_route_acceptation_sans_session_redirige_vers_login():
    """S182b : le lien d'invitation, ouvert sans session, renvoie au login du Cœur avec
    `next` = retour sur la route d'acceptation (login unique, pas de page côté brique)."""
    import os
    os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
    os.environ.setdefault("GATEWAY_KEY", "test")
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    r = c.get("/agenda/invitation/tok999", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/auth/login?next=")
    assert "agenda/invitation/tok999" in loc


def test_next_login_anti_open_redirect():
    """`next` post-login : chemins internes seulement (anti open-redirect)."""
    from routers.auth import _next_sur
    assert _next_sur("/agenda/invitation/x") == "/agenda/invitation/x"
    assert _next_sur("//evil.com") == "/dashboard"          # protocol-relative rejeté
    assert _next_sur("https://evil.com") == "/dashboard"    # absolu rejeté
    assert _next_sur(None) == "/dashboard"                  # absent → défaut


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
