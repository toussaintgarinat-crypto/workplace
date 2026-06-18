"""Validation du catalogue de capacités — le « schéma corporel » (Sprint S63).

Autonome : aucun réseau, aucun manifest réel — un registre factice en mémoire.
    $ cd core && python3 test_catalogue.py
Sortie « ✅ TOUS LES TESTS PASSENT » = découverte + normalisation + résolution
d'URL + garde-fous d'honnêteté OK. S63 ne câble RIEN au LLM : on teste la seule
découverte déclarative.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import catalogue  # noqa: E402


class _Registre:
    """Registre minimal : un dict de manifests."""
    def __init__(self, briques: dict):
        self.briques = briques


def _registre_demo():
    return _Registre({
        "memoire": {
            "nom": "memoire", "port": 5600,
            "capacites": [
                {"nom": "memoire_rappeler", "description": "cherche",
                 "methode": "GET", "chemin": "/rappeler",
                 "params": {"q": {"type": "string", "requis": True}}, "action": False},
                {"nom": "memoire_retenir", "description": "mémorise",
                 "methode": "POST", "chemin": "/retenir", "action": True},
            ],
        },
        "calcul": {
            "nom": "calcul", "port": 5990,
            "capacites": [
                {"nom": "calcul_lister_noeuds", "chemin": "/noeuds"},   # méthode omise → GET
            ],
        },
        # Brique sans capacités : simplement absente du catalogue (pas une erreur).
        "donnees": {"nom": "donnees", "port": 5500},
    })


def test_agrege_les_capacites_de_plusieurs_briques():
    cap = catalogue.collecter_capacites(_registre_demo())
    noms = {c["nom"] for c in cap}
    assert noms == {"memoire_rappeler", "memoire_retenir", "calcul_lister_noeuds"}
    # Chaque entrée sait de quelle brique elle vient.
    par_nom = {c["nom"]: c for c in cap}
    assert par_nom["memoire_rappeler"]["brique"] == "memoire"
    assert par_nom["calcul_lister_noeuds"]["brique"] == "calcul"


def test_resout_url_depuis_le_port():
    cap = {c["nom"]: c for c in catalogue.collecter_capacites(_registre_demo())}
    assert cap["memoire_rappeler"]["url"] == "http://host.docker.internal:5600/rappeler"
    assert cap["calcul_lister_noeuds"]["url"] == "http://host.docker.internal:5990/noeuds"


def test_override_env_prioritaire_sur_le_port():
    os.environ["MEMOIRE_URL"] = "http://mem-mesh:9999/"
    try:
        cap = {c["nom"]: c for c in catalogue.collecter_capacites(_registre_demo())}
        # L'override gagne et le slash final est nettoyé.
        assert cap["memoire_rappeler"]["url"] == "http://mem-mesh:9999/rappeler"
    finally:
        del os.environ["MEMOIRE_URL"]


def test_methode_defaut_get_action_defaut_false_chemin_normalise():
    reg = _Registre({"x": {"nom": "x", "port": 1234, "capacites": [
        {"nom": "x_lire", "chemin": "lire"},        # pas de slash initial, méthode omise
    ]}})
    cap = catalogue.collecter_capacites(reg)[0]
    assert cap["methode"] == "GET"
    assert cap["action"] is False
    assert cap["chemin"] == "/lire"
    assert cap["url"].endswith("/lire")


def test_ignore_capacite_incomplete_sans_chemin():
    reg = _Registre({"x": {"nom": "x", "port": 1234, "capacites": [
        {"nom": "x_bancale"},                       # pas de chemin → écartée
        {"nom": "x_ok", "chemin": "/ok"},
    ]}})
    noms = {c["nom"] for c in catalogue.collecter_capacites(reg)}
    assert noms == {"x_ok"}                          # honnêteté : la bancale est tue, pas inventée


def test_ignore_brique_sans_port_meme_si_elle_declare():
    reg = _Registre({"app-builder": {"nom": "app-builder", "port": None, "capacites": [
        {"nom": "ab_truc", "chemin": "/truc"},
    ]}})
    assert catalogue.collecter_capacites(reg) == []  # frontend pur → non appelable → écarté


def test_doublons_detectes():
    reg = _Registre({
        "a": {"nom": "a", "port": 1, "capacites": [{"nom": "collision", "chemin": "/x"}]},
        "b": {"nom": "b", "port": 2, "capacites": [{"nom": "collision", "chemin": "/y"}]},
    })
    cap = catalogue.collecter_capacites(reg)
    assert catalogue.doublons(cap) == ["collision"]


def test_pas_de_doublon_quand_noms_uniques():
    cap = catalogue.collecter_capacites(_registre_demo())
    assert catalogue.doublons(cap) == []


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
