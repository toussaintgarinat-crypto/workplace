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


def test_calculer_latences_tick_ecart_moyen_non_biaise_par_le_pas_de_polling():
    # Écarts individuels inégaux (4s/6s/4s) : ecart_p50_s (4.0) ne représente
    # QU'UN des trois écarts, pas la tendance réelle — c'est exactement ce
    # que la revue finale a signalé comme trompeur quand ces écarts sont eux-
    # mêmes quantifiés par le pas de polling de l'appelant. ecart_moyen_s
    # (portée totale / nb d'incréments) reste, lui, un estimateur exact et
    # non biaisé de la tendance quel que soit le pas de polling :
    # (14 - 0) / 3 = 4.6666...
    observations = [(0.0, 1), (4.0, 2), (10.0, 3), (14.0, 4)]
    resultat = calculer_latences_tick(observations)
    assert resultat["ecart_moyen_s"] == (14.0 - 0.0) / 3


def test_calculer_latences_tick_ignore_un_tick_non_monotone():
    # Un tick qui reculerait (bruit/désordre) ne doit jamais être accepté
    # comme un nouvel incrément — sinon un écart négatif fausserait le calcul.
    observations = [(0.0, 1), (5.0, 2), (7.0, 1), (10.0, 3)]
    resultat = calculer_latences_tick(observations)
    assert resultat["nb_ticks_observes"] == 2
    assert resultat["ecart_min_s"] == 5.0
    assert resultat["ecart_max_s"] == 5.0
