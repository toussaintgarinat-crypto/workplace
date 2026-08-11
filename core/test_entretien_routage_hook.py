"""S228 — quand le LLM appelle `forge_entretien_demarrer` avec succès, le Cœur active le
routage structurel pour ce fil. Offline, calqué sur test_gate_action_bout_en_bout.py."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import entretien_routage  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "forge": {"nom": "forge", "port": 8600, "capacites": [
        {"nom": "forge_entretien_demarrer", "chemin": "/ventures/{id}/entretien/demarrer",
         "methode": "POST", "action": True, "description": "Démarre l'entretien.",
         "params": {"id": {"type": "string", "requis": True}}},
    ]},
})


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def _jouer(appel_nom, appel_args_json, resultat_outil, fil="fil-test"):
    import accord_action
    import json as _json
    args = _json.loads(appel_args_json)
    accord_action.REGISTRE.demander(fil, appel_nom, {k: v for k, v in args.items() if k != "confirme"})
    accord_action.REGISTRE.tour_utilisateur(fil, "oui vas-y")

    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": appel_nom, "arguments": appel_args_json}}]}}],
        [{"type": "fin", "message": {"role": "assistant", "content": "C'est parti."}}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        return resultat_outil

    async def _run():
        return [evt async for evt in assistant.converser(
            [{"role": "user", "content": "Auditons l'entreprise X"}], REGISTRE, fil=fil)]

    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        return asyncio.run(_run())
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec


def test_demarrer_reussi_active_le_registre():
    resultat = '{"id": "e1", "ventureId": "venture-1", "sectionCourante": "qualitatif.organisation", "question": "...", "rappel": null, "statut": "en_cours"}'
    _jouer("forge_entretien_demarrer",
           '{"id": "venture-1", "confirme": true}', resultat, fil="fil-test")
    assert entretien_routage.REGISTRE.actif("fil-test") == "venture-1"


def test_demarrer_en_echec_n_active_rien():
    _jouer("forge_entretien_demarrer",
           '{"id": "venture-1", "confirme": true}',
           '{"erreur": "Brique injoignable"}', fil="fil-echec")
    assert entretien_routage.REGISTRE.actif("fil-echec") is None
