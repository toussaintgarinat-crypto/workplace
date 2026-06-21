"""La porte à divulgation progressive (Sprint S90) — niveau-0/niveau-1 + `competence_charger`.

Autonome, aucun réseau (registre factice, executer court-circuite avant tout HTTP pour le
méta-outil). On vérifie :
  • porte OFF (défaut) → TOUT est présenté, trié par nom (comportement S64 + préfixe stable) ;
  • porte ON → les capacités niveau ≥ 1 sont DIFFÉRÉES et remplacées par `competence_charger`,
    qui les liste ;
  • une compétence déclarée « chargée » réapparaît en entier, et le méta-outil disparaît quand
    plus rien n'est différé ;
  • `competence_charger` rend le schéma de la cible (ou un refus honnête si inconnue).
    $ cd core && python3 test_porte.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import outils  # noqa: E402


class _Registre:
    def __init__(self, briques):
        self.briques = briques


def _registre():
    # 1 capacité niveau-0 (toujours visible) + 1 capacité niveau-1 (différée derrière la porte).
    return _Registre({"demo": {"nom": "demo", "port": 7777, "capacites": [
        {"nom": "demo_lire", "description": "lecture courante", "methode": "GET",
         "chemin": "/lire", "params": {}, "action": False, "niveau": 0},
        {"nom": "demo_rapport_avance", "description": "rapport coûteux", "methode": "POST",
         "chemin": "/rapport", "params": {"q": {"type": "string", "requis": True}},
         "action": True, "niveau": 1},
    ]}})


def _noms(specs):
    return [s["function"]["name"] for s in specs]


def test_porte_off_renvoie_tout_et_trie():
    specs = outils.outils_pour(_registre())            # porte=False par défaut
    noms = _noms(specs)
    assert "demo_lire" in noms and "demo_rapport_avance" in noms  # niveau-1 présent en entier
    assert outils.META_CHARGER not in noms                       # pas de méta-outil
    assert noms == sorted(noms)                                  # S90a : trié par nom


def test_porte_on_differe_niveau1():
    specs = outils.outils_pour(_registre(), porte=True)
    noms = _noms(specs)
    assert "demo_lire" in noms                       # niveau-0 toujours là
    assert "demo_rapport_avance" not in noms         # niveau-1 différé
    assert outils.META_CHARGER in noms               # remplacé par la porte
    meta = next(s for s in specs if s["function"]["name"] == outils.META_CHARGER)
    assert "demo_rapport_avance" in meta["function"]["description"]   # listée pour le LLM
    assert noms == sorted(noms)


def test_porte_on_chargee_reapparait_et_meta_disparait():
    specs = outils.outils_pour(_registre(), chargees={"demo_rapport_avance"}, porte=True)
    noms = _noms(specs)
    assert "demo_rapport_avance" in noms              # chargée → schéma complet présent
    assert outils.META_CHARGER not in noms            # plus rien de différé → méta-outil retiré


def test_competence_charger_rend_le_schema():
    out = asyncio.run(outils.executer(outils.META_CHARGER,
                                      {"nom": "demo_rapport_avance"}, _registre()))
    data = json.loads(out)
    assert data["ok"] is True and data["chargee"] == "demo_rapport_avance"
    assert data["outil"]["name"] == "demo_rapport_avance"
    # action → le schéma inclut le garde-fou `confirme` (gate préservé).
    assert "confirme" in data["outil"]["parameters"]["properties"]


def test_competence_charger_inconnue_refus_honnete():
    out = asyncio.run(outils.executer(outils.META_CHARGER, {"nom": "n_existe_pas"}, _registre()))
    data = json.loads(out)
    assert data["ok"] is False and "inconnue" in data["message"].lower()


def test_meta_outil_nest_pas_une_action():
    assert outils.est_action(outils.META_CHARGER, _registre()) is False


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
