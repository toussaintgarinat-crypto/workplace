"""Tests de la mécanique pure du tick (Sprint C) — aucune I/O, RNG toujours
seedé explicitement en paramètre (même motif que test_fusion.py/test_spatial.py)."""
from random import Random

import horloge


def test_evoluer_ressources_et_technologie_regenere_et_consomme():
    stock, niveau, consomme = horloge.evoluer_ressources_et_technologie(
        {"ble": 40.0}, niveau_technologie=0.0, population_vivante=5)
    assert 0.0 <= stock["ble"] <= horloge.PLAFOND_RESSOURCE
    assert consomme > 0
    assert niveau > 0.0


def test_evoluer_ressources_stock_vide_ne_plante_pas():
    stock, niveau, consomme = horloge.evoluer_ressources_et_technologie(
        {}, niveau_technologie=1.0, population_vivante=10)
    assert stock == {}
    assert consomme == 0.0
    assert niveau == 1.0


def test_evoluer_ressources_borne_au_plafond_technologie():
    _, niveau, _ = horloge.evoluer_ressources_et_technologie(
        {"ble": 100.0}, niveau_technologie=horloge.PLAFOND_TECHNOLOGIE, population_vivante=1000)
    assert niveau == horloge.PLAFOND_TECHNOLOGIE


def test_meurt_jamais_avant_age_adulte_min():
    rng = Random(1)
    assert horloge.meurt(age=horloge.AGE_ADULTE_MIN - 1, niveau_technologie=0.0, rng=rng) is False


def test_meurt_deterministe_avec_seed_fixe():
    a = horloge.meurt(age=80, niveau_technologie=0.0, rng=Random(42))
    b = horloge.meurt(age=80, niveau_technologie=0.0, rng=Random(42))
    assert a == b


def test_meurt_moins_probable_avec_plus_de_technologie():
    rng_sans_tech = Random(7)
    rng_avec_tech = Random(7)
    resultats_sans_tech = [horloge.meurt(90, 0.0, rng_sans_tech) for _ in range(200)]
    resultats_avec_tech = [horloge.meurt(90, 5.0, rng_avec_tech) for _ in range(200)]
    assert sum(resultats_avec_tech) < sum(resultats_sans_tech)


def test_cellule_saturee():
    assert horloge.cellule_saturee(population_vivante=10, stock={"ble": 5.0}) is True
    assert horloge.cellule_saturee(population_vivante=2, stock={"ble": 50.0}) is False


def test_est_adulte_fecond():
    assert horloge.est_adulte_fecond(horloge.AGE_ADULTE_MIN) is True
    assert horloge.est_adulte_fecond(horloge.AGE_ADULTE_MIN - 1) is False
    assert horloge.est_adulte_fecond(horloge.AGE_FECONDITE_MAX + 1) is False


def test_former_couples_appariement_borne_par_le_plus_petit_groupe():
    couples = horloge.former_couples(["f1", "f2", "f3"], ["m1"], Random(1))
    assert len(couples) <= 1


def test_former_couples_deterministe():
    a = horloge.former_couples(["f1", "f2"], ["m1", "m2"], Random(5))
    b = horloge.former_couples(["f1", "f2"], ["m1", "m2"], Random(5))
    assert a == b


def test_tenter_rencontres_occasionnelles_moins_probable_que_couples():
    f, m = [f"f{i}" for i in range(50)], [f"m{i}" for i in range(50)]
    couples = horloge.former_couples(f, m, Random(1))
    rencontres = horloge.tenter_rencontres_occasionnelles(f, m, Random(1))
    assert len(rencontres) < len(couples)


def test_derive_position_naissance_dans_les_bornes_valides():
    lat, lon = horloge.derive_position_naissance(0.0, 0.0)
    assert lat == -90.0 and lon == -180.0
    lat, lon = horloge.derive_position_naissance(horloge.TAILLE_MONDE, horloge.TAILLE_MONDE)
    assert lat == 90.0 and lon == 180.0


def test_derive_heure_et_offset_format_valide():
    heure, offset = horloge.derive_heure_et_offset(Random(1))
    h, m = heure.split(":")
    assert 0 <= int(h) < 24 and 0 <= int(m) < 60
    assert -12 <= offset <= 12


def test_tirer_sexe_deterministe():
    assert horloge.tirer_sexe(Random(1)) == horloge.tirer_sexe(Random(1))
    assert horloge.tirer_sexe(Random(1)) in ("F", "M")


def test_migre_frontiere_deterministe_avec_seed_fixe():
    a = horloge.migre_frontiere(Random(7))
    b = horloge.migre_frontiere(Random(7))
    assert a == b


def test_migre_frontiere_moins_probable_que_migre_intra_pays():
    # Sur un grand nombre de tirages avec le MÊME flux de random, la fréquence de
    # succès de migre_frontiere doit rester nettement sous celle de migre (Sprint C)
    # — traduit "franchir une frontière est un choix plus lourd" (design).
    rng_a, rng_b = Random(123), Random(123)
    n = 5000
    freq_frontiere = sum(horloge.migre_frontiere(rng_a) for _ in range(n)) / n
    freq_intra = sum(horloge.migre(rng_b) for _ in range(n)) / n
    assert freq_frontiere < freq_intra


def test_tirer_pays_destination_choisit_parmi_la_liste():
    rng = Random(1)
    pays = ["m1", "m2", "m3"]
    for _ in range(20):
        assert horloge.tirer_pays_destination(pays, rng) in pays


def test_tirer_cellule_destination_bornee():
    rng = Random(1)
    for _ in range(50):
        cid = horloge.tirer_cellule_destination(7, rng)
        assert 0 <= cid < 7
