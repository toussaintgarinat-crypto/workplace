import archetypes as A
import zones as Z
import tick as T


def test_executer_tick_ne_resout_plus_que_les_groupes():
    Z.seed_zones()
    A.seed_zones_archetype()
    resultat = T.executer_tick()
    assert list(resultat.keys()) == ["groupes"]


def test_executer_tick_sans_rien_a_resoudre_ne_plante_pas():
    Z.seed_zones()
    A.seed_zones_archetype()
    resultat = T.executer_tick()
    assert resultat["groupes"] == []
