"""Conscience de soi — le Cœur décrit son propre corps (Sprint S65).

Autonome : aucun réseau, aucun manifest réel — un registre factice en mémoire.
    $ cd core && python3 test_conscience.py
Sortie « ✅ TOUS LES TESTS PASSENT » = anatomie fidèle aux manifests + digest compact
qui renvoie à l'outil + organe curé/replié + honnêteté (rien d'inventé). S65 ne fait que
RETOURNER vers l'intérieur le schéma corporel S63/S64 : on teste la justesse, pas le réseau.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import conscience  # noqa: E402


class _Registre:
    def __init__(self, briques: dict):
        self.briques = briques


def _registre_demo():
    return _Registre({
        "noyau": {"nom": "noyau", "role": "noyau", "port": 5100},  # = moi, jamais un organe
        "memoire": {"nom": "memoire", "role": "memoire", "statut": "actif", "port": 5600,
                    "description": "souvenirs", "offre": ["retenir", "rappeler"],
                    "capacites": [{"nom": "memoire_retenir"}, {"nom": "memoire_rappeler"}]},
        "calcul": {"nom": "calcul", "role": "calcul", "statut": "a_tester", "port": 5990,
                   "description": "le Muscle", "offre": ["reveiller_noeud"]},
        # Brique hors table curée : organe nommé par son rôle (repli honnête).
        "exotique": {"nom": "exotique", "role": "téléportation", "statut": "actif", "port": 7000},
    })


def _outils_demo():
    return [
        {"type": "function", "function": {"name": "lister_entreprises", "description": "liste"}},
        {"type": "function", "function": {"name": "memoire_retenir", "description": "mémorise"}},
        {"type": "function", "function": {"name": "mes_capacites", "description": "moi"}},
    ]


def test_organes_excluent_le_noyau():
    orgs = conscience.organes(_registre_demo())
    noms = {o["brique"] for o in orgs}
    assert "noyau" not in noms          # le Cœur n'est pas un organe qu'il commande
    assert noms == {"memoire", "calcul", "exotique"}


def test_organe_cure_et_repli_sur_le_role():
    orgs = {o["brique"]: o for o in conscience.organes(_registre_demo())}
    assert orgs["memoire"]["organe"].startswith("mémoire")   # table curée
    assert orgs["calcul"]["organe"].startswith("muscle")
    assert orgs["exotique"]["organe"] == "téléportation"      # repli honnête sur le rôle


def test_organe_fidele_au_manifest():
    orgs = {o["brique"]: o for o in conscience.organes(_registre_demo())}
    m = orgs["memoire"]
    assert m["statut"] == "actif" and m["port"] == 5600
    assert m["description"] == "souvenirs" and m["nb_capacites"] == 2
    assert orgs["calcul"]["statut"] == "a_tester"


def test_digest_nomme_les_organes_et_renvoie_a_l_outil():
    d = conscience.digest(_registre_demo(), nb_outils=42)
    assert "3 organes" in d              # noyau exclu : 3 organes restants
    assert "mémoire" in d and "muscle" in d
    assert "42 outils" in d
    assert "mes_capacites" in d          # règle anti-confabulation : renvoie à l'outil
    assert "invente" in d.lower()


def test_digest_vide_si_aucune_brique():
    assert conscience.digest(_Registre({}), nb_outils=0) == ""
    # Registre avec le seul noyau → aucun organe → digest vide (rien à dire honnêtement).
    assert conscience.digest(_Registre({"noyau": {"nom": "noyau"}}), nb_outils=5) == ""


def test_digest_dedupe_les_organes_courts():
    reg = _Registre({
        "forge": {"nom": "forge", "role": "agents", "port": 5700},
        "generateur": {"nom": "generateur", "role": "generateur", "port": 5400},
    })
    d = conscience.digest(reg, nb_outils=1)
    # « mains » est le libellé court des DEUX → ne doit apparaître qu'une fois.
    assert d.count("mains") == 1


def test_anatomie_liste_les_outils_actifs_avec_drapeau_action():
    est_action = lambda n: n == "memoire_retenir"  # noqa: E731
    a = conscience.anatomie(_registre_demo(), _outils_demo(), est_action)
    par_nom = {o["nom"]: o for o in a["outils"]}
    assert set(par_nom) == {"lister_entreprises", "memoire_retenir", "mes_capacites"}
    assert par_nom["memoire_retenir"]["action"] is True
    assert par_nom["lister_entreprises"]["action"] is False
    assert a["nb_outils"] == 3
    assert par_nom["lister_entreprises"]["description"] == "liste"


def test_anatomie_compte_les_organes_et_se_decrit():
    a = conscience.anatomie(_registre_demo(), _outils_demo(), lambda n: False)
    assert a["corps"] == "Workplace"
    assert a["nb_organes"] == 3
    assert "Cœur" in a["je_suis"]
    assert "invente" in a["note"].lower()       # honnêteté inscrite dans la réponse


def test_anatomie_tolere_outils_vides_ou_sans_nom():
    specs = [{"type": "function", "function": {}}, {"function": {"name": ""}}]
    a = conscience.anatomie(_registre_demo(), specs, lambda n: False)
    assert a["outils"] == []                     # une spec sans nom est ignorée, pas inventée


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
