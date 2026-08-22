"""Câblage de config_tenant dans le chemin de chat (assistant.converser, S234-veille
chantier 3) : le tour de conversation résout la config via le tenant courant
(contexte_tenant), pas via config_assistant.charger() en dur.

Autonome, même harnais que test_converser_stream.py (llm_pipeline doublé).
    $ cd core && python3 test_converser_config_tenant.py
    $ cd core && python3 -m pytest test_converser_config_tenant.py -v
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ["STREAM_ACTIF"] = "1"    # même chemin que test_converser_stream.py (éprouvé)
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "modele.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import config_assistant  # noqa: E402
import config_tenant  # noqa: E402
import contexte_tenant  # noqa: E402
import llm_pipeline  # noqa: E402


def test_converser_resout_avec_le_tenant_courant():
    appels = []

    async def faux_resoudre(org_id, utilisateur, client=None):
        appels.append((org_id, utilisateur))
        return config_assistant.charger()

    async def faux_flux(*a, **k):
        yield {"type": "fin", "message": {"role": "assistant", "content": "salut"},
               "resultat": None}

    jetons = contexte_tenant.definir_contexte(utilisateur="alice", org_id="acme")
    ancien_resoudre, ancien_flux = config_tenant.resoudre, llm_pipeline.completer_flux
    config_tenant.resoudre, llm_pipeline.completer_flux = faux_resoudre, faux_flux
    try:
        async def go():
            return [e async for e in
                    assistant.converser([{"role": "user", "content": "salut"}], registre=None)]
        asyncio.run(go())
    finally:
        config_tenant.resoudre, llm_pipeline.completer_flux = ancien_resoudre, ancien_flux
        contexte_tenant.reinitialiser(jetons)

    assert appels == [("acme", "alice")]


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
