"""S243 — la santé distingue « endormie volontairement » de « en panne », l'horloge réveille
avant d'appeler une tâche, et la boucle de balayage ne plante jamais le Cœur.

$ cd core && python3 -m pytest test_sommeil_sante.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import httpx  # noqa: E402
import pytest  # noqa: E402

import horloge  # noqa: E402
import sommeil  # noqa: E402
from routers import systeme  # noqa: E402
from test_sommeil import FauxDocker, Registre  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _registre():
    return Registre({
        "geo": {"famille": "veille", "url_sante": "http://h:6110/sante", "port": 6110,
                "sommeil": {"conteneurs": ["workplace_geo"]}},
        "calcul": {"famille": "metier", "url_sante": "http://h:5990/sante", "port": 5990},
    })


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    sommeil._ACTIVITE.clear()
    monkeypatch.setattr(sommeil, "PAS_ATTENTE_S", 0.0)
    monkeypatch.setattr(sommeil, "ACTIF", True)
    d = FauxDocker({"workplace_geo": {"running": False, "sante": None}})
    sommeil.definir_backend(d)
    yield d
    sommeil.definir_backend(None)
    sommeil._ACTIVITE.clear()


class _FauxClient:
    """Remplace httpx.AsyncClient : toute URL « h:… » répond 200, sauf celles en `pannes`."""
    appels: list = []
    pannes: set = set()

    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, url, **k):
        _FauxClient.appels.append(url)
        if url in _FauxClient.pannes:
            raise httpx.ConnectError("refusé")
        return httpx.Response(200, request=httpx.Request("GET", url))

    async def request(self, methode, url, **k):
        return await self.get(url)


@pytest.fixture
def faux_http(monkeypatch):
    _FauxClient.appels, _FauxClient.pannes = [], set()
    monkeypatch.setattr(httpx, "AsyncClient", _FauxClient)
    return _FauxClient


# ── /sante-globale ───────────────────────────────────────────────────────────

def test_sante_globale_dit_endormie_et_ne_pingue_pas_une_brique_qui_dort(monkeypatch, faux_http):
    monkeypatch.setattr(systeme, "registre", _registre())
    out = run(systeme.sante_globale())["briques"]
    assert out["geo"]["statut"] == "endormie"
    assert "http://h:6110/sante" not in faux_http.appels      # pas de ping inutile
    assert out["calcul"]["statut"] == "ok"                    # les autres : inchangé


def test_sante_globale_une_brique_eveillee_est_pingue_normalement(monkeypatch, faux_http, _isoler):
    _isoler.c["workplace_geo"].update(running=True, sante="healthy")
    monkeypatch.setattr(systeme, "registre", _registre())
    assert run(systeme.sante_globale())["briques"]["geo"]["statut"] == "ok"


def test_sante_globale_une_brique_eveillee_en_panne_reste_inaccessible(monkeypatch, faux_http, _isoler):
    # Le conteneur tourne mais ne répond pas : c'est une PANNE, pas un sommeil.
    _isoler.c["workplace_geo"].update(running=True, sante="healthy")
    faux_http.pannes = {"http://h:6110/sante"}
    monkeypatch.setattr(systeme, "registre", _registre())
    assert run(systeme.sante_globale())["briques"]["geo"]["statut"] == "inaccessible"


def test_sante_globale_conteneur_introuvable_n_est_pas_presente_comme_endormie(monkeypatch, faux_http, _isoler):
    del _isoler.c["workplace_geo"]
    faux_http.pannes = {"http://h:6110/sante"}
    monkeypatch.setattr(systeme, "registre", _registre())
    assert run(systeme.sante_globale())["briques"]["geo"]["statut"] == "inaccessible"


# ── horloge : réveil avant une tâche planifiée ───────────────────────────────

def test_l_horloge_reveille_la_brique_avant_d_appeler_sa_tache(monkeypatch, faux_http, _isoler):
    enregistre = []
    monkeypatch.setattr(horloge, "_enregistrer", lambda *a, **k: enregistre.append(k))
    reg = _registre()
    tache = {"brique": "geo", "nom": "ingestion-quotidienne", "methode": "POST",
             "chemin": "/ingestion", "_registre": reg, "cadence_heures": 24}
    monkeypatch.setattr(horloge.orchestrateur, "_brique_base", lambda registre, nom: "http://h:6110")
    res = run(horloge._executer(_FauxClient(), tache, horloge.datetime.utcnow()))
    assert res["statut"] == "ok" and _isoler.demarres == ["workplace_geo"]


def test_l_horloge_note_un_echec_de_reveil_sans_planter(monkeypatch, faux_http, _isoler):
    enregistre = []
    monkeypatch.setattr(horloge, "_enregistrer", lambda *a, **k: enregistre.append(k))
    _isoler.demarrage_lent = 10_000
    monkeypatch.setattr(sommeil, "ATTENTE_DEFAUT_S", 0.05)
    tache = {"brique": "geo", "nom": "t", "methode": "POST", "chemin": "/x",
             "_registre": _registre(), "cadence_heures": 24}
    monkeypatch.setattr(horloge.orchestrateur, "_brique_base", lambda registre, nom: "http://h:6110")
    res = run(horloge._executer(_FauxClient(), tache, horloge.datetime.utcnow()))
    assert res["statut"] == "indisponible" and "réveill" in res["detail"].lower()


# ── boucle de balayage ───────────────────────────────────────────────────────

def test_la_boucle_survit_a_une_erreur_de_balayage(monkeypatch):
    appels = {"n": 0}

    async def balayer_qui_plante(registre, maintenant=None):
        appels["n"] += 1
        raise RuntimeError("docker muet")

    async def faux_sleep(_s):
        if appels["n"] >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(sommeil, "balayer", balayer_qui_plante)
    monkeypatch.setattr(sommeil.asyncio, "sleep", faux_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(sommeil.boucle(_registre()))
    assert appels["n"] == 2     # elle a continué après la première erreur
