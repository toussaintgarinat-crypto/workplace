"""Domaine pur : catégorisation, score d'importance, tri. Aucune dépendance externe."""
import domaine


def _msg(**kw):
    base = {"de": "x@y.fr", "de_nom": "X", "sujet": "", "extrait": "", "lu": True}
    base.update(kw)
    return base


def test_categoriser_facture():
    assert domaine.categoriser(_msg(sujet="Votre facture de juin")) == domaine.FACTURE
    assert domaine.categoriser(_msg(sujet="Your invoice is ready")) == domaine.FACTURE


def test_categoriser_rendez_vous():
    assert domaine.categoriser(_msg(sujet="Confirmation de votre rendez-vous")) == domaine.RENDEZ_VOUS


def test_categoriser_newsletter():
    assert domaine.categoriser(_msg(sujet="-50% ce week-end", de="newsletter@boutique.fr")) \
        == domaine.NEWSLETTER


def test_categoriser_notification():
    assert domaine.categoriser(_msg(sujet="Nouvelle connexion à votre compte")) == domaine.NOTIFICATION


def test_categoriser_personnel_vs_autre():
    # Expéditeur humain, rien de spécial → personnel.
    assert domaine.categoriser(_msg(sujet="Photos du week-end", de="papa@example.com")) \
        == domaine.PERSONNEL
    # Expéditeur machine sans mot-clé → autre.
    assert domaine.categoriser(_msg(sujet="ping", de="no-reply@service.com")) == domaine.AUTRE


def test_score_non_lu_plus_haut_que_lu():
    lu = domaine.score_importance(_msg(lu=True, sujet="coucou"))
    non_lu = domaine.score_importance(_msg(lu=False, sujet="coucou"))
    assert non_lu > lu


def test_score_urgence_remonte():
    normal = domaine.score_importance(_msg(sujet="point projet", de="thomas@client.com"))
    urgent = domaine.score_importance(_msg(sujet="URGENT relance", de="thomas@client.com"))
    assert urgent > normal


def test_score_newsletter_descend():
    promo = domaine.score_importance(_msg(lu=False, sujet="-50% soldes", de="newsletter@x.fr"))
    perso = domaine.score_importance(_msg(lu=False, sujet="déjeuner jeudi ?", de="ami@example.com"))
    assert perso > promo


def test_score_expediteur_connu_remonte():
    inconnu = domaine.score_importance(_msg(sujet="bonjour", de="x@y.fr"))
    connu = domaine.score_importance(_msg(sujet="bonjour", de="x@y.fr"), {"x@y.fr"})
    assert connu > inconnu


def test_score_borne_0_100():
    s = domaine.score_importance(_msg(lu=False, sujet="URGENT facture rdv", de="thomas@client.com"),
                                 {"thomas@client.com"})
    assert 0 <= s <= 100


def test_trier_met_le_plus_important_devant():
    msgs = [
        _msg(sujet="-50% soldes", de="newsletter@x.fr", lu=True),
        _msg(sujet="URGENT relance devis", de="thomas@client.com", lu=False),
    ]
    tries = domaine.trier(msgs)
    assert tries[0]["sujet"].startswith("URGENT")
    assert all("score" in m and "categorie" in m for m in tries)


def test_enrichir_ne_mute_pas_l_entree():
    m = _msg(sujet="facture")
    domaine.enrichir(m)
    assert "score" not in m and "categorie" not in m


def test_grouper_par_categorie_ordre_stable():
    msgs = domaine.trier([
        _msg(sujet="facture juin"),
        _msg(sujet="rendez-vous lundi"),
        _msg(sujet="-50% promo", de="newsletter@x.fr"),
    ])
    groupes = domaine.grouper_par_categorie(msgs)
    cles = list(groupes.keys())
    # facture avant newsletter dans l'ordre d'affichage
    assert cles.index(domaine.FACTURE) < cles.index(domaine.NEWSLETTER)
