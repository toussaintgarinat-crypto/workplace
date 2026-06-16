"""Validation du branchement streaming dans `assistant.converser` (S60).

Autonome : on remplace `llm_pipeline.completer_flux` et `outils.executer` par des
doublures, pour prouver que converser (1) émet bien des `texte_delta` au fil de l'eau et
(2) garde la boucle d'outils intacte en streaming.
    $ cd core && python3 test_converser_stream.py
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


async def _converser(messages):
    return [evt async for evt in assistant.converser(messages, registre=None)]


def test_converser_streame_texte():
    async def faux_flux(*a, **k):
        for frag in ("Bon", "jour"):
            yield {"type": "delta", "contenu": frag}
        yield {"type": "fin", "message": {"role": "assistant", "content": "Bonjour"},
               "resultat": None}

    ancien = llm_pipeline.completer_flux
    llm_pipeline.completer_flux = faux_flux
    try:
        evts = asyncio.run(_converser([{"role": "user", "content": "salut"}]))
    finally:
        llm_pipeline.completer_flux = ancien
    types = [e["type"] for e in evts]
    assert types == ["texte_delta", "texte_delta", "fin"], types
    assert "".join(e["contenu"] for e in evts if e["type"] == "texte_delta") == "Bonjour"
    assert not [e for e in evts if e["type"] == "texte"]        # pas de texte « en bloc » en streaming


def test_converser_boucle_outils_en_streaming():
    # 1er tour : le modèle demande un outil ; 2e tour : il répond en texte streamé.
    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "liste_entreprises", "arguments": "{}"}}]}, "resultat": None}],
        [{"type": "delta", "contenu": "Voici "},
         {"type": "delta", "contenu": "le bilan."},
         {"type": "fin", "message": {"role": "assistant", "content": "Voici le bilan."},
          "resultat": None}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        return '{"entreprises": []}'

    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        evts = asyncio.run(_converser([{"role": "user", "content": "où en sont les entreprises ?"}]))
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec
    types = [e["type"] for e in evts]
    assert "outil" in types and "resultat_outil" in types, types
    # Le texte du 2e tour est bien streamé après l'outil, puis fin.
    assert types[-1] == "fin"
    assert "".join(e["contenu"] for e in evts if e["type"] == "texte_delta") == "Voici le bilan."
    outil = [e for e in evts if e["type"] == "outil"][0]
    assert outil["nom"] == "liste_entreprises"


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
