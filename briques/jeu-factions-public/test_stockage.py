import stockage as S


def test_creer_et_lire_personnage():
    S.assurer_joueur("cleA", "Alice")
    p = S.creer_personnage("cleA", "Aria", {"date_naissance": "1990-09-05"},
                           {"portrait": {"archetype": "Le Sage Contemplatif", "stats": {"Sagesse": 100}}})
    assert p["nom"] == "Aria"
    assert p["zone_actuelle"] is None
    lu = S.lire_personnage("cleA", p["id"])
    assert lu["snapshot_holistique"]["portrait"]["archetype"] == "Le Sage Contemplatif"


def test_lire_personnage_dun_autre_compte_renvoie_none():
    S.assurer_joueur("cleB", "Bob")
    p = S.creer_personnage("cleB", "Vorn", {"date_naissance": "1985-01-01"}, {"portrait": {}})
    assert S.lire_personnage("cleA", p["id"]) is None


def test_lister_personnages_filtre_par_compte():
    S.assurer_joueur("cleC", "Cid")
    S.creer_personnage("cleC", "Un", {"date_naissance": "2000-01-01"}, {"portrait": {}})
    S.creer_personnage("cleC", "Deux", {"date_naissance": "2000-01-02"}, {"portrait": {}})
    noms = {p["nom"] for p in S.lister_personnages("cleC")}
    assert noms == {"Un", "Deux"}


def test_un_compte_peut_avoir_plusieurs_personnages():
    S.assurer_joueur("cleD", "Dora")
    a = S.creer_personnage("cleD", "A", {"date_naissance": "1999-01-01"}, {"portrait": {}})
    b = S.creer_personnage("cleD", "B", {"date_naissance": "1999-01-02"}, {"portrait": {}})
    assert a["id"] != b["id"]
    assert len(S.lister_personnages("cleD")) == 2


def test_assigner_zone():
    S.assurer_joueur("cleE", "Eve")
    p = S.creer_personnage("cleE", "Zed", {"date_naissance": "2001-05-05"}, {"portrait": {}})
    maj = S.assigner_zone("cleE", p["id"], "zone-belier")
    assert maj["zone_actuelle"] == "zone-belier"


def test_assigner_zone_personnage_absent_renvoie_none():
    assert S.assigner_zone("cleE", "inconnu", "zone-belier") is None


def test_log_resolution_ne_leve_pas():
    S.log_resolution("zone-belier", None, {"Bélier": 10}, "vaincue")
    S.log_resolution(None, "arch-1", {"perso-1": 5}, "en_cours")


def test_migration_colonnes_effet_est_presente_et_idempotente():
    with S._conn() as c:
        colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    assert {"effet_type", "magnitude", "portee", "cooldown_s"} <= colonnes
    S._conn()


def test_enregistrer_presence_puis_lire():
    S.assurer_joueur("cleF", "Finn")
    assert S.lire_derniere_presence("cleF") is None
    S.enregistrer_presence("cleF")
    assert S.lire_derniere_presence("cleF") is not None


def test_enregistrer_presence_cree_le_joueur_si_absent():
    assert S.lire_derniere_presence("cleG") is None
    S.enregistrer_presence("cleG")
    assert S.lire_derniere_presence("cleG") is not None


def test_lire_derniere_presence_personnage_suit_le_compte_proprietaire():
    S.assurer_joueur("cleH", "Hugo")
    p = S.creer_personnage("cleH", "Perso", {"date_naissance": "1990-01-01"}, {"portrait": {}})
    assert S.lire_derniere_presence_personnage(p["id"]) is None
    S.enregistrer_presence("cleH")
    assert S.lire_derniere_presence_personnage(p["id"]) is not None


def test_lire_derniere_presence_personnage_inconnu_est_none():
    assert S.lire_derniere_presence_personnage("perso-inconnu") is None


def test_migration_derniere_presence_est_presente_et_idempotente():
    with S._conn() as c:
        colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    assert "derniere_presence" in colonnes
    S._conn()


def test_creer_compte_puis_le_relire_par_email():
    c = S.creer_compte("alice@example.com", "hash-bidon", "Alice")
    assert c["email"] == "alice@example.com"
    relu = S.lire_compte_par_email("alice@example.com")
    assert relu["id"] == c["id"]
    assert relu["mot_de_passe_hash"] == "hash-bidon"


def test_lire_compte_par_email_absent_renvoie_none():
    assert S.lire_compte_par_email("jamais-inscrit@example.com") is None


def test_creer_compte_email_deja_pris_leve_integrityerror():
    import sqlite3
    S.creer_compte("bob@example.com", "hash1", "Bob")
    try:
        S.creer_compte("bob@example.com", "hash2", "Bob2")
        assert False, "devait lever IntegrityError"
    except sqlite3.IntegrityError:
        pass
