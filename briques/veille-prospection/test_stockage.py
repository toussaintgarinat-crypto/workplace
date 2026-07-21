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
    assert stockage.lister_campagnes("carol") == []


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


def test_maj_derniere_execution():
    c = stockage.creer_campagne("frank", "zone-frank")
    assert c["derniere_execution"] is None
    stockage.maj_derniere_execution(c["id"])
    maj = stockage.lister_campagnes("frank")[0]
    assert maj["derniere_execution"] is not None
