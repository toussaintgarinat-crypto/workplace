import archetypes as A
import stockage as S
import groupes as G


def _personnage(cle, nom, stats):
    S.assurer_joueur(cle, nom)
    return S.creer_personnage(cle, nom, {"date_naissance": "1990-01-01"},
                              {"traditions": {"signe_solaire": {"nom": "Lion"}},
                               "portrait": {"stats": stats}})


def test_creer_groupe_sur_la_prochaine_etape_ok():
    A.seed_zones_archetype()
    p = _personnage("cleG1", "Cible", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    assert g["personnage_cible_id"] == p["id"]
    assert g["etat"] == "actif"


def test_creer_groupe_sur_une_etape_sautee_leve_valueerror():
    A.seed_zones_archetype()
    p = _personnage("cleG2", "Sauteur", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    try:
        G.creer_groupe(p["id"], etapes[1]["id"])   # ordre 2, alors que sa prochaine est ordre 1
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass


def test_rejoindre_groupe_ok():
    A.seed_zones_archetype()
    p = _personnage("cleG3", "Cible2", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    aide = _personnage("cleG3b", "Aide", {"Charisme": 50, "Combativité": 50, "Énergie": 50})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    membre = G.rejoindre_groupe(g["id"], aide["id"])
    assert aide["id"] in membre["membres"]


def test_rejoindre_groupe_dissous_leve_valueerror():
    A.seed_zones_archetype()
    p = _personnage("cleG4", "Cible3", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    G.dissoudre_groupes_de_letape(etapes[0]["id"], [p["id"]])
    try:
        G.rejoindre_groupe(g["id"], p["id"])
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass


def test_lire_groupe_inconnu_est_none():
    assert G.lire_groupe("inconnu") is None


def test_lire_groupe_connu():
    A.seed_zones_archetype()
    p = _personnage("cleG11", "Solo", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    assert G.lire_groupe(g["id"])["id"] == g["id"]


def test_dissoudre_groupes_de_letape_ne_touche_pas_les_autres_etapes():
    A.seed_zones_archetype()
    p = _personnage("cleG12", "Autre", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g1 = G.creer_groupe(p["id"], etapes[0]["id"])
    G.dissoudre_groupes_de_letape("etape-qui-nexiste-pas", ["quelquun"])
    assert G.lire_groupe(g1["id"])["etat"] == "actif"


def test_lister_groupes_actifs_vide_si_aucun_groupe():
    A.seed_zones_archetype()
    groupes = G.lister_groupes_actifs()
    assert groupes == []


def test_lister_groupes_actifs_inclut_groupe_cree_avec_bons_champs():
    A.seed_zones_archetype()
    p = _personnage("cleG20", "Cible", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    groupes = G.lister_groupes_actifs()
    assert len(groupes) == 1
    groupe = groupes[0]
    assert groupe["id"] == g["id"]
    assert groupe["zone_archetype_id"] == etapes[0]["id"]
    assert groupe["personnage_cible_nom"] == "Cible"
    assert groupe["archetype"] == "Le Meneur Charismatique"
    assert groupe["ordre"] == 1
    assert groupe["etape_nom"] == etapes[0]["nom"]
    assert groupe["nb_membres"] == 1


def test_lister_groupes_actifs_compte_membres():
    A.seed_zones_archetype()
    p = _personnage("cleG21", "Cible", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    aide = _personnage("cleG21b", "Aide", {"Charisme": 50, "Combativité": 50, "Énergie": 50})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    G.rejoindre_groupe(g["id"], aide["id"])
    groupes = G.lister_groupes_actifs()
    assert len(groupes) == 1
    assert groupes[0]["nb_membres"] == 2


def test_lister_groupes_actifs_exclut_groupes_dissous():
    A.seed_zones_archetype()
    p = _personnage("cleG22", "Cible", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    G.dissoudre_groupes_de_letape(etapes[0]["id"], [p["id"]])
    groupes = G.lister_groupes_actifs()
    assert groupes == []
