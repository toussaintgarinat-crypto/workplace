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
    G.resoudre_groupes_actifs()   # se résout tout de suite (stats énormes) → dissous
    try:
        G.rejoindre_groupe(g["id"], p["id"])
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass


def test_resoudre_groupes_actifs_avance_la_cible_et_debloque_competence():
    A.seed_zones_archetype()
    A.seed_competences()
    p = _personnage("cleG5", "Cible4", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    G.creer_groupe(p["id"], etapes[0]["id"])
    resultats = G.resoudre_groupes_actifs()
    assert any(r["etat_resultant"] == "vaincue" for r in resultats)
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
    assert len(A.lister_competences_debloquees(p["id"])) == 1


def test_resoudre_groupes_actifs_carry_naide_pas_la_progression_de_laide():
    """Le carry ne triche pas la progression À PARTIR DE LA 2E ÉTAPE : un aide qui n'a pas
    complété l'étape précédente reste à SA propre étape, même s'il a contribué ses stats au
    groupe d'un autre. (Cas particulier assumé sur la toute PREMIÈRE étape d'une voie jamais
    touchée : `progression_archetype` ne distingue pas « jamais engagé » de « vise vraiment
    cette étape » — un aide totalement neuf y avance aussi si le groupe est vaincu, ce n'est
    pas une triche, c'est documenté dans le spec. La garantie testée ici démarre donc à
    l'étape 2, où la distinction redevient possible : SI l'aide n'a pas complété l'étape 1,
    l'étape 2 n'est structurellement pas sa propre prochaine étape.)"""
    A.seed_zones_archetype()
    A.seed_competences()
    p = _personnage("cleG6", "Cible5", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    aide = _personnage("cleG6b", "Copain", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    # p complète l'étape 1 seul ; aide n'y touche jamais (reste à l'étape 1 dans sa séquence).
    G.creer_groupe(p["id"], etapes[0]["id"])
    G.resoudre_groupes_actifs()
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
    assert A.prochaine_etape(aide["id"], "Le Meneur Charismatique") == etapes[0]["id"]
    # p vise maintenant l'étape 2 ; aide vient l'aider sans avoir fait l'étape 1 lui-même.
    g2 = G.creer_groupe(p["id"], etapes[1]["id"])
    G.rejoindre_groupe(g2["id"], aide["id"])
    G.resoudre_groupes_actifs()
    # p avance à l'étape 3 grâce à l'aide du copain...
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[2]["id"]
    # ...mais le copain reste bloqué à l'étape 1 : l'étape 2 n'était pas SA propre prochaine
    # étape (il n'a jamais complété la 1ʳᵉ), donc sa progression ne saute pas, même si ses
    # stats ont compté dans le total du groupe.
    assert A.prochaine_etape(aide["id"], "Le Meneur Charismatique") == etapes[0]["id"]


def test_resoudre_groupes_actifs_pas_vaincu_reste_actif():
    A.seed_zones_archetype()
    p = _personnage("cleG7", "Faible", {"Charisme": 1, "Combativité": 1, "Énergie": 1})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    resultats = G.resoudre_groupes_actifs()
    assert all(r["etat_resultant"] == "en_cours" for r in resultats if r["groupe_id"] == g["id"])
    with S._conn() as c:
        row = c.execute("SELECT etat FROM groupes WHERE id=?", (g["id"],)).fetchone()
    assert row["etat"] == "actif"


def test_resoudre_groupes_actifs_bonus_idle_comble_lecart(monkeypatch):
    A.seed_zones_archetype()
    monkeypatch.setattr(A, "TAUX_IDLE_PAR_HEURE", 1000.0)
    p = _personnage("cleG8", "Fatigue", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    with S._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cleG8"))
    etapes = A.lister_etapes("Le Meneur Charismatique")
    G.creer_groupe(p["id"], etapes[0]["id"])
    resultats = G.resoudre_groupes_actifs()
    # stats brutes = 30, bien sous la difficulté 80 de l'étape 1 — seul le bonus idle
    # (1h x 1000 pts/h, monkeypatché) permet de la franchir.
    assert any(r["etat_resultant"] == "vaincue" for r in resultats)
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]


def test_resoudre_groupes_actifs_bonus_idle_du_carry_ne_beneficie_pas_a_la_cible(monkeypatch):
    A.seed_zones_archetype()
    monkeypatch.setattr(A, "TAUX_IDLE_PAR_HEURE", 1000.0)
    p = _personnage("cleG10", "Cible7", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    aide = _personnage("cleG10b", "Portefaix", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    # p franchit l'étape 1 seul grâce à SON propre bonus idle (stats brutes 30, insuffisantes
    # seules face à la difficulté 80).
    with S._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cleG10"))
    G.creer_groupe(p["id"], etapes[0]["id"])
    G.resoudre_groupes_actifs()
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
    assert A.prochaine_etape(aide["id"], "Le Meneur Charismatique") == etapes[0]["id"]
    # p "revient" (présence remise à maintenant -> bonus nul pour la suite) ; aide reste idle
    # depuis 1h (bonus énorme avec le taux monkeypatché) mais rejoint en CARRY sur l'étape 2
    # de p — pas structurellement SA prochaine étape (la sienne reste l'étape 1).
    S.enregistrer_presence("cleG10")
    with S._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "cleG10b"))
    g2 = G.creer_groupe(p["id"], etapes[1]["id"])
    G.rejoindre_groupe(g2["id"], aide["id"])
    resultats = G.resoudre_groupes_actifs()
    # total brut = 30 (p) + 30 (aide) = 60, bien sous la difficulté 140 — si le bonus de aide
    # fuitait dans le total du groupe (1000+ pts), l'étape 2 serait vaincue à tort.
    assert all(r["etat_resultant"] == "en_cours" for r in resultats if r["groupe_id"] == g2["id"])
    assert A.prochaine_etape(p["id"], "Le Meneur Charismatique") == etapes[1]["id"]
