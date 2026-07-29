import combat
import mobs
import zones


def _mobs_zone_fixture():
    zones.seed_zones()
    mobs.seed_mobs()
    zone = zones.lister_zones()[0]
    return zone["id"], mobs.lister_mobs_zone(zone["id"])


async def test_rejoindre_cree_une_instance_et_y_ajoute_le_joueur():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    assert "p1" in inst.etat["joueurs"]
    assert inst.zone_id == zone_id


async def test_rejoindre_reutilise_linstance_ouverte():
    zone_id, gabarits = _mobs_zone_fixture()
    inst1 = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    inst2 = await combat.rejoindre(zone_id, "p2", "Eau", "Cancer", gabarits)
    assert inst1.id == inst2.id


async def test_rejoindre_cree_une_nouvelle_instance_une_fois_pleine(monkeypatch):
    monkeypatch.setenv("JEU_FACTIONS_INSTANCE_CAPACITE", "1")
    zone_id, gabarits = _mobs_zone_fixture()
    inst1 = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    combat.enregistrer_connexion(inst1, "p1", object())
    inst2 = await combat.rejoindre(zone_id, "p2", "Eau", "Cancer", gabarits)
    assert inst1.id != inst2.id


async def test_quitter_retire_le_joueur_et_marque_linstance_vide():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    combat.enregistrer_connexion(inst, "p1", object())
    combat.quitter(inst, "p1", horodatage=100.0)
    assert "p1" not in inst.etat["joueurs"]
    assert inst.derniere_activite == 100.0


async def test_instance_expiree_apres_le_delai_de_grace(monkeypatch):
    monkeypatch.setenv("COMBAT_INSTANCE_GRACE_S", "30")
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    combat.enregistrer_connexion(inst, "p1", object())
    combat.quitter(inst, "p1", horodatage=100.0)
    assert not combat.instance_expiree(inst, horodatage=110.0)
    assert combat.instance_expiree(inst, horodatage=131.0)


async def test_fermer_instance_la_retire_du_registre():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    assert inst in combat._INSTANCES[zone_id]
    combat.fermer_instance(inst)
    assert inst not in combat._INSTANCES[zone_id]


async def test_un_tick_applique_la_simulation_pure():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    x_avant = inst.etat["joueurs"]["p1"]["x"]
    actions = [{"type": "deplacement", "personnage_id": "p1", "direction": {"x": 1, "y": 0}}]
    await combat.un_tick(inst, actions, dt=1.0, competences={}, horodatage=0.0)
    assert inst.etat["joueurs"]["p1"]["x"] > x_avant


async def test_un_tick_persiste_la_victoire_de_zone_a_la_mort_du_boss():
    zone_id, gabarits = _mobs_zone_fixture()
    inst = await combat.rejoindre(zone_id, "p1", "Feu", "Bélier", gabarits)
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    inst.etat["mobs"][boss_id]["pv"] = 0
    inst.etat["mobs"][boss_id]["degats_recus_par_guilde"] = {"Bélier": 400}
    evenements = await combat.un_tick(inst, [], dt=0.1, competences={}, horodatage=0.0)
    assert any(e["type"] == "boss_tue" for e in evenements)
    assert zones.lire_zone(zone_id)["etat"] == "vaincue"
    scores = {s["guilde"]: s["points_cumules"] for s in zones.lire_zone(zone_id)["scores"]}
    assert scores["Bélier"] == 400
