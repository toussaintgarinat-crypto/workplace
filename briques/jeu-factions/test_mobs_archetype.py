import archetypes
import mobs_archetype as MA


def _etape_fixture():
    archetypes.seed_zones_archetype()
    return archetypes.lister_etapes("Le Meneur Charismatique")[0]


def test_seed_mobs_archetype_cree_un_boss_et_deux_mobs_par_etape():
    etape = _etape_fixture()
    MA.seed_mobs_archetype()
    gabarits = MA.lister_mobs_etape(etape["id"])
    assert len(gabarits) == 3
    assert sum(1 for g in gabarits if g["role"] == "boss") == 1
    assert sum(1 for g in gabarits if g["role"] == "mob") == 2


def test_seed_mobs_archetype_est_idempotent():
    etape = _etape_fixture()
    MA.seed_mobs_archetype()
    MA.seed_mobs_archetype()
    assert len(MA.lister_mobs_etape(etape["id"])) == 3


def test_seed_mobs_archetype_couvre_les_30_etapes():
    archetypes.seed_zones_archetype()
    MA.seed_mobs_archetype()
    total = 0
    for arch in archetypes.ARCHETYPES_SIGNATURE:
        for e in archetypes.lister_etapes(arch):
            total += len(MA.lister_mobs_etape(e["id"]))
    assert total == 30 * 3


def test_boss_plus_difficile_a_plus_de_pv_que_letape_precedente():
    archetypes.seed_zones_archetype()
    MA.seed_mobs_archetype()
    etapes = archetypes.lister_etapes("Le Meneur Charismatique")
    pv = []
    for e in etapes:
        boss = next(g for g in MA.lister_mobs_etape(e["id"]) if g["role"] == "boss")
        pv.append(boss["pv_max"])
    assert pv[0] < pv[1] < pv[2]


def test_lister_mobs_etape_inconnue_est_vide():
    assert MA.lister_mobs_etape("inconnue") == []


def test_nom_du_boss_reprend_le_titre_de_letape():
    etape = _etape_fixture()
    MA.seed_mobs_archetype()
    boss = next(g for g in MA.lister_mobs_etape(etape["id"]) if g["role"] == "boss")
    assert etape["nom"] in boss["nom"]
