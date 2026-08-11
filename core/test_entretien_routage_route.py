"""S228 — quand un entretien est actif pour (fil, personne), le tour de chat est routé
directement vers Forge au lieu du LLM habituel. Teste la fonction extraite, pas tout le
serveur HTTP/SSE (cf. convention test_assistant_routes.py / test_gate_action_bout_en_bout.py)."""
import asyncio
import os
import sys

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")
sys.path.insert(0, os.path.dirname(__file__))

import entretien_routage  # noqa: E402
from routers.assistant import _flux_entretien  # noqa: E402


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def test_flux_entretien_emet_texte_puis_fin():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Et les fournisseurs ?", "statut": "en_cours"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    types = [e["type"] for e in evts]
    assert types == ["texte", "fin"]
    assert evts[0]["contenu"] == "Et les fournisseurs ?"


def test_flux_entretien_sur_cloture_naturelle():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="Terminé.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert evts[0]["type"] == "texte"
    assert "terminé" in evts[0]["contenu"].lower() or "termine" in evts[0]["contenu"].lower()
    assert evts[-1]["type"] == "fin"


def test_flux_entretien_forge_indisponible_ne_leve_pas():
    """Si Forge est injoignable (timeout/exception réseau), `_flux_entretien` ne doit PAS
    laisser l'exception remonter et casser le flux SSE — elle dégrade proprement."""
    class _FakeClientEnPanne:
        async def post(self, url, **kw):
            raise RuntimeError("connexion refusée")

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClientEnPanne(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert evts[-1]["type"] in ("fin", "erreur")
    assert any(e["type"] in ("texte", "erreur") for e in evts)


def test_flux_entretien_forge_reponse_malformee_ne_leve_pas():
    """Un 200 dont le corps n'est pas du JSON valide (`.json()` lève) doit aussi dégrader,
    pas planter le générateur."""
    class _FakeRespMalformee:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeRespMalformee()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert evts[-1]["type"] in ("fin", "erreur")
    assert any(e["type"] in ("texte", "erreur") for e in evts)
