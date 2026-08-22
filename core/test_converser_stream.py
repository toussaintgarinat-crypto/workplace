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
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "modele.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402
import httpx  # noqa: E402
import json  # noqa: E402
import journal_modele  # noqa: E402


async def _converser(messages, fil=None):
    return [evt async for evt in assistant.converser(messages, registre=None, fil=fil)]


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


def _sse(*chunks) -> bytes:
    corps = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    return corps.encode()


def test_converser_journalise_chaque_appel_dans_journal_modele(monkeypatch):
    """Bout-en-bout (assistant → llm_pipeline RÉEL → journal_modele), sans mocker
    completer_flux lui-même : un tour à 2 itérations (1 tool call puis 1 réponse finale)
    produit exactement 2 lignes dans journal_modele, sous le fil d'accord S222."""
    tours_restants = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {
                "name": "liste_entreprises", "arguments": "{}"}}]}}]}),
        _sse({"choices": [{"delta": {"content": "Voici le bilan."}}]}),
    ]

    def handler(req):
        # `converser()` fait d'autres requêtes HTTP avant même d'atteindre la boucle LLM
        # (ex. `config_assistant.chaine_modeles()` → `lister_modeles()` sonde `/v1/models`,
        # gatée par `cascade_auto`, vraie par défaut) : ne consommer les tours SSE que sur
        # l'endpoint completions réel, sous peine de vider `tours_restants` pour la mauvaise
        # requête.
        if not str(req.url).endswith("/v1/chat/completions"):
            return httpx.Response(404)
        return httpx.Response(200, content=tours_restants.pop(0))

    # Capture la classe RÉELLE avant patch : le patch ci-dessous remplace l'attribut
    # `httpx.AsyncClient` — y référer *dans* le lambda recréerait le lambda lui-même
    # (récursion infinie), d'où la capture par fermeture ici.
    AsyncClientReel = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: AsyncClientReel(transport=httpx.MockTransport(handler)))

    async def faux_exec(nom, args, registre):
        return '{"entreprises": []}'

    ancien_exec = outils.executer
    outils.executer = faux_exec
    try:
        asyncio.run(_converser(
            [{"role": "user", "content": "où en sont les entreprises ?"}], fil="fil-e2e"))
    finally:
        outils.executer = ancien_exec

    appels = journal_modele.appels("fil-e2e")
    assert len(appels) == 2, appels
    assert appels[0]["message_recu"]["tool_calls"][0]["function"]["name"] == "liste_entreprises"
    assert appels[1]["message_recu"]["content"] == "Voici le bilan."


if __name__ == "__main__":
    import inspect

    reussis, sautes = [], []
    for nom, fn in sorted(globals().items()):
        if not (nom.startswith("test_") and callable(fn)):
            continue
        # Inspection de signature AVANT l'appel — pas un `except TypeError` après coup, qui
        # avalerait aussi un vrai TypeError levé PENDANT le corps d'un test (bug réel). Un
        # test qui déclare des paramètres (fixture pytest, ex. `monkeypatch`) est sauté
        # explicitement ; un test sans paramètre qui lève doit continuer à faire planter
        # le lanceur (revue finale S234, point 4).
        if inspect.signature(fn).parameters:
            print(f"  ⊘ {nom} (sauté, nécessite pytest)")
            sautes.append(nom)
            continue
        fn()
        print(f"  ✓ {nom}")
        reussis.append(nom)

    if sautes:
        print(f"\n✅ {len(reussis)}/{len(reussis) + len(sautes)} tests exécutés directement "
              f"passent ({len(sautes)} sautés, nécessitent pytest — lance "
              f"`pytest {os.path.basename(__file__)}` pour les inclure)")
    else:
        print(f"\n✅ TOUS LES TESTS PASSENT ({len(reussis)}/{len(reussis)})")
