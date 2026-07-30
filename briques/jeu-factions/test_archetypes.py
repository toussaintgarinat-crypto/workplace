from datetime import datetime, timezone

import archetypes as A


def test_archetypes_signature_a_10_entrees_de_3_stats():
    assert len(A.ARCHETYPES_SIGNATURE) == 10
    for stats in A.ARCHETYPES_SIGNATURE.values():
        assert len(stats) == 3


def test_seed_zones_archetype_cree_3_etapes_par_archetype():
    A.seed_zones_archetype()
    for archetype in A.ARCHETYPES_SIGNATURE:
        etapes = A.lister_etapes(archetype)
        assert len(etapes) == 3
        assert [e["ordre"] for e in etapes] == [1, 2, 3]


def test_seed_est_idempotent():
    A.seed_zones_archetype()
    A.seed_zones_archetype()
    assert len(A.lister_etapes("Le Sage Contemplatif")) == 3


def test_prochaine_etape_personnage_neuf_est_la_premiere():
    A.seed_zones_archetype()
    etapes = A.lister_etapes("Le Sage Contemplatif")
    assert A.prochaine_etape("perso-neuf", "Le Sage Contemplatif") == etapes[0]["id"]


def test_prochaine_etape_apres_completion_avance():
    A.seed_zones_archetype()
    etapes = A.lister_etapes("Le Sage Contemplatif")
    A.marquer_etape_vaincue("perso-x", etapes[0]["id"])
    assert A.prochaine_etape("perso-x", "Le Sage Contemplatif") == etapes[1]["id"]


def test_prochaine_etape_none_quand_tout_vaincu():
    A.seed_zones_archetype()
    etapes = A.lister_etapes("Le Gardien Loyal")
    for e in etapes:
        A.marquer_etape_vaincue("perso-y", e["id"])
    assert A.prochaine_etape("perso-y", "Le Gardien Loyal") is None


def test_calculer_resolution_pure():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}},
              {"personnage_id": "p2", "stats": {"Charisme": 10, "Combativité": 5, "Énergie": 5}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100)
    assert res["total"] == 110
    assert res["vaincue"] is True


def test_debloquer_competence_si_existe():
    A.seed_zones_archetype()
    A.seed_competences()
    etapes = A.lister_etapes("Le Meneur Charismatique")
    A.debloquer_competence_si_existe("perso-z", etapes[0]["id"])
    debloquees = A.lister_competences_debloquees("perso-z")
    assert len(debloquees) == 1
    assert debloquees[0]["archetype"] == "Le Meneur Charismatique"


def test_debloquer_competence_deux_fois_ne_duplique_pas():
    A.seed_zones_archetype()
    A.seed_competences()
    etapes = A.lister_etapes("Le Meneur Charismatique")
    A.debloquer_competence_si_existe("perso-w", etapes[0]["id"])
    A.debloquer_competence_si_existe("perso-w", etapes[0]["id"])
    assert len(A.lister_competences_debloquees("perso-w")) == 1


def test_seed_competences_definit_un_effet_pour_chaque_etape():
    A.seed_zones_archetype()
    A.seed_competences()
    effets = A.lister_toutes_competences_avec_effet()
    assert len(effets) == 30  # 10 archétypes x 3 étapes
    assert all(e["effet_type"] in ("degats", "soin", "bouclier") for e in effets.values())
    assert all(isinstance(e["magnitude"], int) and e["magnitude"] > 0 for e in effets.values())


def test_seed_competences_est_idempotent_et_backfill_les_lignes_existantes():
    A.seed_zones_archetype()
    A.seed_competences()
    avant = A.lister_toutes_competences_avec_effet()
    A.seed_competences()
    apres = A.lister_toutes_competences_avec_effet()
    assert avant == apres


def test_seed_competences_backfill_une_ligne_deja_existante_sans_effet():
    A.seed_zones_archetype()
    # simule une compétence seedée AVANT ce plan (pas d'effet), motif déjà utilisé en
    # production sur le HP — le seed doit la compléter, pas la dupliquer.
    import stockage as S
    import uuid
    etape = A.lister_etapes("Le Sage Contemplatif")[0]
    with S._conn() as c:
        c.execute("""INSERT INTO competences (id, nom, texte, archetype, ordre_etape)
                     VALUES (?,?,?,?,?)""",
                  (uuid.uuid4().hex, "Compétence — ancienne", "texte", "Le Sage Contemplatif",
                   etape["ordre"]))
    A.seed_competences()
    effets = A.lister_toutes_competences_avec_effet()
    trouvee = [e for cid, e in effets.items()]
    assert any(e["effet_type"] == "degats" for e in trouvee)  # ordre 1 → degats
    # une seule ligne pour cette étape (pas de doublon inséré par-dessus l'ancienne)
    with S._conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM competences WHERE archetype=? AND ordre_etape=?",
                      ("Le Sage Contemplatif", etape["ordre"])).fetchone()["n"]
    assert n == 1


def test_bonus_idle_sans_presence_est_nul():
    assert A.bonus_idle(None, datetime.now(timezone.utc), taux_par_heure=2.0, plafond_heures=24) == 0


def test_bonus_idle_arrondit_a_lentier_inferieur():
    maintenant = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    derniere = datetime(2026, 7, 30, 11, 20, 0, tzinfo=timezone.utc)  # 40 min plus tôt
    bonus = A.bonus_idle(derniere.isoformat(), maintenant, taux_par_heure=1.0, plafond_heures=24)
    assert bonus == 0  # 0.667h x 1 pt/h = 0.667 → arrondi à 0


def test_bonus_idle_proportionnel_au_temps_ecoule():
    maintenant = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    derniere = datetime(2026, 7, 30, 7, 0, 0, tzinfo=timezone.utc)  # 5h plus tôt
    bonus = A.bonus_idle(derniere.isoformat(), maintenant, taux_par_heure=2.0, plafond_heures=24)
    assert bonus == 10  # 5h x 2 pts/h


def test_bonus_idle_plafonne_au_dela_du_plafond():
    maintenant = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
    derniere = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)  # 48h plus tôt
    bonus = A.bonus_idle(derniere.isoformat(), maintenant, taux_par_heure=2.0, plafond_heures=24)
    assert bonus == 48  # plafonné à 24h x 2 pts/h, pas 48h x 2


def test_bonus_idle_futur_ou_maintenant_est_nul():
    maintenant = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert A.bonus_idle(maintenant.isoformat(), maintenant, taux_par_heure=2.0, plafond_heures=24) == 0


def test_calculer_resolution_sans_bonus_est_inchangee():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100)
    assert res["total"] == 90
    assert res["vaincue"] is False


def test_calculer_resolution_bonus_sur_membre_absent_est_ignore():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100,
                                bonus_par_membre={"pX": 999})
    assert res["total"] == 90


def test_calculer_resolution_bonus_ajoute_au_membre_concerne():
    membres = [{"personnage_id": "p1", "stats": {"Charisme": 40, "Combativité": 30, "Énergie": 20}}]
    res = A.calculer_resolution(membres, ("Charisme", "Combativité", "Énergie"), difficulte=100,
                                bonus_par_membre={"p1": 15})
    assert res["total"] == 105
    assert res["vaincue"] is True


def test_seed_zones_archetype_a_un_contenu_narratif_distinct_par_archetype():
    A.seed_zones_archetype()
    noms = set()
    for archetype in A.ARCHETYPES_SIGNATURE:
        for e in A.lister_etapes(archetype):
            assert "étape" not in e["nom"].lower()
            noms.add(e["nom"])
    assert len(noms) == 30  # aucun texte dupliqué entre archétypes/étapes
