"""Tests de fusion.py — logique pure de world-engine, sans réseau."""
import fusion


def test_date_pour_signe_vierge():
    assert fusion.date_pour_signe("Vierge", 1990) == "1990-08-23"


def test_date_pour_signe_capricorne_reste_dans_l_annee_donnee():
    """Capricorne est à cheval sur le nouvel an (22 déc → 19 jan) : on ancre sur le
    DÉBUT de plage (22 décembre), qui reste toujours dans l'année demandée."""
    assert fusion.date_pour_signe("Capricorne", 2000) == "2000-12-22"


def test_date_pour_signe_verseau_janvier():
    assert fusion.date_pour_signe("Verseau", 2010) == "2010-01-20"
