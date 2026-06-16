"""Validation du branchement « Muscle déporté » (roadmap S58b).

Autonome : aucune dépendance pytest ni vraie brique calcul (on simule l'HTTP via
httpx.MockTransport, et on isole la config dans un fichier temporaire).
    $ cd core && python3 test_muscle.py
"""
import asyncio
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(_tmp, "assistant_config.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")   # config_assistant l'exige à l'import
sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import config_assistant  # noqa: E402
import muscle  # noqa: E402


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── Config opt-in ─────────────────────────────────────────────────────────────
def test_config_muscle_persiste():
    assert config_assistant.charger()["muscle_actif"] is False     # défaut : off
    config_assistant.definir_muscle(True)
    assert config_assistant.charger()["muscle_actif"] is True
    config_assistant.definir_muscle(False)
    assert config_assistant.charger()["muscle_actif"] is False


# ── tete_de_cascade ─────────────────────────────────────────────────────────--
def test_tete_de_cascade_muscle_pret():
    def h(req):
        assert req.url.path == "/muscle"
        assert req.url.params.get("reveiller") == "0"              # ne réveille jamais ici
        return httpx.Response(200, json={"disponible": True, "modele_gateway": "ollama/llama3.3"})

    async def go():
        async with _client(h) as c:
            return await muscle.tete_de_cascade(c)
    assert asyncio.run(go()) == "ollama/llama3.3"


def test_tete_de_cascade_aucun_muscle():
    def h(req):
        return httpx.Response(200, json={"disponible": False, "noeuds": []})

    async def go():
        async with _client(h) as c:
            return await muscle.tete_de_cascade(c)
    assert asyncio.run(go()) is None


def test_tete_de_cascade_brique_injoignable():
    def h(req):
        raise httpx.ConnectError("refused", request=req)

    async def go():
        async with _client(h) as c:
            return await muscle.tete_de_cascade(c)
    assert asyncio.run(go()) is None                                # best-effort, jamais d'exception


# ── état (dashboard / ⚙ Cerveau) ───────────────────────────────────────────--
def test_etat_noeuds():
    def h(req):
        assert req.url.path == "/noeuds"
        return httpx.Response(200, json={"noeuds": [{"id": "muscle", "etat": "endormi"}]})

    async def go():
        async with _client(h) as c:
            return await muscle.etat(c)
    res = asyncio.run(go())
    assert res["brique_joignable"] is True
    assert res["noeuds"][0]["id"] == "muscle"


def test_etat_brique_absente():
    def h(req):
        raise httpx.ConnectError("refused", request=req)

    async def go():
        async with _client(h) as c:
            return await muscle.etat(c)
    res = asyncio.run(go())
    assert res["brique_joignable"] is False and res["noeuds"] == []


# ── prepend en tête de cascade (logique branchée dans assistant.py) ───────────
def test_prepend_tete_dedup():
    # Reproduit l'insertion : le muscle passe en tête, sans doublon ni perte d'ordre.
    modeles = ["free/a", "ollama/llama3.3", "deepseek/deepseek-v4-flash"]
    tete = "ollama/llama3.3"
    resultat = [tete] + [m for m in modeles if m != tete]
    assert resultat == ["ollama/llama3.3", "free/a", "deepseek/deepseek-v4-flash"]


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
