"""Tests unitaires du sous-domaine PUR (S81) : objet-valeur Argent, entité Convive,
groupage d'une commande multi-convive. Rapides (aucune I/O)."""
import pytest

import domaine
from domaine import Argent, Convive


def test_argent_somme_et_produit():
    a = Argent(1400) + Argent(700)
    assert a.cents == 2100 and a.devise == "EUR"
    assert Argent(700).fois(3).cents == 2100


def test_argent_zero_et_borne_positif():
    assert Argent.zero().cents == 0
    assert Argent(-500).borne_positif().cents == 0
    assert Argent(500).borne_positif().cents == 500


def test_argent_refuse_de_melanger_les_devises():
    with pytest.raises(ValueError):
        Argent(100, "EUR") + Argent(100, "USD")


def test_convive_normalise_les_blancs_et_le_vide():
    assert Convive.normaliser("  Thomas  ") == "Thomas"
    assert Convive.normaliser("") == "Convive"
    assert Convive.normaliser(None) == "Convive"
    assert Convive.normaliser("", defaut="A") == "A"


def test_grouper_par_convive_conserve_l_ordre_et_le_defaut():
    plats = [
        {"plat_id": "p1", "convive": "Thomas"},
        {"plat_id": "p2", "convive": "Sarah"},
        {"plat_id": "p3"},                       # pas de convive → défaut
        {"plat_id": "p4", "convive": "Thomas"},  # rejoint le 1er groupe
    ]
    groupes = domaine.grouper_par_convive(plats, convive_defaut="Lucas")
    noms = [g[0] for g in groupes]
    assert noms == ["Thomas", "Sarah", "Lucas"]          # ordre d'apparition
    assert [it["plat_id"] for it in groupes[0][1]] == ["p1", "p4"]
    assert groupes[2][1][0]["plat_id"] == "p3"


def test_grouper_panier_vide():
    assert domaine.grouper_par_convive([], "X") == []
    assert domaine.grouper_par_convive(None) == []
