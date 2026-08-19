"""Tests de la persistance (S193). Isolation par user_id, journal d'exécutions par
campagne — motif briques/veille-info/test_stockage.py."""
import stockage


def test_creer_et_lister_campagnes():
    c = stockage.creer_campagne("alice", "zone-1")
    assert c["zone_id"] == "zone-1" and c["actif"] is True
    campagnes = stockage.lister_campagnes("alice")
    assert len(campagnes) == 1 and campagnes[0]["id"] == c["id"]


def test_lister_campagnes_isole_par_user_id():
    stockage.creer_campagne("bob", "zone-de-bob")
    assert all(c["zone_id"] != "zone-de-bob" for c in stockage.lister_campagnes("alice"))


def test_supprimer_campagne_isole_par_user_id():
    c = stockage.creer_campagne("carol", "zone-a-supprimer")
    assert stockage.supprimer_campagne("mallory", c["id"]) is False
    assert stockage.supprimer_campagne("carol", c["id"]) is True
    assert stockage.lister_campagnes("carol", actives_seulement=True) == []


def test_supprimer_campagne_est_un_soft_delete():
    """`supprimer_campagne` désactive (`actif = 0`) au lieu de DELETE — la ligne (et son
    historique dans `executions`) survit, elle disparaît seulement de la liste par défaut
    « actives seulement » côté route HTTP."""
    c = stockage.creer_campagne("dave-soft", "zone-soft")
    assert stockage.supprimer_campagne("dave-soft", c["id"]) is True
    toutes = stockage.lister_campagnes("dave-soft")
    assert len(toutes) == 1
    assert toutes[0]["id"] == c["id"]
    assert toutes[0]["actif"] is False


def test_lister_user_ids_actifs_ignore_campagnes_inactives():
    stockage.creer_campagne("dave", "zone-active")
    seule = stockage.creer_campagne("dave-seul-inactif", "zone-off")
    with stockage._conn() as c:
        c.execute("UPDATE campagnes SET actif = 0 WHERE id = ?", (seule["id"],))
    ids = stockage.lister_user_ids_actifs()
    assert "dave" in ids
    assert "dave-seul-inactif" not in ids


def test_inserer_et_lister_executions():
    c = stockage.creer_campagne("erin", "zone-erin")
    stockage.inserer_execution(c["id"], trouves=3, deja_connus=1, nouveaux_crm=2, erreur=None)
    executions = stockage.lister_executions(c["id"])
    assert len(executions) == 1
    assert executions[0]["trouves"] == 3 and executions[0]["erreur"] is None


def test_executions_isole_par_campagne_id():
    c1 = stockage.creer_campagne("grace", "zone-grace-1")
    c2 = stockage.creer_campagne("grace", "zone-grace-2")
    stockage.inserer_execution(c1["id"], trouves=5, deja_connus=2, nouveaux_crm=3, erreur=None)
    stockage.inserer_execution(c2["id"], trouves=7, deja_connus=1, nouveaux_crm=6, erreur=None)

    executions_c1 = stockage.lister_executions(c1["id"])
    assert len(executions_c1) == 1
    assert executions_c1[0]["campagne_id"] == c1["id"]
    assert executions_c1[0]["trouves"] == 5

    executions_c2 = stockage.lister_executions(c2["id"])
    assert len(executions_c2) == 1
    assert executions_c2[0]["campagne_id"] == c2["id"]
    assert executions_c2[0]["trouves"] == 7


def test_maj_derniere_execution():
    c = stockage.creer_campagne("frank", "zone-frank")
    assert c["derniere_execution"] is None
    stockage.maj_derniere_execution(c["id"])
    maj = stockage.lister_campagnes("frank")[0]
    assert maj["derniere_execution"] is not None


def test_creer_campagne_type_par_defaut_b2b():
    c = stockage.creer_campagne("user-type-defaut", "zone-x")
    assert c["type"] == "b2b"


def test_creer_campagne_type_b2c():
    c = stockage.creer_campagne("user-type-b2c", "zone-logements", type_="b2c")
    assert c["type"] == "b2c"


def test_lister_campagnes_expose_le_type():
    stockage.creer_campagne("user-liste-type", "zone-y", type_="b2c")
    campagnes = stockage.lister_campagnes("user-liste-type")
    assert campagnes[0]["type"] == "b2c"


def test_creer_campagne_stocke_zone_nom():
    c = stockage.creer_campagne("zn-alice", "zone-1", zone_nom="Restos Castres")
    assert c["zone_nom"] == "Restos Castres"
    relue = stockage.lister_campagnes("zn-alice")[0]
    assert relue["zone_nom"] == "Restos Castres"


def test_creer_campagne_zone_nom_optionnel():
    c = stockage.creer_campagne("zn-bob", "zone-2")
    assert c["zone_nom"] is None


def test_lire_campagne_isole_par_user_id():
    c = stockage.creer_campagne("zn-carol", "zone-3")
    assert stockage.lire_campagne("zn-carol", c["id"]) == c
    assert stockage.lire_campagne("zn-mallory", c["id"]) is None


def test_lire_campagne_introuvable_rend_none():
    assert stockage.lire_campagne("zn-dave", 999999) is None
