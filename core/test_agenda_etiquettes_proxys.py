"""Proxys étiquettes du Cœur + enrichissement des événements (nom + couleur d'étiquette).

Sans réseau : on remplace httpx.AsyncClient du module agenda par un faux client. Vérifie
les helpers CRUD étiquettes et que lister_evenements résout l'étiquette (le nom + sa
couleur priment sur la couleur libre, repli sur la couleur du calendrier).
    $ cd core && python3 test_agenda_etiquettes_proxys.py
"""
import asyncio
import sys, os

sys.path.insert(0, os.path.dirname(__file__))
import agenda  # noqa: E402

APPELS = []


class _Resp:
    def __init__(self, payload=None, status=200):
        self._p = payload if payload is not None else {}
        self.status_code = status
        self.headers = {"content-type": "application/json"}
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
        if url.endswith("/labels"):
            return _Resp([{"id": "lab1", "name": "Famille", "color": "#ff0000"}])
        if url.endswith("/events"):
            return _Resp([
                {"id": "e1", "title": "RDV", "start_at": "2030-01-01T09:00:00", "label_id": "lab1", "color": "#abcdef"},
                {"id": "e2", "title": "Libre", "start_at": "2030-01-01T10:00:00", "label_id": None, "color": "#abcdef"},
                {"id": "e3", "title": "Vide", "start_at": "2030-01-01T11:00:00", "label_id": None, "color": None},
            ])
        if url.endswith("/calendars"):
            return _Resp([{"id": "cal1", "name": "Perso", "color": "#111111"}])
        return _Resp([])
    async def post(self, url, headers=None, json=None, files=None):
        APPELS.append(("POST", url, json))
        return _Resp({"id": "newlab", "echo": json})
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


def test_lister_etiquettes():
    _setup()
    r = _run(agenda.lister_etiquettes(None, "cal1"))
    assert ("GET", "http://agenda/calendars/cal1/labels") in APPELS
    assert r[0]["name"] == "Famille"


def test_creer_etiquette():
    _setup()
    r = _run(agenda.creer_etiquette(None, "cal1", "Boulot", "#00ff00"))
    assert ("POST", "http://agenda/calendars/cal1/labels", {"name": "Boulot", "color": "#00ff00"}) in APPELS
    assert r["id"] == "newlab"


def test_modifier_etiquette():
    _setup()
    _run(agenda.modifier_etiquette(None, "lab1", {"name": "Maison"}))
    assert ("PATCH", "http://agenda/labels/lab1", {"name": "Maison"}) in APPELS


def test_supprimer_etiquette():
    _setup()
    assert _run(agenda.supprimer_etiquette(None, "lab1")) is True
    assert ("DELETE", "http://agenda/labels/lab1") in APPELS


# NB (S168) : l'enrichissement des événements (résolution étiquette → nom + couleur, replis
# couleur libre puis couleur du calendrier) a migré du Cœur vers la brique — il est désormais
# testé dans briques/agenda/backend/tests/test_service_agenda.py (agrégation /service/events).
# Côté Cœur, `lister_evenements` ne fait qu'un GET et renvoie le payload déjà enrichi
# (délégation testée dans test_timetree_outils.py::test_lister_evenements_delegue_a_service).


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
