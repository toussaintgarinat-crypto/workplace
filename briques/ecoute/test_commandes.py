"""Tests du cycle de commande (S43) — SQLite side-car, hors ligne (pas de Stripe)."""
import pytest

import commandes as cmd


@pytest.fixture
def magasin(tmp_path):
    m = cmd.MagasinCommandes(db=str(tmp_path / "t.db"))
    m.init_db()
    return m


def test_slugifier():
    assert cmd.slugifier("Acme Corp !") == "acme_corp"
    # FR-first : les accents sont translittérés, pas jetés (sinon Léon → l_on).
    assert cmd.slugifier("  Éléphant-Bleu  ") == "elephant_bleu"
    assert cmd.slugifier("Maison Léon") == cmd.slugifier("maison leon")  # idempotence des graphies
    assert cmd.slugifier("!!!") == ""


def test_creer_en_attente(magasin):
    c = magasin.creer("Acme Corp")
    assert c["statut"] == "en_attente_paiement"
    assert c["modele"] == "acme_corp"
    assert c["prix_cents"] == cmd.PRIX_CENTS


def test_creer_nom_vide_refuse(magasin):
    with pytest.raises(ValueError):
        magasin.creer("!!!")


def test_idempotent_pas_de_doublon(magasin):
    c1 = magasin.creer("Acme Corp")
    c2 = magasin.creer("acme  corp")  # même slug
    assert c1["id"] == c2["id"]  # on rend la commande en cours, pas un doublon (pas de double-débit)


def test_transitions_gardees(magasin):
    c = magasin.creer("Acme")
    # saut interdit en_attente → en_entrainement
    with pytest.raises(ValueError):
        magasin.changer_etat(c["id"], "en_entrainement")
    # chemin nominal
    magasin.marquer_payee(c["id"])
    assert magasin.get(c["id"])["statut"] == "payee"
    magasin.changer_etat(c["id"], "en_entrainement")
    livree = magasin.changer_etat(c["id"], "livree", factice=True)
    assert livree["statut"] == "livree" and livree["factice"] == 1


def test_marquer_payee_idempotent(magasin):
    c = magasin.creer("Acme")
    magasin.marquer_payee(c["id"])
    magasin.changer_etat(c["id"], "en_entrainement")
    # re-payer ne régresse pas depuis en_entrainement
    again = magasin.marquer_payee(c["id"])
    assert again["statut"] == "en_entrainement"


def test_changer_etat_idempotent_meme_etat(magasin):
    c = magasin.creer("Acme")
    magasin.marquer_payee(c["id"])
    assert magasin.changer_etat(c["id"], "payee")["statut"] == "payee"  # pas d'erreur


def test_incr_relance(magasin):
    c = magasin.creer("Acme")
    magasin.incr_relance(c["id"])
    magasin.incr_relance(c["id"])
    assert magasin.get(c["id"])["relances"] == 2


def test_livrees_et_session(magasin):
    c = magasin.creer("Acme")
    magasin.attacher_session(c["id"], "cs_test_123")
    assert magasin.par_session("cs_test_123")["id"] == c["id"]
    magasin.marquer_payee(c["id"])
    magasin.changer_etat(c["id"], "en_entrainement")
    magasin.changer_etat(c["id"], "livree")
    assert [x["id"] for x in magasin.livrees()] == [c["id"]]


def test_vue_projection(magasin):
    c = magasin.creer("Acme")
    v = cmd.vue(c)
    assert v["terminal"] is False and v["factice"] is False
    assert set(v) >= {"id", "nom_marque", "modele", "statut", "prix_cents", "devise"}
