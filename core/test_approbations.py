"""Machine à états des approbations (S245) : transitions, expiration, journal, persistance."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402

T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "approbations.db"))
    approbations.init_db()


def _demande(sens="reversible", **kw):
    return approbations.creer("app_redemarrer", {"app": "crm"}, "Redémarrer crm", sens,
                              origine="incident", maintenant=T0, **kw)


def test_creation_est_en_attente_avec_ttl_par_niveau():
    for niveau, minutes in (("reversible", 30), ("donnees", 120), ("destructif", 15)):
        a = approbations.creer(f"cap_{niveau}", {}, "r", niveau, maintenant=T0)
        assert a["statut"] == "en_attente"
        assert a["expire_a"] == T0 + minutes * 60
        assert len(a["id"]) == 32


def test_ttl_surchargeable_par_env(monkeypatch):
    monkeypatch.setenv("APPROBATION_TTL_DESTRUCTIF_MIN", "5")
    assert approbations.ttl_secondes("destructif") == 300


def test_niveau_lecture_ou_inconnu_refuse():
    for niveau in ("lecture", "nimporte"):
        with pytest.raises(ValueError):
            approbations.creer("x", {}, "r", niveau, maintenant=T0)


def test_code_seulement_pour_destructif():
    assert _demande("reversible")["code"] is None
    code = _demande("destructif")["code"]
    assert code is not None and len(code) == 6 and code.isdigit()


def test_creer_est_idempotent_sur_la_meme_action():
    a, b = _demande(), _demande()
    assert a["id"] == b["id"]


def test_approuver_reversible():
    a = _demande()
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 10, utilisateur="perso") == (True, "ok")
    lue = approbations.lire(a["id"])
    assert lue["statut"] == "approuvee" and lue["decide_par"] == "tg:42"


def test_double_approbation_refusee():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 2, utilisateur="perso") == (False, "deja_decidee")


def test_approuver_apres_expiration_marque_expiree():
    a = _demande()
    ok, raison = approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 31 * 60, utilisateur="perso")
    assert (ok, raison) == (False, "expiree")
    assert approbations.lire(a["id"])["statut"] == "expiree"


def test_destructif_ne_s_approuve_pas_par_bouton_seul():
    a = _demande("destructif")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso") == (False, "code_requis")
    assert approbations.lire(a["id"])["statut"] == "en_attente"


def test_id_inconnu():
    assert approbations.approuver("0" * 32, "tg:42", "telegram", utilisateur="perso") == (False, "introuvable")
    assert approbations.refuser("0" * 32, "tg:42", "telegram", utilisateur="perso") == (False, "introuvable")


def test_refuser_puis_plus_d_approbation():
    a = _demande()
    assert approbations.refuser(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso") == (True, "ok")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 2, utilisateur="perso") == (False, "deja_decidee")


def test_journal_append_only_trace_chaque_transition():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso")
    assert [e["evenement"] for e in approbations.journal(a["id"])] == ["creee", "approuvee"]
    with sqlite3.connect(approbations.DB) as c:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute("UPDATE approbations_journal SET evenement='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute("DELETE FROM approbations_journal")


def test_persistance_apres_redemarrage():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso")
    approbations.init_db()  # « redémarrage » : la base reste, init_db est idempotent
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_prerequis_bloquent_l_approbation():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee",))
    assert a["prerequis"] == {"sauvegarde_verifiee": False}
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso") == (False, "prerequis")


import threading


# ── Code à 6 chiffres (destructif) ───────────────────────────────────────────

def test_code_bon_approuve_un_destructif():
    a = _demande("destructif")
    assert approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso") == (True, "ok")
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2, utilisateur="perso")
    assert r["ok"] is True and r["approbation_id"] == a["id"]
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_pas_de_saisie_armee_le_message_n_est_pas_un_code():
    _demande("destructif")
    assert approbations.valider_code_saisi("tg:42", "123456", utilisateur="perso") is None


def test_trois_codes_faux_refusent_la_demande():
    a = _demande("destructif")
    faux = "000000" if a["code"] != "000000" else "111111"
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    r1 = approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 2, utilisateur="perso")
    r2 = approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 3, utilisateur="perso")
    assert (r1["raison"], r1["restants"]) == ("code_faux", 2)
    assert (r2["raison"], r2["restants"]) == ("code_faux", 1)
    r3 = approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 4, utilisateur="perso")
    assert r3["raison"] == "essais_epuises"
    assert approbations.lire(a["id"])["statut"] == "refusee"
    # la saisie est désarmée : un 4e message repart au LLM
    assert approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 5, utilisateur="perso") is None


def test_le_bon_code_apres_refus_n_approuve_rien():
    a = _demande("destructif")
    faux = "000000" if a["code"] != "000000" else "111111"
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    for i in range(3):
        approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 2 + i, utilisateur="perso")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 9, utilisateur="perso")  # doit échouer
    assert approbations.lire(a["id"])["statut"] == "refusee"


def test_armer_refuse_hors_destructif_ou_expire():
    assert approbations.armer_saisie_code(_demande("reversible")["id"], "tg:42", utilisateur="perso") == (False, "pas_destructif")
    d = _demande("destructif")
    assert approbations.armer_saisie_code(d["id"], "tg:42", maintenant=T0 + 16 * 60, utilisateur="perso") == (False, "expiree")


def test_saisie_armee_expire_au_bout_de_5_minutes():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    assert approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 1 + 301, utilisateur="perso") is None


def test_la_saisie_d_un_autre_approbateur_ne_compte_pas():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    assert approbations.valider_code_saisi("tg:99", a["code"], maintenant=T0 + 2, utilisateur="perso") is None


# ── Consommation atomique ────────────────────────────────────────────────────

def _approuvee(**kw):
    a = _demande(**kw)
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso")
    return a


def test_consommer_une_seule_fois():
    a = _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2) == a["id"]
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 3) is None
    assert approbations.lire(a["id"])["statut"] == "executee"


def test_consommer_exige_la_meme_empreinte():
    _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "autre"}, maintenant=T0 + 2) is None
    assert approbations.consommer("autre_cap", {"app": "crm"}, maintenant=T0 + 2) is None


def test_consommer_ignore_confirme():
    _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm", "confirme": True}, maintenant=T0 + 2)


def test_consommer_sans_approbation_ou_en_attente_ou_refusee():
    assert approbations.consommer("app_redemarrer", {"app": "crm"}) is None
    _demande()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 1) is None


def test_consommer_apres_la_fenetre_d_execution():
    _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 1 + 301 + 30 * 60) is None


def test_consommation_concurrente_une_seule_gagne():
    _approuvee()
    gagnants = []

    def tenter():
        r = approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2)
        if r:
            gagnants.append(r)

    fils = [threading.Thread(target=tenter) for _ in range(12)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert len(gagnants) == 1


def test_conclure_echec_passe_executee_a_echec():
    a = _approuvee()
    approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2)
    approbations.conclure(a["id"], False, "Erreur (crm) : boom")
    lue = approbations.lire(a["id"])
    assert lue["statut"] == "echec" and "boom" in lue["resultat"]


def test_conclure_succes_garde_executee_et_note_le_resultat():
    a = _approuvee()
    approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2)
    approbations.conclure(a["id"], True, "ok")
    assert approbations.lire(a["id"])["statut"] == "executee"


# ── Niveau de sensibilité dans la consommation (déviation de sécurité) ───────

def test_consommer_destructif_ne_prend_pas_une_approbation_reversible():
    a = _approuvee()  # reversible, approuvée par bouton
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, niveau="destructif",
                                  maintenant=T0 + 2) is None
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_consommer_avec_niveau_correspondant_consomme():
    a = _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, niveau="reversible",
                                  maintenant=T0 + 2) == a["id"]


def test_consommer_destructif_approuve_par_code_se_consomme_avec_son_niveau():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2, utilisateur="perso")
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, niveau="destructif",
                                  maintenant=T0 + 3) == a["id"]


# ── Prérequis ────────────────────────────────────────────────────────────────

def test_prerequis_satisfaits_debloquent_l_approbation():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee", "restauration_testee"))
    assert approbations.satisfaire_prerequis(a["id"], "sauvegarde_verifiee") is False
    assert approbations.satisfaire_prerequis(a["id"], "restauration_testee") is True
    for nom in ("sauvegarde_verifiee", "restauration_testee"):   # drapeaux revérifiés à l'usage
        approbations.enregistrer_preuve(nom, ["crm"], "P1", T0 + 3600, utilisateur="perso",
                                        maintenant=T0)
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1, utilisateur="perso") == (True, "ok")


def test_prerequis_inconnu_ignore():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee",))
    assert approbations.satisfaire_prerequis(a["id"], "inconnu") is False


# ── Expiration et relance ────────────────────────────────────────────────────

def test_expirer_perimees():
    vieille = _demande()
    ok = approbations.creer("autre", {}, "r", "donnees", maintenant=T0)
    assert approbations.expirer_perimees(maintenant=T0 + 31 * 60) == [vieille["id"]]
    assert approbations.lire(vieille["id"])["statut"] == "expiree"
    assert approbations.lire(ok["id"])["statut"] == "en_attente"
    assert approbations.expirer_perimees(maintenant=T0 + 31 * 60) == []  # idempotent


def test_une_approbation_non_utilisee_finit_expiree():
    a = _approuvee()
    assert a["id"] in approbations.expirer_perimees(maintenant=T0 + 3600)
    assert approbations.lire(a["id"])["statut"] == "expiree"


def test_a_relancer_respecte_delai_et_plafond():
    a = _demande()
    assert approbations.a_relancer(600, 3, maintenant=T0 + 300) == []
    assert [x["id"] for x in approbations.a_relancer(600, 3, maintenant=T0 + 601)] == [a["id"]]
    approbations.marquer_relancee(a["id"], maintenant=T0 + 601)
    assert approbations.a_relancer(600, 3, maintenant=T0 + 700) == []
    assert [x["id"] for x in approbations.a_relancer(600, 3, maintenant=T0 + 1300)] == [a["id"]]
    for i in range(3):
        approbations.marquer_relancee(a["id"], maintenant=T0 + 1300 + i)
    assert approbations.a_relancer(600, 3, maintenant=T0 + 5000) == []  # plafond atteint


def test_en_attente_et_messages():
    a = _demande()
    approbations.enregistrer_messages(a["id"], [{"chat_id": "42", "message_id": 7}])
    assert approbations.lire(a["id"])["messages"] == [{"chat_id": "42", "message_id": 7}]
    assert [x["id"] for x in approbations.en_attente()] == [a["id"]]


# ── Saisie du code : robustesse (revue) ──────────────────────────────────────

def _faux(a):
    return "000000" if a["code"] != "000000" else "111111"


def test_saisie_non_ascii_ou_mal_formee_compte_comme_essai_sans_crash():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    r1 = approbations.valider_code_saisi("tg:42", "é12345", maintenant=T0 + 2, utilisateur="perso")
    r2 = approbations.valider_code_saisi("tg:42", "12345", maintenant=T0 + 3, utilisateur="perso")
    assert (r1["raison"], r1["restants"]) == ("code_faux", 2)
    assert (r2["raison"], r2["restants"]) == ("code_faux", 1)
    r3 = approbations.valider_code_saisi("tg:42", "١٢٣٤٥٦", maintenant=T0 + 4, utilisateur="perso")  # chiffres arabes
    assert r3["raison"] == "essais_epuises"
    assert approbations.lire(a["id"])["statut"] == "refusee"
    ev = [e["evenement"] for e in approbations.journal(a["id"])]
    assert ev.count("code_faux") == 3


def test_essais_concurrents_ne_depassent_pas_la_limite():
    a = _demande("destructif")
    faux = _faux(a)
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    res, barre = [], threading.Barrier(8)

    def go():
        barre.wait()
        res.append(approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 2, utilisateur="perso"))

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not any(r and r["ok"] for r in res)
    assert approbations.lire(a["id"])["statut"] == "refusee"
    with approbations._conn() as c:
        assert c.execute("SELECT essais FROM approbations WHERE id=?", (a["id"],)).fetchone()[0] == 3
    ev = [e["evenement"] for e in approbations.journal(a["id"])]
    assert ev.count("code_faux") == 3


def test_course_a_l_approbation_ne_journalise_pas_approuvee(monkeypatch):
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    monkeypatch.setattr(approbations, "_transition", lambda *a_, **k: False)
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2, utilisateur="perso")
    assert r["ok"] is False and r["raison"] == "deja_decidee"
    assert "approuvee" not in [e["evenement"] for e in approbations.journal(a["id"])]


def test_bon_code_apres_expiration_de_la_demande_n_approuve_pas():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    # saisie encore armée (5 min) mais demande expirée : on force l'expiration de la demande
    with approbations._conn() as c:
        c.execute("UPDATE approbations SET expire_a=? WHERE id=?", (T0 + 2, a["id"]))
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 3, utilisateur="perso")
    assert r["ok"] is False and r["raison"] == "expiree"
    assert approbations.lire(a["id"])["statut"] == "expiree"


def test_bon_code_apres_decision_par_un_autre_canal_n_approuve_pas():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    assert approbations.refuser(a["id"], "tg:99", "telegram", maintenant=T0 + 2, utilisateur="perso")
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 3, utilisateur="perso")
    assert r["ok"] is False and r["raison"] == "deja_decidee"
    assert approbations.lire(a["id"])["statut"] == "refusee"


# ── Revue finale S245 : prérequis imposés au code destructif ─────────────────

def test_armer_refuse_si_prerequis_non_reunis():
    a = _demande("destructif", prerequis=("sauvegarde_verifiee",))
    assert approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso") == (False, "prerequis")
    assert approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2, utilisateur="perso") is None
    assert approbations.lire(a["id"])["statut"] == "en_attente"


def test_code_soumis_prerequis_non_reunis_n_approuve_jamais():
    a = _demande("destructif", prerequis=("sauvegarde_verifiee",))
    with approbations._conn() as c:   # saisie armée « de force » (état incohérent)
        c.execute("INSERT INTO saisie_code (approbateur, approbation_id, expire_a) VALUES (?,?,?)",
                  ("tg:42", a["id"], T0 + 999))
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2, utilisateur="perso")
    assert r["ok"] is False and r["raison"] == "prerequis"
    lue = approbations.lire(a["id"])
    assert lue["statut"] == "en_attente" and lue["essais"] == 0     # pas un essai raté
    assert approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 3, utilisateur="perso") is None  # désarmée


def test_destructif_prerequis_satisfaits_puis_code_approuve():
    a = _demande("destructif", prerequis=("sauvegarde_verifiee",))
    # Le drapeau seul ne suffit plus (revérifié à l'usage) : une vraie preuve doit exister.
    approbations.enregistrer_preuve("sauvegarde_verifiee", ["crm"], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso") == (True, "ok")
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2, utilisateur="perso")
    assert r["ok"] is True and approbations.lire(a["id"])["statut"] == "approuvee"


@pytest.mark.parametrize("valeur", ["abc", "0", "-5", ""])
def test_ttl_invalide_retombe_sur_le_defaut(monkeypatch, caplog, valeur):
    monkeypatch.setenv("APPROBATION_TTL_DESTRUCTIF_MIN", valeur)
    with caplog.at_level("WARNING"):
        assert approbations.ttl_secondes("destructif") == 15 * 60
    assert "APPROBATION_TTL_DESTRUCTIF_MIN" in caplog.text


def test_origine_contextvar_set_reset():
    assert approbations.ORIGINE.get() == "inconnue"
    with approbations.avec_origine("mcp"):
        assert approbations.creer("c1", {}, "r", "reversible", maintenant=T0)["origine"] == "mcp"
    assert approbations.ORIGINE.get() == "inconnue"
    with pytest.raises(RuntimeError):
        with approbations.avec_origine("coagent"):
            raise RuntimeError
    assert approbations.ORIGINE.get() == "inconnue"
