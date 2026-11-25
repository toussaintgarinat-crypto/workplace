"""S245b — reprise après approbation : garde en mode reprise, purge des args, anti-redemande."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402
import approbations_canal  # noqa: E402
import approbations_reprise  # noqa: E402
import contexte_tenant  # noqa: E402
import outils  # noqa: E402

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



# ── Task 6 : reprise (exécution par le Cœur) ────────────────────────────────

class _Reg:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _Reg({"dokploy": {"nom": "dokploy", "port": 6300, "capacites": [
    {"nom": "app_redemarrer", "chemin": "/redemarrer", "methode": "POST", "action": True,
     "sensibilite": "reversible", "description": "Redémarre une app.",
     "params": {"app": {"type": "string", "requis": True}}}]}})


@pytest.fixture
def faux_outils(monkeypatch):
    vu = {"appels": [], "contexte": [], "maj": [], "notifs": []}

    async def _executer(nom, args, registre):
        ctx = contexte_tenant.contexte_actuel()
        vu["appels"].append((nom, dict(args)))
        vu["contexte"].append((ctx.utilisateur, ctx.org_id, approbations.ORIGINE.get()))
        return '{"ok": true}'

    async def _maj(registre, demande):
        vu["maj"].append(demande["statut"])

    async def _notifier(registre, demande):
        vu["notifs"].append(demande["id"])

    monkeypatch.setattr(outils, "_executer", _executer)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", _maj)
    monkeypatch.setattr(outils, "_notifier_approbation", _notifier)
    return vu


def _demande_approuvee(utilisateur="alice", org="org-1"):
    d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                           origine="incident", utilisateur=utilisateur, org_id=org)
    ok, _ = approbations.approuver(d["id"], "tg:1", "telegram", utilisateur=utilisateur)
    assert ok
    return d["id"]


def test_reprendre_execute_dans_le_contexte_du_demandeur(faux_outils):
    id_ = _demande_approuvee()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "executee"
    assert faux_outils["appels"] == [("app_redemarrer", {"app": "crm", "confirme": True})]
    assert faux_outils["contexte"] == [("alice", "org-1", "incident")]
    assert approbations.lire(id_)["statut"] == "executee"
    assert faux_outils["maj"] == ["executee"]          # message Telegram édité à l'état final
    assert faux_outils["notifs"] == []                 # AUCUNE nouvelle demande


def test_reprendre_ne_fuit_pas_le_contexte(faux_outils):
    id_ = _demande_approuvee()

    async def scenario():
        # Les assertions DOIVENT s'exécuter dans la même coroutine (contexte non copié).
        contexte_tenant.definir_contexte(utilisateur="avant")
        origine_avant = approbations.ORIGINE.get()
        await approbations_reprise.reprendre(REGISTRE, id_)
        assert contexte_tenant.contexte_actuel().utilisateur == "avant"
        assert approbations.REPRISE.get() is None
        assert approbations.ORIGINE.get() == origine_avant

    asyncio.run(scenario())


def test_reprendre_deux_fois_n_execute_qu_une_fois(faux_outils):
    id_ = _demande_approuvee()

    async def deux():
        return await asyncio.gather(approbations_reprise.reprendre(REGISTRE, id_),
                                    approbations_reprise.reprendre(REGISTRE, id_))

    asyncio.run(deux())
    assert len(faux_outils["appels"]) == 1


def test_reprendre_ignore_une_demande_non_approuvee(faux_outils):
    d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                           utilisateur="alice")
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, d["id"])) == "ignoree"
    assert faux_outils["appels"] == []


def test_reprendre_sans_args_ne_fait_rien(faux_outils):
    id_ = _demande_approuvee()
    import sqlite3
    c = sqlite3.connect(approbations.DB)
    c.execute("UPDATE approbations SET args=NULL WHERE id=?", (id_,))
    c.commit()
    c.close()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "sans_args"
    assert faux_outils["appels"] == []


def test_echec_d_execution_passe_en_echec(monkeypatch, faux_outils):
    async def _boom(nom, args, registre):
        return '{"erreur": "dokploy injoignable"}'

    monkeypatch.setattr(outils, "_executer", _boom)
    id_ = _demande_approuvee()
    asyncio.run(approbations_reprise.reprendre(REGISTRE, id_))
    assert approbations.lire(id_)["statut"] == "echec"
    assert faux_outils["maj"] == ["echec"]


def test_exception_dans_l_outil_ne_remonte_pas(monkeypatch, faux_outils):
    async def _crash(nom, args, registre):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(outils, "_executer", _crash)
    id_ = _demande_approuvee()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "echec"
    assert approbations.lire(id_)["statut"] == "echec"


def test_exception_avant_consommation_est_journalisee_et_reste_reprenable(
        monkeypatch, faux_outils, caplog):
    def _casse(*a, **k):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(approbations, "exiger", _casse)
    id_ = _demande_approuvee()
    with caplog.at_level("WARNING"):
        assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "echec"
    assert approbations.lire(id_)["statut"] == "approuvee"       # pas consommée : l'horloge réessaiera
    assert "non consommée" in caplog.text and "SECRET" not in caplog.text


def test_garde_qui_refuse_abandonne_la_demande(monkeypatch, faux_outils):
    # exiger refuse (empreinte différente) sans lever : rien n'est exécuté, on ne ment pas,
    # et la demande est abandonnée pour que l'horloge ne la rejoue pas indéfiniment.
    monkeypatch.setattr(approbations, "exiger",
                        lambda *a, **k: (None, "refus", None))
    id_ = _demande_approuvee()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "non_consommee"
    assert faux_outils["appels"] == []
    assert approbations.lire(id_)["statut"] == "expiree"
    assert approbations.args_de(id_) is None
    assert "abandonnee" in [e["evenement"] for e in approbations.journal(id_)]


def test_capacite_plus_sensible_n_est_pas_executee_et_est_abandonnee(monkeypatch, faux_outils):
    monkeypatch.setattr(outils, "est_sensible", lambda nom, registre: None)
    id_ = _demande_approuvee()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "ignoree"
    assert faux_outils["appels"] == []
    assert approbations.lire(id_)["statut"] == "expiree"
    assert approbations.args_de(id_) is None
    evts = [e for e in approbations.journal(id_) if e["evenement"] == "abandonnee"]
    assert evts and "plus sensible" in evts[0]["detail"]
    assert approbations.a_reprendre(maintenant=10 ** 10, delai_s=0) == []


def test_sensibilite_changee_n_est_pas_executee(monkeypatch, faux_outils):
    monkeypatch.setattr(outils, "est_sensible", lambda nom, registre: "destructif")
    id_ = _demande_approuvee()          # approuvée en « reversible »
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "ignoree"
    assert faux_outils["appels"] == []
    assert approbations.lire(id_)["statut"] == "expiree"


def test_abandonner_seulement_depuis_approuvee():
    id_ = _approuvee()
    assert approbations.abandonner(id_, "raison " + "x" * 300, maintenant=T0 + 5) is True
    assert approbations.lire(id_)["statut"] == "expiree"
    assert approbations.args_de(id_) is None
    evt = [e for e in approbations.journal(id_) if e["evenement"] == "abandonnee"]
    assert len(evt) == 1 and len(evt[0]["detail"]) == 200
    assert approbations.abandonner(id_, "encore") is False        # déjà finale


def test_abandonner_sans_effet_sur_les_autres_etats():
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")
    assert approbations.abandonner(d["id"], "x") is False          # en_attente
    assert approbations.lire(d["id"])["statut"] == "en_attente"
    assert approbations.abandonner("inexistant", "x") is False
    id_ = _approuvee()
    approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice", T0 + 2)
    assert approbations.abandonner(id_, "x") is False              # executee
    assert approbations.lire(id_)["statut"] == "executee"
    assert not [e for e in approbations.journal(id_) if e["evenement"] == "abandonnee"]


def test_lancer_planifie_la_reprise_en_tache_de_fond(faux_outils):
    id_ = _demande_approuvee()

    async def scenario():
        approbations_reprise.lancer(REGISTRE, id_)
        assert approbations_reprise._TACHES
        while approbations_reprise._TACHES:
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert len(faux_outils["appels"]) == 1
