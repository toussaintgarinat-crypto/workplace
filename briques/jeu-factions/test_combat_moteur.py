import combat_moteur as CM

MOB_ZONE = [{"id": "boss-1", "nom": "Boss", "role": "boss", "pv_max": 50,
            "degats_attaque": 5, "cooldown_attaque_s": 1.0, "portee_aggro": 200,
            "portee_attaque": 20}]

COMPETENCE_DEGATS = {"sort-degats": {"effet_type": "degats", "magnitude": 30,
                                     "portee": 100, "cooldown_s": 2.0}}
COMPETENCE_SOIN = {"sort-soin": {"effet_type": "soin", "magnitude": 15,
                                 "portee": 100, "cooldown_s": 5.0}}
COMPETENCE_BOUCLIER = {"sort-bouclier": {"effet_type": "bouclier", "magnitude": 20,
                                         "portee": 100, "cooldown_s": 5.0}}
COMPETENCE_ETOURDI = {"sort-etourdi": {"effet_type": "etourdissement", "magnitude": 3.0,
                                       "portee": 100, "cooldown_s": 8.0}}
COMPETENCE_DOT = {"sort-dot": {"effet_type": "dot", "magnitude": 10,
                               "portee": 100, "cooldown_s": 8.0}}


def _etat_avec_joueur():
    etat = CM.nouvel_etat_instance("zone-1", 800, MOB_ZONE)
    return CM.ajouter_joueur(etat, "p1", "Feu", "Bélier")


def _joueur_colle_au_mob(etat, mob_id, pid="p1"):
    etat["joueurs"][pid]["x"] = etat["mobs"][mob_id]["x"]
    etat["joueurs"][pid]["y"] = etat["mobs"][mob_id]["y"]
    return etat


def test_nouvel_etat_instance_place_le_boss_au_centre():
    etat = CM.nouvel_etat_instance("zone-1", 800, MOB_ZONE)
    mob_id = next(iter(etat["mobs"]))
    assert etat["mobs"][mob_id]["x"] == 400
    assert etat["mobs"][mob_id]["y"] == 400
    assert etat["mobs"][mob_id]["role"] == "boss"


def test_ajouter_puis_retirer_joueur():
    etat = _etat_avec_joueur()
    assert "p1" in etat["joueurs"]
    etat = CM.retirer_joueur(etat, "p1")
    assert "p1" not in etat["joueurs"]


def test_deplacement_borne_par_larene():
    etat = _etat_avec_joueur()
    actions = [{"type": "deplacement", "personnage_id": "p1", "direction": {"x": -1, "y": -1}}]
    etat, _ = CM.avancer_tick(etat, actions, dt=10.0, competences={}, horodatage=0.0,
                              respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["x"] == 0
    assert etat["joueurs"]["p1"]["y"] == 0


def test_sort_hors_de_portee_est_un_noop():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat["joueurs"]["p1"]["x"], etat["joueurs"]["p1"]["y"] = 0, 0
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, evenements = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                                       horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 50
    assert evenements == []


def test_degats_appliques_et_mob_tue():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 20
    etat, ev2 = CM.avancer_tick(etat, actions, dt=3.0, competences=COMPETENCE_DEGATS,
                                horodatage=3.0, respawn_delai_s=60.0)
    assert mob_id not in etat["mobs"]
    mort = next(e for e in ev2 if e["type"] == "boss_tue")
    assert mort["contributions"] == {"Bélier": 50}


def test_cooldown_bloque_la_reutilisation_immediate():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 20
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.5, respawn_delai_s=60.0)  # cooldown 2s pas écoulé
    assert etat["mobs"][mob_id]["pv"] == 20


def test_plusieurs_sorts_au_meme_tick_dans_lordre():
    mob_zone_resistant = [{**MOB_ZONE[0], "pv_max": 200}]
    etat = CM.nouvel_etat_instance("zone-1", 800, mob_zone_resistant)
    etat = CM.ajouter_joueur(etat, "p1", "Feu", "Bélier")
    etat = CM.ajouter_joueur(etat, "p2", "Eau", "Cancer")
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id, "p1")
    etat = _joueur_colle_au_mob(etat, mob_id, "p2")
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats", "cible_id": mob_id},
              {"type": "sort", "personnage_id": "p2", "competence_id": "sort-degats", "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {"Bélier": 30, "Cancer": 30}


def test_mob_nattaque_que_dans_sa_portee_daggro():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat["mobs"][mob_id]["portee_aggro"] = 10
    etat["joueurs"]["p1"]["x"], etat["joueurs"]["p1"]["y"] = 0, 0  # loin du boss (400,400)
    etat, _ = CM.avancer_tick(etat, [], dt=1.0, competences={}, horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["cible_id"] is None
    assert etat["joueurs"]["p1"]["pv"] == 100


def test_effet_soin_augmente_les_pv():
    etat = _etat_avec_joueur()
    etat["joueurs"]["p1"]["pv"] = 50
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-soin", "cible_id": "p1"}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_SOIN,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["pv"] == 65


def test_effet_bouclier_absorbe_les_degats_suivants():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-bouclier", "cible_id": "p1"}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_BOUCLIER,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["bouclier"] == 20
    # le boss (degats_attaque=5, cooldown_restant=0, joueur dans sa portee_attaque) attaque :
    etat = _joueur_colle_au_mob(etat, mob_id)
    etat, _ = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=1.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["pv"] == 100  # entièrement absorbé
    assert etat["joueurs"]["p1"]["bouclier"] == 15


def test_effet_etourdissement_empeche_le_mob_dattaquer():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-etourdi",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_ETOURDI,
                              horodatage=0.0, respawn_delai_s=60.0)
    etat, _ = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=1.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["pv"] == 100  # le mob était étourdi, n'a pas pu attaquer


def test_effet_dot_inflige_des_degats_dans_la_duree():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-dot",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DOT,
                              horodatage=0.0, respawn_delai_s=60.0)
    etat, _ = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=1.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["pv"] == 48  # 50 - 1 (tick de cast) - 1 (tick suivant)


def test_actions_malformees_sont_des_noop_silencieux():
    etat = _etat_avec_joueur()
    x_avant, y_avant = etat["joueurs"]["p1"]["x"], etat["joueurs"]["p1"]["y"]
    actions = [
        {"personnage_id": "p1"},                                            # type manquant
        {"type": "deplacement", "personnage_id": "p1"},                     # direction manquante
        {"type": "deplacement", "personnage_id": "p1", "direction": "nord"},  # direction non-dict
        {"type": "sort", "personnage_id": "p1"},                            # competence_id manquant
        {"type": "sort"},                                                   # personnage_id manquant
    ]
    etat, evenements = CM.avancer_tick(etat, actions, dt=1.0, competences={}, horodatage=0.0,
                                       respawn_delai_s=60.0)
    assert etat["joueurs"]["p1"]["x"] == x_avant
    assert etat["joueurs"]["p1"]["y"] == y_avant
    assert evenements == []


def test_soin_revive_un_joueur_ko():
    etat = _etat_avec_joueur()
    etat = CM.ajouter_joueur(etat, "p2", "Eau", "Cancer")
    etat["joueurs"]["p2"]["pv"] = 0
    etat["joueurs"]["p2"]["etat"] = "ko"
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-soin", "cible_id": "p2"}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_SOIN,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["joueurs"]["p2"]["etat"] == "actif"
    assert etat["joueurs"]["p2"]["pv"] == 15


def test_boss_respawn_apres_le_delai():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat["mobs"][mob_id]["pv"] = 0
    etat, ev1 = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=0.0, respawn_delai_s=5.0)
    assert any(e["type"] == "boss_tue" for e in ev1)
    assert not any(m["role"] == "boss" for m in etat["mobs"].values())
    etat, ev2 = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=2.0, respawn_delai_s=5.0)
    assert not any(m["role"] == "boss" for m in etat["mobs"].values())  # trop tôt
    etat, ev3 = CM.avancer_tick(etat, [], dt=0.1, competences={}, horodatage=6.0, respawn_delai_s=5.0)
    assert any(m["role"] == "boss" for m in etat["mobs"].values())
    assert any(e["type"] == "boss_reapparu" for e in ev3)


def test_ajouter_joueur_cle_contribution_par_defaut_est_le_signe():
    etat = _etat_avec_joueur()
    assert etat["joueurs"]["p1"]["cle_contribution"] == "Bélier"


def test_ajouter_joueur_cle_contribution_explicite_bucket_par_cle():
    etat = CM.nouvel_etat_instance("zone-1", 800, MOB_ZONE)
    etat = CM.ajouter_joueur(etat, "p1", "Archétype", "p1", cle_contribution="perso-1")
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {"perso-1": 30}


def test_appliquer_bonus_degats_reduit_les_pv_du_boss():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = CM.appliquer_bonus_degats(etat, 20, "perso-1")
    assert etat["mobs"][mob_id]["pv"] == 30
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {"perso-1": 20}


def test_appliquer_bonus_degats_zero_est_un_noop():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = CM.appliquer_bonus_degats(etat, 0, "perso-1")
    assert etat["mobs"][mob_id]["pv"] == 50
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {}
