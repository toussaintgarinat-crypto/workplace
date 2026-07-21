"""Tests de la taxonomie des familles de briques (S142 + ajout famille veille)."""
import familles


def test_veille_est_dans_la_taxonomie():
    slugs = [f["slug"] for f in familles.FAMILLES]
    assert "veille" in slugs


def test_meta_veille_a_le_bon_label_et_icone():
    m = familles.meta("veille")
    assert m["label"] == "Veille"
    assert m["icone"] == "🔭"


def test_grouper_range_une_brique_veille_dans_le_bon_groupe():
    briques = [{"nom": "geo-demo", "famille": "veille"}]
    groupes = familles.grouper(briques)
    assert "veille" in groupes
    assert groupes["veille"]["label"] == "Veille"
    assert groupes["veille"]["icone"] == "🔭"
    assert groupes["veille"]["briques"] == briques


def test_toutes_les_familles_ont_un_slug_unique():
    slugs = [f["slug"] for f in familles.FAMILLES]
    assert len(slugs) == len(set(slugs))
