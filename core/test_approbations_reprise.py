"""S245b — reprise après approbation : garde en mode reprise, purge des args, anti-redemande."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402

T0 = 1_000_000.0
ARGS = {"app": "crm", "token": "SECRET-ARG"}


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _approuvee(utilisateur="alice", sens="reversible", args=None):
    d = approbations.creer("app_redemarrer", args or ARGS, "r", sens, origine="coagent",
                           maintenant=T0, utilisateur=utilisateur)
    ok, _ = approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1, utilisateur=utilisateur)
    assert ok
    return d["id"]


def test_args_de_rend_les_vrais_arguments():
    id_ = _approuvee()
    assert approbations.args_de(id_) == ARGS


def test_args_purges_quand_la_demande_est_refusee():
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")
    approbations.refuser(d["id"], "tg:1", "telegram", T0 + 1, utilisateur="alice")
    assert approbations.args_de(d["id"]) is None


def test_args_purges_quand_la_demande_expire():
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")
    approbations.expirer_perimees(maintenant=T0 + 10 ** 6)
    assert approbations.args_de(d["id"]) is None


def test_args_purges_a_la_consommation_puis_a_l_echec():
    id_ = _approuvee()
    assert approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice",
                                     T0 + 2) is True
    assert approbations.args_de(id_) is None
    approbations.conclure(id_, False, "boom")
    assert approbations.lire(id_)["statut"] == "echec"


def test_consommer_id_usage_unique():
    id_ = _approuvee()
    assert approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice", T0 + 2)
    assert not approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice",
                                         T0 + 3)


def test_consommer_id_refuse_autre_utilisateur_autre_action_ou_niveau():
    id_ = _approuvee()
    assert not approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "bob", T0 + 2)
    assert not approbations.consommer_id(id_, "app_reset", ARGS, "reversible", "alice", T0 + 2)
    assert not approbations.consommer_id(id_, "app_redemarrer", {"app": "autre"}, "reversible",
                                         "alice", T0 + 2)
    assert not approbations.consommer_id(id_, "app_redemarrer", ARGS, "destructif", "alice",
                                         T0 + 2)
    assert approbations.lire(id_)["statut"] == "approuvee"


def test_exiger_en_reprise_consomme_exactement_cet_id_sans_jamais_creer_de_demande():
    import contexte_tenant
    id_ = _approuvee()
    # `creer` dédoublonne : on clone en SQL une 2e approbation `approuvee` de même empreinte,
    # décidée AVANT la première (un `consommer` classique la prendrait en premier).
    import sqlite3
    autre = "b" * 32
    c = sqlite3.connect(approbations.DB)
    c.execute("INSERT INTO approbations SELECT ?, capacite, empreinte, resume, sensibilite, "
              "origine, statut, cree_a, expire_a, ?, decide_par, canal, resultat, prerequis, "
              "code, essais, nb_relances, relance_a, messages, utilisateur, org_id, args "
              "FROM approbations WHERE id=?", (autre, T0, id_))
    c.commit()
    c.close()
    assert approbations.lire(autre)["statut"] == "approuvee"
    # `utilisateur` du contexte = « perso » par défaut : on fixe celui du demandeur.
    jetons = contexte_tenant.definir_contexte(utilisateur="alice")
    try:
        with approbations.avec_reprise(id_):
            got, refus, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible",
                                                       "r", maintenant=T0 + 2)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert (got, refus, nouvelle) == (id_, None, None)
    assert approbations.lire(autre)["statut"] == "approuvee"


def test_exiger_en_reprise_sans_approbation_valide_refuse_sans_creer():
    import contexte_tenant
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")                    # encore en_attente
    jetons = contexte_tenant.definir_contexte(utilisateur="alice")
    try:
        with approbations.avec_reprise(d["id"]):
            got, refus, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible",
                                                       "r", maintenant=T0 + 2)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert got is None and nouvelle is None and "reprise" in refus.lower()
    assert len(approbations.en_attente()) == 1                       # aucune nouvelle demande


def test_message_d_attente_n_invite_plus_a_rappeler_l_outil():
    _, refus, _ = approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                      maintenant=T0)
    assert "AUTOMATIQUEMENT" in refus and "MÊMES arguments" not in refus


def test_action_deja_executee_recemment_n_est_pas_redemandee():
    id_ = _approuvee(utilisateur="perso")
    approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "perso", T0 + 2)
    approbations.conclure(id_, True, '{"ok": true}')
    got, refus, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                               maintenant=T0 + 60)
    assert got is None and nouvelle is None and "déjà d'être exécutée" in refus
    # Passé le délai, une nouvelle demande est de nouveau possible.
    _, _, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                         maintenant=T0 + 2 + approbations.DELAI_APRES_EXECUTION_S + 1)
    assert nouvelle is not None


def test_a_reprendre_liste_les_approuvees_orphelines():
    id_ = _approuvee()                                   # décidée à T0+1
    assert approbations.a_reprendre(maintenant=T0 + 30, delai_s=60) == []      # trop récente
    assert approbations.a_reprendre(maintenant=T0 + 100, delai_s=60) == [id_]
    approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice", T0 + 101)
    assert approbations.a_reprendre(maintenant=T0 + 200, delai_s=60) == []


def test_args_reellement_ecrits_en_colonne_apres_creer():
    import sqlite3
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")
    c = sqlite3.connect(approbations.DB)
    brut = c.execute("SELECT args FROM approbations WHERE id=?", (d["id"],)).fetchone()[0]
    c.close()
    import json
    assert json.loads(brut) == ARGS
    assert "args" not in d and "SECRET-ARG" not in str(d)       # jamais exposés par la vue

