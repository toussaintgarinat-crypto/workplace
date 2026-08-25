import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mesure_charge_world_engine import calculer_latences_tick


def test_calculer_latences_tick_ignore_les_lectures_sans_increment():
    # 3 lectures au même tick (polling plus rapide que le tick) puis un
    # incrément : un seul écart doit être compté, pas deux.
    observations = [(100.0, 5), (101.0, 5), (102.0, 5), (105.0, 6)]
    resultat = calculer_latences_tick(observations)
    assert resultat["nb_ticks_observes"] == 1
    assert resultat["ecart_p50_s"] == 3.0  # 105 - 102


def test_calculer_latences_tick_calcule_percentiles_sur_plusieurs_increments():
    observations = [(0.0, 1), (5.0, 2), (11.0, 3), (14.0, 4)]
    resultat = calculer_latences_tick(observations)
    assert resultat["nb_ticks_observes"] == 3
    assert resultat["ecart_min_s"] == 3.0
    assert resultat["ecart_max_s"] == 6.0


def test_calculer_latences_tick_vide_si_moins_de_deux_increments():
    assert calculer_latences_tick([(0.0, 1), (2.0, 1)]) == {}
    assert calculer_latences_tick([]) == {}
