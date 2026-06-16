"""Validation du repli souverain CPU dans la cascade (S62) — `chaine_modeles`.

Autonome : on remplace `lister_modeles` (pas de vraie Gateway) pour figer les gratuits.
    $ cd core && python3 test_repli_souverain.py
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import config_assistant as C  # noqa: E402


def _chaine(conf):
    async def faux_lister():
        return ["free/a", "free/b", "openai/x"]
    ancien = C.lister_modeles
    C.lister_modeles = faux_lister
    try:
        return asyncio.run(C.chaine_modeles(conf))
    finally:
        C.lister_modeles = ancien


_BASE = dict(model="", cascade_auto=True, cascade_free_n=2,
             repli_payant="deepseek/payant")


def test_souverain_avant_payant():
    chaine = _chaine({**_BASE, "repli_souverain": "local/cpu",
                      "repli_souverain_avant_payant": True})
    assert chaine == ["free/a", "free/b", "local/cpu", "deepseek/payant"], chaine


def test_souverain_apres_payant():
    chaine = _chaine({**_BASE, "repli_souverain": "local/cpu",
                      "repli_souverain_avant_payant": False})
    assert chaine == ["free/a", "free/b", "deepseek/payant", "local/cpu"], chaine


def test_absent_si_non_configure():
    chaine = _chaine({**_BASE, "repli_souverain": ""})
    assert chaine == ["free/a", "free/b", "deepseek/payant"], chaine


def test_mode_manuel_souverain_en_dernier():
    chaine = _chaine({"model": "go/glm-5", "cascade_auto": False,
                      "fallback_models": ["free/a"], "repli_souverain": "local/cpu"})
    assert chaine == ["go/glm-5", "free/a", "local/cpu"], chaine


def test_dedup_si_souverain_deja_present():
    # Si le souverain est déjà la tête, pas de doublon en fin de chaîne.
    chaine = _chaine({**_BASE, "model": "local/cpu", "repli_souverain": "local/cpu",
                      "repli_souverain_avant_payant": True})
    assert chaine.count("local/cpu") == 1, chaine
    assert chaine[0] == "local/cpu"


def test_persistance_setter():
    C.definir_repli_souverain(modele="local/cpu", avant_payant=False)
    conf = C.charger()
    assert conf["repli_souverain"] == "local/cpu"
    assert conf["repli_souverain_avant_payant"] is False


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
