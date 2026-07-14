"""Outils TimeTree de l'assistant + agrégation multi-calendriers de l'agenda.

Sans réseau : on stube `agenda.*`. Vérifie que les outils sont déclarés, que connecter/
déconnecter sont GARDÉS (confirmation), que la synchro appelle bien la brique, que les
identifiants ne fuitent jamais dans la réponse de l'outil, et que `lister_evenements`
agrège les événements de TOUS les calendriers (perso + TimeTree).
    $ cd core && python3 test_timetree_outils.py
"""
import asyncio
import json
import os

os.environ.setdefault("GATEWAY_KEY", "test")

import agenda  # noqa: E402
import outils  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


NOMS = {o["function"]["name"] for o in outils.OUTILS}


def test_outils_timetree_declares():
    attendus = {"timetree_etat", "timetree_connecter", "timetree_choisir_calendrier",
                "timetree_synchroniser", "timetree_deconnecter"}
    assert attendus <= NOMS


def test_actions_timetree_gardees():
    assert {"timetree_connecter", "timetree_deconnecter"} <= outils.OUTILS_ACTION
    for libre in ("timetree_etat", "timetree_synchroniser", "timetree_choisir_calendrier"):
        assert libre not in outils.OUTILS_ACTION


def test_synchroniser_appelle_la_brique(monkeypatch=None):
    async def faux_sync(registre):
        return {"ok": True, "created": 3, "updated": 1, "fetched": 4}
    agenda.timetree_synchroniser = faux_sync
    out = json.loads(_run(outils.executer("timetree_synchroniser", {}, None)))
    assert out["ok"] is True and out["created"] == 3


def test_connecter_gate_puis_sans_fuite():
    # Sans confirme → confirmation demandée, la brique n'est PAS appelée.
    appels = []
    async def faux_connect(registre, email, password, calendar_id=None):
        appels.append((email, password))
        return {"connected": True, "calendars": [{"id": "1", "name": "Famille"}], "calendar_id": None}
    agenda.timetree_connecter = faux_connect

    r1 = json.loads(_run(outils.executer("timetree_connecter",
                    {"email": "me@x.fr", "password": "secret"}, None)))
    assert r1.get("confirmation_requise") is True
    assert appels == []

    # Avec confirme → appelle la brique, renvoie les calendriers, JAMAIS le mot de passe.
    r2 = json.loads(_run(outils.executer("timetree_connecter",
                    {"email": "me@x.fr", "password": "secret", "confirme": True}, None)))
    assert r2["connected"] is True and r2["calendriers"][0]["name"] == "Famille"
    assert "secret" not in json.dumps(r2)


def test_deconnecter_gate():
    async def faux_deco(registre):
        return True
    agenda.timetree_deconnecter = faux_deco
    r1 = json.loads(_run(outils.executer("timetree_deconnecter", {}, None)))
    assert r1.get("confirmation_requise") is True
    r2 = json.loads(_run(outils.executer("timetree_deconnecter", {"confirme": True}, None)))
    assert r2["deconnecte"] is True


# ── Délégation de lister_evenements vers la surface /service (S168) ───────────
# L'agrégation multi-calendriers + la jointure étiquette/couleur vivent DÉSORMAIS dans la
# brique (surface /service/events, testée dans briques/agenda) : côté Cœur, le client ne
# fait plus qu'un GET et renvoie le payload déjà enrichi. On vérifie ici cette délégation.

class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._p = payload
    def json(self):
        return self._p


class _FakeClient:
    """Stub httpx.AsyncClient : /service/events → payload déjà agrégé + enrichi par la brique."""
    dernier = {}

    def __init__(self, *a, **k):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, headers=None, params=None):
        _FakeClient.dernier = {"url": url, "params": params}
        if url.endswith("/service/events"):
            return _Resp([
                {"id": "e1", "title": "Perso RDV", "calendrier": "Perso", "couleur": "#fff"},
                {"id": "e2", "title": "Marina", "calendrier": "TimeTree", "couleur": "#4CD2C0"},
            ])
        return _Resp([])


def test_lister_evenements_delegue_a_service():
    agenda._base = lambda registre: "http://agenda"
    agenda.httpx.AsyncClient = _FakeClient
    evts = _run(agenda.lister_evenements(None, "2026-07-14T00:00:00", "2026-07-21T00:00:00"))
    # Un seul appel, vers la surface agrégée de la brique, avec les bornes en params.
    assert _FakeClient.dernier["url"] == "http://agenda/service/events"
    assert _FakeClient.dernier["params"] == {"debut": "2026-07-14T00:00:00", "fin": "2026-07-21T00:00:00"}
    # Le payload enrichi par la brique est renvoyé tel quel (calendrier + couleur préservés).
    titres = {e["title"] for e in evts}
    assert titres == {"Perso RDV", "Marina"}
    marina = next(e for e in evts if e["title"] == "Marina")
    assert marina["calendrier"] == "TimeTree" and marina["couleur"] == "#4CD2C0"


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
