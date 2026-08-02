import mobs
import zones


def test_seed_mobs_cree_un_boss_et_deux_mobs_par_zone():
    zones.seed_zones()
    mobs.seed_mobs()
    une_zone = zones.lister_zones()[0]
    gabarits = mobs.lister_mobs_zone(une_zone["id"])
    assert len(gabarits) == 3
    assert sum(1 for g in gabarits if g["role"] == "boss") == 1
    assert sum(1 for g in gabarits if g["role"] == "mob") == 2


def test_seed_mobs_est_idempotent():
    zones.seed_zones()
    mobs.seed_mobs()
    mobs.seed_mobs()
    une_zone = zones.lister_zones()[0]
    assert len(mobs.lister_mobs_zone(une_zone["id"])) == 3


def test_lister_mobs_zone_inconnue_est_vide():
    assert mobs.lister_mobs_zone("inconnue") == []


def test_gabarits_ont_les_champs_attendus():
    zones.seed_zones()
    mobs.seed_mobs()
    une_zone = zones.lister_zones()[0]
    boss = next(g for g in mobs.lister_mobs_zone(une_zone["id"]) if g["role"] == "boss")
    for champ in ("id", "zone_id", "nom", "pv_max", "degats_attaque",
                 "cooldown_attaque_s", "portee_aggro", "portee_attaque"):
        assert champ in boss
