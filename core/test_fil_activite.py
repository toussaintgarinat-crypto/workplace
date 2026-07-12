"""Tests du fil d'activité (S165) — les évènements SSE portent brique + statut.

Offline, calqué sur test_converser_stream : doublures de `llm_pipeline.completer_flux`
et `outils.executer`, et un faux registre pour la brique d'origine.
    $ cd core && python3 test_fil_activite.py
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ["STREAM_ACTIF"] = "1"
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "geo": {"nom": "geo", "port": 6110, "capacites": [
        {"nom": "geo_zones", "chemin": "/zones", "description": "Zones de veille."}]},
})


def _tour_outil(nom_outil, resultat_outil):
    """Fabrique les doublures : 1er tour = appel d'outil, 2e tour = réponse texte."""
    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": nom_outil, "arguments": "{}"}}]}, "resultat": None}],
        [{"type": "fin", "message": {"role": "assistant", "content": "Fait."}, "resultat": None}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        return resultat_outil

    return faux_flux, faux_exec


def _converser(registre):
    async def _run():
        return [evt async for evt in assistant.converser(
            [{"role": "user", "content": "vas-y"}], registre)]
    return asyncio.run(_run())


def _avec_doublures(faux_flux, faux_exec, registre):
    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        return _converser(registre)
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec


def test_brique_de():
    # Capacité de manifest → sa brique ; outil en dur ou inconnu → « cœur ».
    assert outils.brique_de("geo_zones", REGISTRE) == "geo"
    assert outils.brique_de("lister_entreprises", REGISTRE) == "cœur"
    assert outils.brique_de("outil_fantome", REGISTRE) == "cœur"


def test_evenement_outil_porte_la_brique():
    faux_flux, faux_exec = _tour_outil("geo_zones", '{"zones": []}')
    evts = _avec_doublures(faux_flux, faux_exec, REGISTRE)
    outil = next(e for e in evts if e["type"] == "outil")
    assert outil["brique"] == "geo"


def test_resultat_ok_quand_l_outil_reussit():
    faux_flux, faux_exec = _tour_outil("geo_zones", '{"zones": []}')
    evts = _avec_doublures(faux_flux, faux_exec, REGISTRE)
    res = next(e for e in evts if e["type"] == "resultat_outil")
    assert res["ok"] is True


def test_resultat_ko_quand_l_outil_echoue():
    faux_flux, faux_exec = _tour_outil("geo_zones", "Brique injoignable (geo)")
    evts = _avec_doublures(faux_flux, faux_exec, REGISTRE)
    res = next(e for e in evts if e["type"] == "resultat_outil")
    assert res["ok"] is False


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
