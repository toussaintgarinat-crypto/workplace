"""Validation du pipeline d'appel LLM économe (Sprint S138, chantier 0 + trimming).

Autonome : aucune dépendance pytest ni vraie Gateway (on simule l'HTTP).
    $ cd core && python3 test_s138.py
Sortie « ✅ TOUS LES TESTS PASSENT » = parité + comptage coût + budget OK.
"""

import asyncio
import os
import sys
import tempfile

# Journal + cache isolés dans un dossier temporaire AVANT d'importer les modules.
_tmp = tempfile.mkdtemp()
os.environ["USAGE_LLM_PATH"] = os.path.join(_tmp, "usage.jsonl")
os.environ["LLM_CACHE_PATH"] = os.path.join(_tmp, "cache.jsonl")
os.environ["SHADOW_RUNS_PATH"] = os.path.join(_tmp, "shadow.jsonl")
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(_tmp, "modele.jsonl")
os.environ.setdefault("LLM_BUDGET_MOIS_USD", "0")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")  # clé factice : les modules l'exigent désormais
sys.path.insert(0, os.path.dirname(__file__))

import cache_semantique  # noqa: E402
import journal_usage  # noqa: E402
import llm_pipeline  # noqa: E402
import journal_modele  # noqa: E402
import pytest  # noqa: E402
import routage  # noqa: E402
import shadow  # noqa: E402
import summarisation  # noqa: E402
import trimming  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _journal_vierge_au_demarrage():
    """Ce fichier suppose (comme en exécution standalone) un journal d'usage VIERGE au départ,
    puis une accumulation ORDONNÉE entre ses tests (parité de coût → garde-fou budget). En suite
    complète, `journal_usage.JOURNAL_PATH` est partagé et déjà rempli par des fichiers de test
    antérieurs. On repart donc d'un journal vide une seule fois, avant les tests du module —
    l'accumulation interne (dont dépendent les tests budget) reste intacte."""
    try:
        os.remove(journal_usage.JOURNAL_PATH)
    except FileNotFoundError:
        pass
    yield


def _vecteur(texte: str) -> list[float]:
    """Embedding factice déterministe : même texte → même vecteur (cosinus = 1)."""
    base = [(hash((i, texte)) % 1000) / 1000 for i in range(8)]
    return base


class _FakeResp:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.status_code = 200
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Route selon l'URL : /v1/embeddings → vecteur, sinon complétion chat."""
    def __init__(self):
        self.appels_chat = 0

    async def post(self, url, *a, **k):
        if url.endswith("/v1/embeddings"):
            texte = (k.get("json") or {}).get("input", "")
            return _FakeResp({"data": [{"embedding": _vecteur(texte)}]})
        self.appels_chat += 1
        return _FakeResp(
            {"choices": [{"message": {"content": "bonjour", "tool_calls": None}}],
             "usage": {"prompt_tokens": 123, "completion_tokens": 45}},
            headers={"x-litellm-response-cost": "0.0042"})

    async def aclose(self):
        pass


def test_trimming():
    msgs = [{"role": "system", "content": "système"}]
    msgs += [{"role": "user", "content": f"message {i}   espaces"} for i in range(20)]
    red, eco = trimming.trim(msgs, derniers=6)
    assert red[0]["role"] == "system"
    assert sum(1 for m in red if m["role"] != "system") == 6
    assert "  " not in red[1]["content"] and eco > 0
    # Un message `tool` orphelin ne doit jamais ouvrir la fenêtre.
    msgs2 = ([{"role": "system", "content": "x"}] + [{"role": "user", "content": "a"}] * 3
             + [{"role": "tool", "content": "orphelin"}, {"role": "user", "content": "b"}])
    red2, _ = trimming.trim(msgs2, derniers=2)
    assert red2[1]["role"] != "tool"


def test_cout():
    assert llm_pipeline._cout("openai/gpt-4o-mini", 1000, 1000, None) > 0
    assert llm_pipeline._cout("free/x/y", 1000, 1000, None) == 0.0
    assert llm_pipeline._cout("openai/gpt-4o", 0, 0, "0.0123") == 0.0123  # en-tête fait foi
    assert llm_pipeline._cout("inconnu/modele", 1000, 1000, None) == 0.0


def test_noms_outils_best_effort_sur_entree_malformee():
    """`_noms_outils()` est appelée inline aux call-sites de journal_modele, AVANT le
    best-effort interne de `enregistrer_appel` : elle doit donc être défensive elle-même,
    jamais lever, quelle que soit la forme de `tools`."""
    assert llm_pipeline._noms_outils(None) == []
    assert llm_pipeline._noms_outils([]) == []
    assert llm_pipeline._noms_outils([{"function": "pas un dict"}]) == []
    assert llm_pipeline._noms_outils(["pas un dict du tout"]) == []


def test_pipeline_et_journal():
    res = asyncio.run(llm_pipeline.completer(
        [{"role": "user", "content": "salut"}],
        modeles=["openai/gpt-4o-mini"], etiquette="chat", client=_FakeClient()))
    assert res.ok and res.contenu == "bonjour"
    assert res.tokens_in == 123 and res.tokens_out == 45 and res.cout_usd == 0.0042
    r = journal_usage.resume()
    assert r["total"]["appels"] == 1 and r["total"]["tokens_in"] == 123


def test_pipeline_journalise_dans_journal_modele():
    res = asyncio.run(llm_pipeline.completer(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "salut"}],
        modeles=["openai/gpt-4o-mini"], etiquette="chat", fil="fil-test-s138",
        client=_FakeClient()))
    assert res.ok
    appels = journal_modele.appels("fil-test-s138")
    assert len(appels) == 1
    a = appels[0]
    assert a["modele"] == "openai/gpt-4o-mini"
    assert a["messages"][-1]["content"] == "salut"
    assert a["message_recu"]["content"] == "bonjour"


def test_pipeline_ne_journalise_pas_sur_hit_cache_semantique():
    """Un hit du cache sémantique ne fait atteindre AUCUN modèle ce tour-ci : pas de
    nouvelle ligne journal_modele (cf. spec, décision explicite)."""
    cli = _FakeClient()
    prompt = [{"role": "system", "content": "archiviste"},
              {"role": "user", "content": "range ce devis, encore"}]
    asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], temperature=0, etiquette="classement",
        trim_contexte=False, cache=True, fil="fil-cache-s138", client=cli))
    n_avant = len(journal_modele.appels("fil-cache-s138"))
    assert n_avant == 1  # le 1er appel (miss) a bien été journalisé
    asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], temperature=0, etiquette="classement",
        trim_contexte=False, cache=True, fil="fil-cache-s138", client=cli))
    assert len(journal_modele.appels("fil-cache-s138")) == n_avant  # hit → pas de nouvelle ligne


def test_cache_semantique():
    cli = _FakeClient()
    prompt = [{"role": "system", "content": "archiviste"},
              {"role": "user", "content": "range ce devis"}]
    # 1er appel : miss → vraie complétion + mise en cache.
    r1 = asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], temperature=0,
        etiquette="classement", trim_contexte=False, cache=True, client=cli))
    assert r1.ok and not r1.cache_hit and cli.appels_chat == 1
    # 2e appel identique : hit → 0 token, AUCUN appel chat supplémentaire.
    r2 = asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], temperature=0,
        etiquette="classement", trim_contexte=False, cache=True, client=cli))
    assert r2.ok and r2.cache_hit and r2.tokens_in == 0 and cli.appels_chat == 1
    assert r2.contenu == "bonjour"
    # Avec des outils, le cache est ignoré (effet de bord) : un 3e appel tape le chat.
    cli3 = _FakeClient()
    r3 = asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], tools=[{"function": {"name": "x"}}],
        trim_contexte=False, cache=True, client=cli3))
    assert r3.ok and not r3.cache_hit and cli3.appels_chat == 1


def test_routage():
    def msg(t):
        return [{"role": "system", "content": "s"}, {"role": "user", "content": t}]
    # Heuristiques de complexité.
    assert routage.complexite(msg("Bonjour, ça va ?")) == routage.TRIVIAL
    assert routage.complexite(msg("def f(x):\n  return x")) == routage.COMPLEXE
    assert routage.complexite(msg("x" * 700)) == routage.COMPLEXE

    conf = {"routage_actif": True, "modele_econome": "free/eco", "fallback_models": []}
    # Requête triviale, sans outils → économe préposé en tête, modèle voulu en filet.
    mods, routed, niveau = routage.router(msg("merci !"), ["openai/gpt-4o"], conf)
    assert routed == "free/eco" and mods[0] == "free/eco" and "openai/gpt-4o" in mods
    # Outils requis → jamais de rétrogradation (garde-fou function-calling).
    mods2, routed2, _ = routage.router(msg("merci !"), ["openai/gpt-4o"], conf,
                                       tools=[{"function": {"name": "x"}}])
    assert routed2 is None and mods2 == ["openai/gpt-4o"]
    # Kill-switch : routage inactif → liste inchangée.
    conf_off = {**conf, "routage_actif": False}
    mods3, routed3, _ = routage.router(msg("merci !"), ["openai/gpt-4o"], conf_off)
    assert routed3 is None and mods3 == ["openai/gpt-4o"]
    # Requête complexe → reste sur le modèle puissant même si routage actif.
    mods4, routed4, _ = routage.router(msg("x" * 700), ["openai/gpt-4o"], conf)
    assert routed4 is None and mods4 == ["openai/gpt-4o"]


def test_summarisation():
    cli = _FakeClient()
    hist = [{"role": "system", "content": "prompt système"}]
    hist += [{"role": "user", "content": f"vieux message {i}"} for i in range(10)]
    hist += [{"role": "user", "content": "question récente A"},
             {"role": "user", "content": "question récente B"}]
    conf = {"resume_actif": True, "modele_resume": "free/eco",
            "seuil_resume_tokens": 10, "resume_garder": 2, "fallback_models": []}
    out = asyncio.run(summarisation.condenser(cli, hist, conf))
    assert out[0]["role"] == "system" and out[0]["content"] == "prompt système"
    # Une note de résumé a remplacé les anciens messages.
    assert any(m["role"] == "system" and m["content"].startswith("[Résumé") for m in out)
    # Les 2 derniers tours sont préservés intacts.
    assert out[-2]["content"] == "question récente A"
    assert out[-1]["content"] == "question récente B"
    assert len(out) < len(hist)  # historique condensé
    # En deçà du seuil : aucun appel, historique inchangé.
    court = [{"role": "user", "content": "court"}]
    assert asyncio.run(summarisation.condenser(cli, court, conf)) == court


def test_shadow():
    # Échantillonnage : inactif → jamais ; taux 1.0 → toujours ; taux 0 → jamais.
    assert shadow.echantillonne({"shadow_actif": False}) is False
    assert shadow.echantillonne({"shadow_actif": True, "shadow_taux": 1.0}) is True
    assert shadow.echantillonne({"shadow_actif": True, "shadow_taux": 0.0}) is False
    # Choix du candidat : explicite, sinon 1er free des fallbacks, jamais le modèle prod.
    assert shadow.candidat({"shadow_candidat": "free/c"}, "openai/gpt-4o") == "free/c"
    assert shadow.candidat({"fallback_models": ["openai/x", "free/y"]}, "openai/gpt-4o") == "free/y"
    assert shadow.candidat({"shadow_candidat": "openai/gpt-4o"}, "openai/gpt-4o") is None
    # Équivalence : réponses identiques → cosinus ~1 ; différentes → < 1.
    cli = _FakeClient()
    eq_same = asyncio.run(shadow._equivalence(cli, "même texte", "même texte"))
    eq_diff = asyncio.run(shadow._equivalence(cli, "alpha", "oméga"))
    assert eq_same is not None and eq_same > 0.999
    assert eq_diff is not None and eq_diff < eq_same
    # Rapport : 20 verdicts « equivalent » → recommandation de rétrograder.
    for _ in range(20):
        shadow._ajouter({"ts": 0, "etiquette": "chat", "modele_prod": "openai/gpt-4o",
                         "modele_candidat": "free/y", "equiv_score": 0.95,
                         "cout_prod": 0.01, "cout_candidat": 0.0, "verdict": "equivalent"})
    rap = shadow.rapport()
    flux = rap["flux"][0]
    assert "chat:openai/gpt-4o→free/y" == flux["flux"]
    assert flux["echantillons"] >= 20 and flux["taux_equivalent"] == 1.0
    assert flux["recommande_retrograder"] is True
    assert flux["economie_observee_usd"] > 0


def test_garde_fou_budget():
    journal_usage.BUDGET_MOIS = 0.001  # dépassé par l'appel précédent
    assert journal_usage.peut_appeler_payant() is False
    mods, force = llm_pipeline._ordonner_selon_budget(["openai/gpt-4o", "free/x/y"])
    assert mods == ["free/x/y"] and force is True
    res = asyncio.run(llm_pipeline.completer(
        [{"role": "user", "content": "x"}], modeles=["openai/gpt-4o"], client=_FakeClient()))
    assert not res.ok and "Budget" in res.erreur


def test_go_a_cout_marginal_nul():
    # Le forfait OpenCode Go (go/*) est facturé en $-équivalent, pas au call : il
    # est donc à coût marginal nul (comme free/ et ollama/) et NE doit pas être
    # jeté par le garde-fou budget, qui ne vise que le payant au call.
    assert llm_pipeline._sans_cout_marginal("go/deepseek-v4-pro") is True
    journal_usage.BUDGET_MOIS = 0.001
    assert journal_usage.peut_appeler_payant() is False
    mods, force = llm_pipeline._ordonner_selon_budget(
        ["openai/gpt-4o", "go/deepseek-v4-pro", "free/x/y"])
    assert mods == ["go/deepseek-v4-pro", "free/x/y"] and force is True


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
