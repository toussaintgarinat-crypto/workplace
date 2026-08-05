"""Persistance du moteur de démarchage POSTAL (registre par adresse + courriers/tokens)
— motif briques/mail/stockage.py::demarchage_* (email), réindexé par adresse."""
import stockage


def test_demarchage_postal_lire_absent_rend_none():
    assert stockage.demarchage_postal_lire("t1", "12 Rue X") is None


def test_demarchage_postal_enregistrer_contact_incremente():
    a = stockage.demarchage_postal_enregistrer_contact("t2", "12 Rue X, Castres")
    assert a["nb_contacts"] == 1 and a["opt_out"] is False
    b = stockage.demarchage_postal_enregistrer_contact("t2", "12 Rue X, Castres")
    assert b["nb_contacts"] == 2


def test_demarchage_postal_desinscrire_fige_opt_out():
    stockage.demarchage_postal_enregistrer_contact("t3", "4 Impasse Y")
    d = stockage.demarchage_postal_desinscrire("t3", "4 Impasse Y")
    assert d["opt_out"] is True
    # Un nouveau contact APRÈS désinscription ne réactive jamais l'opt-out.
    e = stockage.demarchage_postal_enregistrer_contact("t3", "4 Impasse Y")
    assert e["opt_out"] is True


def test_demarchage_postal_lister_isole_par_tenant():
    stockage.demarchage_postal_enregistrer_contact("t4-moi", "7 Rue Z")
    assert stockage.demarchage_postal_lister("t4-voisin") == []
    assert len(stockage.demarchage_postal_lister("t4-moi")) == 1


def test_creer_courrier_genere_un_token_unique():
    c1 = stockage.creer_courrier("t5", adresse="12 Rue X", commune="Castres",
                                 lead_id="lead-1", contenu="Bonjour...")
    c2 = stockage.creer_courrier("t5", adresse="4 Rue Y", contenu="Bonjour...")
    assert c1["token"] and c2["token"] and c1["token"] != c2["token"]
    assert c1["statut"] == "brouillon" and c1["lead_id"] == "lead-1"


def test_lire_courrier_cloisonne_par_tenant():
    c = stockage.creer_courrier("t6-moi", adresse="9 Rue A", contenu="X")
    assert stockage.lire_courrier("t6-moi", c["id"]) is not None
    assert stockage.lire_courrier("t6-voisin", c["id"]) is None


def test_lire_courrier_par_token_traverse_les_tenants():
    """PAS cloisonné : la page publique n'a aucun tenant à présenter."""
    c = stockage.creer_courrier("t7", adresse="1 Rue B", contenu="X")
    trouve = stockage.lire_courrier_par_token(c["token"])
    assert trouve and trouve["id"] == c["id"] and trouve["tenant"] == "t7"
    assert stockage.lire_courrier_par_token("token-inexistant") is None


def test_marquer_courrier_envoye_puis_repondu():
    c = stockage.creer_courrier("t8", adresse="3 Rue C", contenu="X")
    envoye = stockage.marquer_courrier_envoye("t8", c["id"])
    assert envoye["statut"] == "envoye" and envoye["envoye_le"]
    repondu = stockage.marquer_courrier_repondu(c["token"])
    assert repondu["statut"] == "repondu" and repondu["reponse_le"]
