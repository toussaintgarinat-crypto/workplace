from datetime import datetime, timedelta, timezone

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
    G.dissoudre_groupes_de_letape(etapes[0]["id"])
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
    G.dissoudre_groupes_de_letape("etape-qui-nexiste-pas")
    assert G.lire_groupe(g1["id"])["etat"] == "actif"
