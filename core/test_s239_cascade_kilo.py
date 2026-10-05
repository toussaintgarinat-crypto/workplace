"""S239 — Les gratuits Kilo Code (`kilo/*`) dans la cascade du Cœur, APRÈS les `free/*`.

Ce qui doit être verrouillé :
  1. l'ordre exact de la cascade auto : [tête] → `free/*` (top N) → `kilo/*` (top N) →
     souverain/repli payant. Les `kilo/*` sont un FILET : leurs fournisseurs amont peuvent
     journaliser les requêtes, ils ne passent jamais devant un modèle choisi ni devant
     OpenRouter ;
  2. un `kilo/*` est à coût marginal nul (le garde-fou budget ne doit pas le jeter) ;
  3. le routage dynamique peut descendre vers un `kilo/*` à défaut de `free/*`.
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import config_assistant as C  # noqa: E402
import llm_pipeline  # noqa: E402
import routage  # noqa: E402


def _chaine(conf, dispo):
    async def faux_lister():
        return dispo
    ancien = C.lister_modeles
    C.lister_modeles = faux_lister
    try:
        return asyncio.run(C.chaine_modeles(conf))
    finally:
        C.lister_modeles = ancien


_DISPO = ["kilo/k1", "free/a", "openai/x", "kilo/k2", "free/b", "free/c", "kilo/k3",
          "gratuit/auto", "go/glm-5"]
_BASE = dict(cascade_auto=True, cascade_free_n=2, repli_payant="deepseek/payant")


def test_ordre_tete_free_kilo_repli():
    chaine = _chaine({**_BASE, "model": "mistral/small"}, _DISPO)
    assert chaine == ["mistral/small", "free/a", "free/b", "kilo/k1", "kilo/k2",
                      "deepseek/payant"], chaine


def test_ordre_avec_souverain_avant_payant():
    chaine = _chaine({**_BASE, "model": "", "repli_souverain": "local/cpu",
                      "repli_souverain_avant_payant": True}, _DISPO)
    assert chaine == ["free/a", "free/b", "kilo/k1", "kilo/k2", "local/cpu",
                      "deepseek/payant"], chaine


def test_kilo_seuls_si_aucun_free_servi():
    """Le cas du 2026-10-05 : OpenRouter mort, plus aucun `free/*` utile."""
    chaine = _chaine({**_BASE, "model": "mistral/small"}, ["kilo/k1", "kilo/k2", "kilo/k3"])
    assert chaine == ["mistral/small", "kilo/k1", "kilo/k2", "deepseek/payant"], chaine


def test_alias_gratuit_auto_jamais_dans_la_cascade():
    """`gratuit/auto` (routeur de Kilo) est réservé à la Forge : il masquerait au journal le
    modèle qui a réellement répondu."""
    chaine = _chaine({**_BASE, "model": ""}, _DISPO)
    assert "gratuit/auto" not in chaine and "go/glm-5" not in chaine, chaine


def test_kilo_sans_cout_marginal():
    assert llm_pipeline._sans_cout_marginal("kilo/nvidia/nemotron-3-super-120b-a12b") is True
    assert llm_pipeline._sans_cout_marginal("deepseek/deepseek-v4-flash") is False


def test_routage_descend_vers_kilo_a_defaut_de_free():
    assert routage._premier_gratuit(["mistral/small", "kilo/k1"], {}) == "kilo/k1"
    # Un `free/*` reste préféré dans l'ordre de la chaîne (il vient avant dans la cascade).
    assert routage._premier_gratuit(["mistral/small", "free/a", "kilo/k1"], {}) == "free/a"
