"""Vérification proactive GeoHub (S160) — nouveautés de veille → pastille 🔔.

Autonome : aucun réseau. Base des rappels redirigée vers un dossier temporaire,
client HTTP substitué (faux AsyncClient). On vérifie : rappel créé quand la brique
annonce des nouveautés, dédoublonnage du jour, silence si la brique est absente ou
en erreur.
"""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

_TMP = tempfile.mkdtemp()
os.environ["RAPPELS_DB"] = os.path.join(_TMP, "rappels_geo.db")
sys.path.insert(0, os.path.dirname(__file__))

import proactif  # noqa: E402

# Sous pytest, un autre module peut avoir importé proactif AVANT nous (DB figée au
# défaut /data, illisible hors Docker) : on repointe l'attribut du module — `_conn()`
# relit le global à chaque appel, l'ordre d'import ne compte plus.
proactif.DB = os.environ["RAPPELS_DB"]

REGISTRE = SimpleNamespace(briques={"geo": {"port": 6110}})
REGISTRE_VIDE = SimpleNamespace(briques={})


def _reset():
    # `proactif.DB` (et non l'env) : sous pytest, un autre module de test peut avoir
    # importé proactif AVANT nous — c'est sa valeur figée qui fait foi.
    if os.path.exists(proactif.DB):
        os.remove(proactif.DB)
    proactif.init_db()


class _FauxClient:
    """Remplace httpx.AsyncClient : renvoie une réponse figée, sans réseau."""
    def __init__(self, status_code=200, corps=None):
        self._status = status_code
        self._corps = corps or {}

    def __call__(self, *a, **k):   # httpx.AsyncClient(timeout=10) → self
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **k):
        return SimpleNamespace(status_code=self._status, json=lambda: self._corps)


def _run(coro):
    return asyncio.run(coro)


def test_nouveautes_creent_un_rappel(monkeypatch):
    _reset()
    corps = {"nouveautes": [{"metadata": {"nom": "Boulangerie du Pont"}},
                            {"metadata": {"nom": "Garage de la Gare"}}]}
    monkeypatch.setattr(proactif.httpx, "AsyncClient", _FauxClient(corps=corps))
    assert _run(proactif._check_geo(REGISTRE)) == 1
    rappels = [r for r in proactif.lister() if r["type"] == "geo"]
    assert len(rappels) == 1
    assert "2 nouveauté(s)" in rappels[0]["titre"]
    assert "Boulangerie du Pont" in rappels[0]["corps"]


def test_dedoublonnage_un_seul_rappel_par_jour(monkeypatch):
    _reset()
    corps = {"nouveautes": [{"metadata": {"nom": "X"}}]}
    monkeypatch.setattr(proactif.httpx, "AsyncClient", _FauxClient(corps=corps))
    assert _run(proactif._check_geo(REGISTRE)) == 1
    assert _run(proactif._check_geo(REGISTRE)) == 0   # même clé datée, non lue
    assert len([r for r in proactif.lister() if r["type"] == "geo"]) == 1


def test_sans_nouveaute_pas_de_rappel(monkeypatch):
    _reset()
    monkeypatch.setattr(proactif.httpx, "AsyncClient",
                        _FauxClient(corps={"nouveautes": []}))
    assert _run(proactif._check_geo(REGISTRE)) == 0
    assert not [r for r in proactif.lister() if r["type"] == "geo"]


def test_brique_absente_ou_en_erreur_reste_silencieux(monkeypatch):
    _reset()
    # Brique non déclarée au registre → 0, sans lever.
    assert _run(proactif._check_geo(REGISTRE_VIDE)) == 0
    # Brique déclarée mais en erreur HTTP → 0, sans lever.
    monkeypatch.setattr(proactif.httpx, "AsyncClient", _FauxClient(status_code=503))
    assert _run(proactif._check_geo(REGISTRE)) == 0
    assert not [r for r in proactif.lister() if r["type"] == "geo"]
