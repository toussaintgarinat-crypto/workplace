"""S178 Task C6 — l'horloge du Cœur déclenche le digest agenda (`_check_digest`).

Autonome : aucun réseau. L'agenda no-op si ce n'est pas l'heure / déjà envoyé —
appeler à chaque tick proactif est donc sûr et idempotent côté Cœur ; `_check_digest`
lui-même ne fait qu'un POST best-effort et renvoie toujours 0 (le digest n'alimente
pas le magasin de rappels, contrairement à `_check_agenda`/`_check_geo`).
"""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

_TMP = tempfile.mkdtemp()
os.environ["RAPPELS_DB"] = os.path.join(_TMP, "rappels_digest.db")
sys.path.insert(0, os.path.dirname(__file__))

import proactif  # noqa: E402

REGISTRE = SimpleNamespace(briques={"agenda": {"port": 6100}})


class _FauxClient:
    """Remplace httpx.AsyncClient : capture l'appel POST, sans réseau."""
    def __init__(self):
        self.appels = []  # liste de (url, headers)

    def __call__(self, *a, **k):   # httpx.AsyncClient(timeout=15) → self
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **k):
        self.appels.append((url, k.get("headers") or {}))
        return SimpleNamespace(status_code=200, json=lambda: {})


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_check_digest_appelle_agenda(monkeypatch):
    monkeypatch.setenv("DIGEST_KEY", "dk")
    monkeypatch.setattr(proactif.orchestrateur, "_brique_base",
                        lambda registre, nom: "http://agenda")
    faux = _FauxClient()
    monkeypatch.setattr(proactif.httpx, "AsyncClient", faux)

    n = _run(proactif._check_digest(REGISTRE))

    assert n == 0
    assert len(faux.appels) == 1
    url, headers = faux.appels[0]
    assert url.endswith("/digests/executer")
    assert headers.get("X-API-Key") == "dk"


def test_check_digest_sans_cle_ne_fait_aucun_appel(monkeypatch):
    monkeypatch.delenv("DIGEST_KEY", raising=False)
    monkeypatch.setattr(proactif.orchestrateur, "_brique_base",
                        lambda registre, nom: "http://agenda")
    faux = _FauxClient()
    monkeypatch.setattr(proactif.httpx, "AsyncClient", faux)

    n = _run(proactif._check_digest(REGISTRE))

    assert n == 0
    assert faux.appels == []


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
