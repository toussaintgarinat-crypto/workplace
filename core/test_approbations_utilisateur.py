"""S245b — l'approbation est liée à l'utilisateur qui l'a demandée (limite n°1 d'S245)."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402
import contexte_tenant  # noqa: E402

T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _demande(utilisateur, sens="reversible", args=None):
    return approbations.creer("app_redemarrer", args or {"app": "crm"}, "Redémarrer crm", sens,
                              origine="conversation", maintenant=T0, utilisateur=utilisateur)


def test_utilisateur_par_defaut_vient_du_contexte_tenant():
    jetons = contexte_tenant.definir_contexte(utilisateur="carol", org_id="org-9")
    try:
        d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                               maintenant=T0)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert d["utilisateur"] == "carol" and d["org_id"] == "org-9"


def test_sans_contexte_l_utilisateur_est_perso():
    d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible", maintenant=T0)
    assert d["utilisateur"] == "perso"


def test_args_jamais_exposes_par_la_vue():
    d = _demande("alice", args={"app": "crm", "token": "SECRET"})
    assert "args" not in d
    assert all("args" not in x for x in approbations.en_attente())
    assert "SECRET" not in str(approbations.lire(d["id"]))


def test_deux_utilisateurs_ont_chacun_leur_demande_pour_la_meme_action():
    a, b = _demande("alice"), _demande("bob")
    assert a["id"] != b["id"]


def test_meme_utilisateur_meme_action_ne_double_pas():
    assert _demande("alice")["id"] == _demande("alice")["id"]


def test_un_autre_utilisateur_ne_peut_pas_approuver():
    d = _demande("alice")
    ok, raison = approbations.approuver(d["id"], "tg:2", "telegram", T0 + 1, utilisateur="bob")
    assert (ok, raison) == (False, "introuvable")
    assert approbations.lire(d["id"])["statut"] == "en_attente"
    assert "refus_autre_utilisateur" in [j["evenement"] for j in approbations.journal(d["id"])]


def test_un_autre_utilisateur_ne_peut_pas_refuser():
    d = _demande("alice")
    assert approbations.refuser(d["id"], "tg:2", "telegram", T0 + 1,
                                utilisateur="bob") == (False, "introuvable")
    assert approbations.lire(d["id"])["statut"] == "en_attente"


def test_le_demandeur_approuve():
    d = _demande("alice")
    assert approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1,
                                  utilisateur="alice") == (True, "ok")


def test_bob_ne_consomme_pas_l_approbation_d_alice():
    d = _demande("alice")
    approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1, utilisateur="alice")
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, "reversible", T0 + 2,
                                  utilisateur="bob") is None
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, "reversible", T0 + 2,
                                  utilisateur="alice") == d["id"]


def test_exiger_isole_les_utilisateurs():
    """Alice a une approbation valide : Bob, lui, déclenche SA propre demande."""
    d = _demande("alice")
    approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1, utilisateur="alice")
    jetons = contexte_tenant.definir_contexte(utilisateur="bob")
    try:
        id_, refus, nouvelle = approbations.exiger("app_redemarrer", {"app": "crm"},
                                                   "reversible", "r", maintenant=T0 + 2)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert id_ is None and nouvelle is not None and nouvelle["utilisateur"] == "bob"
    assert approbations.lire(d["id"])["statut"] == "approuvee"      # celle d'Alice intacte


def test_en_attente_filtre_par_utilisateur():
    a, b = _demande("alice"), _demande("bob")
    assert [x["id"] for x in approbations.en_attente(utilisateur="alice")] == [a["id"]]
    assert {x["id"] for x in approbations.en_attente()} == {a["id"], b["id"]}


def test_code_destructif_autre_utilisateur_ne_peut_pas_armer():
    d = _demande("alice", sens="destructif")
    assert approbations.armer_saisie_code(d["id"], "tg:2", T0 + 1,
                                          utilisateur="bob") == (False, "introuvable")


def test_valider_code_autre_utilisateur_est_ignore():
    d = _demande("alice", sens="destructif")
    approbations.armer_saisie_code(d["id"], "tg:1", T0 + 1, utilisateur="alice")
    code = approbations.lire(d["id"])["code"]
    # Même `par`, mais présenté comme un autre utilisateur : traité comme « pas de saisie ».
    assert approbations.valider_code_saisi("tg:1", code, T0 + 2, utilisateur="bob") is None
    assert approbations.lire(d["id"])["statut"] == "en_attente"


def test_migration_d_une_base_s245_existante(tmp_path, monkeypatch):
    """Une base déjà déployée (sans les nouvelles colonnes) est migrée sans perte."""
    chemin = str(tmp_path / "ancienne.db")
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE approbations (
        id TEXT PRIMARY KEY, capacite TEXT NOT NULL, empreinte TEXT NOT NULL,
        resume TEXT NOT NULL, sensibilite TEXT NOT NULL, origine TEXT NOT NULL,
        statut TEXT NOT NULL, cree_a REAL NOT NULL, expire_a REAL NOT NULL, decide_a REAL,
        decide_par TEXT, canal TEXT, resultat TEXT, prerequis TEXT NOT NULL DEFAULT '{}',
        code TEXT, essais INTEGER NOT NULL DEFAULT 0, nb_relances INTEGER NOT NULL DEFAULT 0,
        relance_a REAL, messages TEXT NOT NULL DEFAULT '[]')""")
    c.execute("INSERT INTO approbations (id, capacite, empreinte, resume, sensibilite, origine, "
              "statut, cree_a, expire_a) VALUES ('a','cap','e','r','reversible','chat',"
              "'en_attente',1,2)")
    c.commit()
    c.close()
    monkeypatch.setattr(approbations, "DB", chemin)
    approbations.init_db()
    approbations.init_db()                      # idempotent
    ligne = approbations.lire("a")
    assert ligne["utilisateur"] == "perso" and "args" not in ligne
