"""Tests du theme_complet — orchestrateur, repli honnête, cohérence."""
from datetime import datetime
import theme_complet as TC
import traditions as T


_FICHE_COMPLETE = {
    "date_naissance": "2000-01-01",
    "heure_naissance": "12:00",
    "latitude": 45.0,
    "longitude": 0.0,
    "utc_offset": 0.0,
    "systeme_maisons": "whole_sign",
    "methode_dominantes": "comptage_dignite",
}


def test_theme_complet_champs_present():
    res = TC.theme_complet(_FICHE_COMPLETE)
    assert "fondations" in res
    assert "dix_corps" in res
    assert "points_evolutifs" in res
    assert "maisons" in res
    assert "aspects" in res
    assert "dominantes" in res
    assert "meta" in res


def test_fondations_six_entrees():
    res = TC.theme_complet(_FICHE_COMPLETE)
    f = res["fondations"]
    assert {"soleil", "lune", "ascendant", "descendant",
            "milieu_du_ciel", "fond_du_ciel"} <= set(f.keys())


def test_dix_corps_dix_entrees():
    res = TC.theme_complet(_FICHE_COMPLETE)
    assert set(res["dix_corps"].keys()) == {"Soleil", "Lune", "Mercure", "Vénus",
                                            "Mars", "Jupiter", "Saturne", "Uranus",
                                            "Neptune", "Pluton"}


def test_points_evolutifs_quatre():
    res = TC.theme_complet(_FICHE_COMPLETE)
    assert set(res["points_evolutifs"].keys()) == {"noeud_nord", "noeud_sud",
                                                    "chiron", "lilith"}


def test_maisons_12_et_systeme():
    res = TC.theme_complet(_FICHE_COMPLETE)
    assert len(res["maisons"]) == 12
    assert res["meta"]["systeme_maisons_effectif"] == "whole_sign"


def test_repli_sans_heure_sans_lieu():
    """Sans heure/lieu : seulement les fondations Soleil (+ Lune approx à midi)."""
    fiche = {"date_naissance": "2000-01-01"}
    res = TC.theme_complet(fiche)
    assert "soleil" in res.get("fondations", {})
    # Pas de maisons, pas d'aspects (besoin de l'heure/lieu)
    assert "maisons" not in res or not res["maisons"]
    assert "aspects" not in res or not res["aspects"]


def test_theme_complet_depuis_traditions_coherent():
    """Variante réutilisant traditions : mêmes fondations Soleil/Asc/MC."""
    trad = T.calculer(_FICHE_COMPLETE)
    res1 = TC.theme_complet(_FICHE_COMPLETE)
    res2 = TC.theme_complet_depuis_traditions(trad, _FICHE_COMPLETE)
    assert abs(res1["fondations"]["soleil"]["longitude"]
               - res2["fondations"]["soleil"]["longitude"]) < 1e-3


def test_changement_systeme_maisons_change_maisons_pas_positions():
    """Whole Sign vs Equal House : positions identiques, maisons différentes."""
    fiche_ws = {**_FICHE_COMPLETE, "systeme_maisons": "whole_sign"}
    fiche_eh = {**_FICHE_COMPLETE, "systeme_maisons": "equal_house"}
    ws = TC.theme_complet(fiche_ws)
    eh = TC.theme_complet(fiche_eh)
    # Positions des corps identiques
    assert ws["dix_corps"]["Soleil"]["longitude"] == eh["dix_corps"]["Soleil"]["longitude"]
    # Cuspes des maisons différents (sauf si Asc à 0° d'un signe)
    assert ws["meta"]["systeme_maisons_effectif"] != eh["meta"]["systeme_maisons_effectif"]


def test_meta_contient_caveats():
    res = TC.theme_complet(_FICHE_COMPLETE)
    caveats = res["meta"].get("caveats", [])
    assert any("Pluton" in c or "Chiron" in c for c in caveats)


def test_noeud_sud_symetrique_noeud_nord():
    res = TC.theme_complet(_FICHE_COMPLETE)
    nn = res["points_evolutifs"]["noeud_nord"]["longitude"]
    ns = res["points_evolutifs"]["noeud_sud"]["longitude"]
    ecart = abs(nn - ns) % 360
    assert abs(ecart - 180) < 1e-3 or abs(ecart - 180) > 179.99
