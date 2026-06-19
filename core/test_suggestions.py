"""Actions suggérées — boutons d'action génériques (S76).

Deux niveaux : (1) le module `suggestions` propose Confirmer/Annuler sur une confirmation
en attente et RIEN sinon ; (2) `assistant.converser` émet bien un évènement SSE `actions`
juste après un résultat d'outil en attente de confirmation — la matière des boutons côté
front (dashboard web + Mini App). Autonome : LLM et outil doublés.
    $ cd core && python3 test_suggestions.py
"""
import asyncio
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(_TMP, "cfg.json")
# Stores d'auto-amélioration en tmp : assistant importe amelioration (addendum_actif) ;
# on n'écrit jamais dans /data, même si ce fichier de test est importé en premier.
os.environ.setdefault("AMELIORATION_PATH", os.path.join(_TMP, "amel.json"))
os.environ.setdefault("PROPRIOCEPTION_PATH", os.path.join(_TMP, "proprio.jsonl"))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ["STREAM_ACTIF"] = "1"
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402
import suggestions  # noqa: E402


# ── Unité : le mécanisme générique ───────────────────────────────────────────
def test_confirmation_propose_confirmer_annuler():
    acts = suggestions.pour_resultat("curateur_lancer", {}, "{...}", confirmation=True)
    labels = [a["label"] for a in acts]
    assert any("Confirmer" in l for l in labels)
    assert any("Annuler" in l for l in labels)
    # Le premier bouton injecte un accord explicite → le LLM rappellera avec confirme=true.
    assert "confirme" in acts[0]["envoi"].lower()


def test_sans_confirmation_aucun_bouton():
    assert suggestions.pour_resultat("lister_entreprises", {}, "{}", confirmation=False) == []


# ── Intégration : converser émet l'évènement SSE `actions` ───────────────────
async def _converser(messages):
    return [evt async for evt in assistant.converser(messages, registre=None)]


def test_converser_emet_actions_apres_confirmation():
    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "curateur_lancer", "arguments": "{}"}}]}, "resultat": None}],
        [{"type": "delta", "contenu": "Tu confirmes ?"},
         {"type": "fin", "message": {"role": "assistant", "content": "Tu confirmes ?"},
          "resultat": None}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        # Simule le gate : l'outil renvoie une demande de confirmation.
        return '{"confirmation_requise": true, "action": "lancer un cycle de curation"}'

    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        evts = asyncio.run(_converser([{"role": "user", "content": "améliore-toi"}]))
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec
    actions = [e for e in evts if e["type"] == "actions"]
    assert actions, [e["type"] for e in evts]
    labels = [a["label"] for a in actions[0]["actions"]]
    assert any("Confirmer" in l for l in labels) and any("Annuler" in l for l in labels)
    # L'évènement `actions` suit immédiatement le `resultat_outil` (ordre attendu côté front).
    types = [e["type"] for e in evts]
    assert types.index("actions") == types.index("resultat_outil") + 1


def test_pas_d_actions_sans_outil():
    async def faux_flux(*a, **k):
        yield {"type": "delta", "contenu": "Bonjour"}
        yield {"type": "fin", "message": {"role": "assistant", "content": "Bonjour"}, "resultat": None}

    ancien = llm_pipeline.completer_flux
    llm_pipeline.completer_flux = faux_flux
    try:
        evts = asyncio.run(_converser([{"role": "user", "content": "salut"}]))
    finally:
        llm_pipeline.completer_flux = ancien
    assert not [e for e in evts if e["type"] == "actions"]


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
