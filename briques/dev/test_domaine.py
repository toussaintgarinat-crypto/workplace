"""Domaine pur : machine à états, nommage de branche, garde-fous. Aucun I/O."""
import domaine
import pytest


def test_slug_reduit_et_borne():
    assert domaine.slug("Ajouter un filtre par Entreprise !") == "ajouter-un-filtre-par-entreprise"
    assert domaine.slug("") == "chantier"
    assert len(domaine.slug("x" * 200)) <= 48


def test_nom_branche_prefixe_dev_jamais_main():
    b = domaine.nom_branche("mail", "ajouter un champ")
    assert b.startswith("dev/")
    assert not domaine.branche_protegee(b)


def test_branche_protegee():
    assert domaine.branche_protegee("main")
    assert domaine.branche_protegee("MASTER")
    assert domaine.branche_protegee(" prod ")
    assert not domaine.branche_protegee("dev/feature")


def test_transitions_valides():
    assert domaine.transition_autorisee(domaine.CREE, domaine.EN_COURS)
    assert domaine.transition_autorisee(domaine.EN_COURS, domaine.REVUE)
    assert domaine.transition_autorisee(domaine.REVUE, domaine.FUSIONNE)
    assert domaine.transition_autorisee(domaine.CREE, domaine.JETE)


def test_transitions_interdites():
    assert not domaine.transition_autorisee(domaine.CREE, domaine.FUSIONNE)   # pas de fusion sans revue
    assert not domaine.transition_autorisee(domaine.FUSIONNE, domaine.EN_COURS)  # terminal
    assert not domaine.transition_autorisee(domaine.JETE, domaine.EN_COURS)      # terminal


def test_exiger_transition_leve():
    with pytest.raises(domaine.TransitionInvalide):
        domaine.exiger_transition(domaine.CREE, domaine.FUSIONNE)


def test_transition_cree_planifie_en_cours():
    # Flux BMAD (S88) : cree → planifie → en_cours, replanification autorisée.
    assert domaine.transition_autorisee(domaine.CREE, domaine.PLANIFIE)
    assert domaine.transition_autorisee(domaine.PLANIFIE, domaine.EN_COURS)
    assert domaine.transition_autorisee(domaine.PLANIFIE, domaine.PLANIFIE)  # replanifier
    assert not domaine.transition_autorisee(domaine.PLANIFIE, domaine.REVUE)  # pas de saut


def test_verrou_de_plan_bmad():
    ch = domaine.Chantier(id="x", intention="t", brique_cible="mail",
                          branche="dev/mail-t", plan_requis=True)
    # Plan requis mais pas validé → codage VERROUILLÉ.
    assert ch.peut_planifier and ch.code_verrouille_par_plan and not ch.peut_lancer
    ch.avancer(domaine.PLANIFIE)
    ch.plan = {"texte": "## Mini-PRD\n..."}
    ch.plan_valide = True
    # Plan validé → verrou levé, on peut coder.
    assert not ch.code_verrouille_par_plan and ch.peut_lancer
    ch.avancer(domaine.EN_COURS)


def test_sans_plan_requis_pas_de_verrou():
    ch = domaine.Chantier(id="y", intention="t", brique_cible="mail", branche="dev/mail-y")
    assert not ch.code_verrouille_par_plan and ch.peut_lancer  # rétrocompat flux direct


def test_chantier_avancer_et_drapeaux():
    ch = domaine.Chantier(id="x", intention="t", brique_cible="mail",
                          branche="dev/mail-t")
    assert ch.statut == domaine.CREE and ch.peut_lancer and not ch.peut_fusionner
    ch.avancer(domaine.EN_COURS)
    ch.avancer(domaine.REVUE)
    assert ch.peut_fusionner
    ch.avancer(domaine.FUSIONNE)
    assert not ch.peut_lancer
    with pytest.raises(domaine.TransitionInvalide):
        ch.avancer(domaine.EN_COURS)
