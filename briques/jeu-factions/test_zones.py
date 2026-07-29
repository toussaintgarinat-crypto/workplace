import stockage as S
import zones as Z


def test_seed_zones_cree_les_12_zones():
    Z.seed_zones()
    zs = Z.lister_zones()
    assert len(zs) == 12
    assert {z["signe_natif"] for z in zs} == {
        "Bélier", "Taureau", "Gémeaux", "Cancer", "Lion", "Vierge",
        "Balance", "Scorpion", "Sagittaire", "Capricorne", "Verseau", "Poissons"}


def test_seed_zones_est_idempotent():
    Z.seed_zones()
    Z.seed_zones()
    assert len(Z.lister_zones()) == 12


def test_lire_zone_inconnue_none():
    assert Z.lire_zone("inconnue") is None


def test_calculer_resolution_pure_vaincue():
    personnages = [{"id": "p1", "signe": "Bélier", "stats": {"Combativité": 60, "Énergie": 20}},
                  {"id": "p2", "signe": "Lion", "stats": {"Combativité": 10, "Énergie": 10}}]
    res = Z.calculer_resolution(personnages, ["Combativité", "Énergie"], difficulte=90)
    assert res["total"] == 100
    assert res["vaincue"] is True
    assert res["par_guilde"] == {"Bélier": 80, "Lion": 20}


def test_calculer_resolution_pure_pas_vaincue():
    personnages = [{"id": "p1", "signe": "Bélier", "stats": {"Combativité": 5, "Énergie": 5}}]
    res = Z.calculer_resolution(personnages, ["Combativité", "Énergie"], difficulte=90)
    assert res["vaincue"] is False


def test_resoudre_toutes_zones_marque_vaincue_et_note_le_score():
    Z.seed_zones()
    S.assurer_joueur("cleF", "Fay")
    p = S.creer_personnage("cleF", "Ram", {"date_naissance": "1990-01-01"},
                           {"traditions": {"signe_solaire": {"nom": "Bélier"}},
                            "portrait": {"stats": {"Combativité": 200, "Énergie": 200}}})
    zs = Z.lister_zones()
    belier = next(z for z in zs if z["signe_natif"] == "Bélier")
    S.assigner_zone("cleF", p["id"], belier["id"])
    resultats = Z.resoudre_toutes_zones(["Combativité", "Énergie"])
    entree = next(r for r in resultats if r["zone_id"] == belier["id"])
    assert entree["etat_resultant"] == "vaincue"
    assert Z.lire_zone(belier["id"])["etat"] == "vaincue"


def test_resoudre_toutes_zones_ignore_les_zones_deja_vaincues():
    Z.seed_zones()
    zs = Z.lister_zones()
    scorpion = next(z for z in zs if z["signe_natif"] == "Scorpion")
    with S._conn() as c:
        c.execute("UPDATE zones SET etat='vaincue' WHERE id=?", (scorpion["id"],))
    resultats = Z.resoudre_toutes_zones(["Combativité", "Énergie"])
    assert all(r["zone_id"] != scorpion["id"] for r in resultats)


def test_lister_zones_inclut_les_scores():
    Z.seed_zones()
    zs = Z.lister_zones()
    assert all("scores" in z for z in zs)


def test_lire_zone_inclut_scores_et_historique():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    z = Z.lire_zone(zid)
    assert "scores" in z and "historique" in z


def test_lire_zone_scores_reflete_ajouter_score():
    Z.seed_zones()
    belier = next(z for z in Z.lister_zones() if z["signe_natif"] == "Bélier")
    Z.ajouter_score(belier["id"], "Bélier", 400)
    z = Z.lire_zone(belier["id"])
    assert z["scores"] == [{"guilde": "Bélier", "points_cumules": 400}]


def test_marquer_vaincue_si_premiere_fois():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    assert Z.marquer_vaincue_si_premiere_fois(zid) is True
    assert Z.lire_zone(zid)["etat"] == "vaincue"
    assert Z.marquer_vaincue_si_premiere_fois(zid) is False  # déjà vaincue, pas de re-déclenchement


def test_ajouter_score_cumule_par_guilde():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    Z.ajouter_score(zid, "Bélier", 30)
    Z.ajouter_score(zid, "Bélier", 20)
    Z.ajouter_score(zid, "Lion", 5)
    scores = {s["guilde"]: s["points_cumules"] for s in Z.lire_zone(zid)["scores"]}
    assert scores == {"Bélier": 50, "Lion": 5}


def test_ajouter_score_ignore_les_points_a_zero():
    Z.seed_zones()
    zid = Z.lister_zones()[0]["id"]
    Z.ajouter_score(zid, "Bélier", 0)
    assert Z.lire_zone(zid)["scores"] == []


def test_signe_personnage_lit_le_snapshot():
    assert Z.signe_personnage({"traditions": {"signe_solaire": {"nom": "Lion"}}}) == "Lion"
    assert Z.signe_personnage({}) is None
