"""Tests du ciblage de l'assistant (S165) — contexte volatile « pose-le où il travaille ».

Offline : un faux registre en mémoire suffit (même forme que registre.Registre.briques).
    $ cd core && python3 -m pytest test_ciblage.py -q
"""
import os
import tempfile

os.environ.setdefault("ASSISTANT_CONFIG_PATH", os.path.join(tempfile.mkdtemp(), "cfg.json"))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")

import ciblage  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "geo": {
        "nom": "geo", "port": 6110,
        "description": "Veille territoriale : entreprises et associations sur une carte.",
        "capacites": [
            {"nom": "geo_zones", "chemin": "/zones", "description": "Liste les zones de veille."},
            {"nom": "geo_veille_lancer", "chemin": "/ingestion/executer", "methode": "POST",
             "description": "Relance la veille.", "action": True},
        ],
    },
    "muette": {"nom": "muette", "port": 7000, "description": "Brique sans capacités."},
})


def test_sans_cible_contexte_vide():
    assert ciblage.contexte_de(None, REGISTRE) == ""
    assert ciblage.contexte_de("  ", REGISTRE) == ""


def test_brique_connue_decrit_role_et_capacites():
    ctx = ciblage.contexte_de("geo", REGISTRE)
    assert "« geo »" in ctx
    assert "Veille territoriale" in ctx
    assert "geo_zones" in ctx and "geo_veille_lancer" in ctx
    # Le gate reste visible : les actions sont marquées, jamais banalisées.
    assert "[ACTION — confirmation requise]" in ctx
    assert "court-circuiter" in ctx


def test_brique_inconnue_note_honnete():
    ctx = ciblage.contexte_de("fantome", REGISTRE)
    assert "fantome" in ctx
    assert "aucune brique" in ctx          # on ne confabule pas une brique absente
    assert "etat_briques" in ctx


def test_brique_sans_capacites_reste_utilisable():
    ctx = ciblage.contexte_de("muette", REGISTRE)
    assert "« muette »" in ctx
    assert "Capacités" not in ctx          # pas de section vide inventée


def test_plafond_capacites():
    briques = {"grosse": {"nom": "grosse", "port": 7001, "description": "Riche.",
               "capacites": [{"nom": f"cap_{i}", "chemin": f"/c{i}", "description": "d"}
                             for i in range(ciblage.MAX_CAPACITES + 3)]}}
    ctx = ciblage.contexte_de("grosse", _FauxRegistre(briques))
    assert f"cap_{ciblage.MAX_CAPACITES - 1}" in ctx
    assert f"cap_{ciblage.MAX_CAPACITES}" not in ctx
    assert "+3 autres" in ctx and "mes_capacites" in ctx


def test_fusionner_instructions():
    # Ni projet ni cible → None (comportement d'avant S165 strictement inchangé).
    assert ciblage.fusionner_instructions(None, None, REGISTRE) is None
    # Projet seul → inchangé.
    assert ciblage.fusionner_instructions("projet X", None, REGISTRE) == "projet X"
    # Cible seule → le contexte de ciblage.
    seul = ciblage.fusionner_instructions(None, "geo", REGISTRE)
    assert seul and seul.startswith("Ciblage")
    # Les deux → projet d'abord, ciblage ensuite.
    deux = ciblage.fusionner_instructions("projet X", "geo", REGISTRE)
    assert deux.startswith("projet X") and "Ciblage" in deux


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
