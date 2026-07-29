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
