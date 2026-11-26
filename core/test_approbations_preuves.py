"""Prérequis « preuve de sauvegarde » (S247) : la preuve est liée à l'utilisateur ET à l'app."""
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402

T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _demande(app="calendrier", user="perso", prerequis=("preuve_sauvegarde",), niveau="donnees"):
    return approbations.creer("livraison_reset_app", {"app": app}, "Remise à zéro", niveau,
                              prerequis=prerequis, maintenant=T0, utilisateur=user)


def test_sans_preuve_le_prerequis_est_non_satisfait():
    assert _demande()["prerequis"] == {"preuve_sauvegarde": False}


def test_preuve_deja_valide_satisfait_des_la_creation():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert _demande()["prerequis"] == {"preuve_sauvegarde": True}


def test_preuve_d_une_autre_app_ne_compte_pas():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["autre"], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert _demande()["prerequis"] == {"preuve_sauvegarde": False}


def test_preuve_d_un_autre_utilisateur_ne_compte_pas():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                    utilisateur="marie", maintenant=T0)
    assert _demande(user="perso")["prerequis"] == {"preuve_sauvegarde": False}


def test_preuve_expiree_ne_compte_pas():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 10,
                                    utilisateur="perso", maintenant=T0)
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso", T0 + 11) is False


def test_preuve_deja_expiree_a_l_enregistrement_est_ignoree():
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 - 1,
                                           utilisateur="perso", maintenant=T0) == []
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso", T0) is False


def test_echeance_plafonnee_a_24h():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 10 ** 9,
                                    utilisateur="perso", maintenant=T0)
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso",
                                      T0 + approbations.PREUVE_TTL_MAX_S - 1) is True
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso",
                                      T0 + approbations.PREUVE_TTL_MAX_S + 1) is False


def test_cle_insensible_a_la_casse_et_aux_espaces():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["  Calendrier "], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert _demande(app="CALENDRIER")["prerequis"] == {"preuve_sauvegarde": True}


def test_preuve_tardive_libere_la_demande_en_attente_et_la_renvoie():
    a = _demande()
    liberees = approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1",
                                               T0 + 3600, utilisateur="perso", maintenant=T0 + 5)
    assert liberees == [a["id"]]
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": True}


def test_preuve_tardive_ne_libere_pas_la_demande_d_un_autre_utilisateur():
    a = _demande(user="marie")
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                           utilisateur="perso", maintenant=T0 + 5) == []
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": False}


def test_demande_avec_deux_prerequis_n_est_liberee_que_quand_tous_le_sont():
    a = _demande(prerequis=("preuve_sauvegarde", "autre_preuve"))
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                           utilisateur="perso", maintenant=T0 + 5) == []
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": True,
                                                       "autre_preuve": False}


def test_bouton_toujours_refuse_tant_que_le_prerequis_manque():
    a = _demande(niveau="destructif")
    ok, raison = approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1,
                                                utilisateur="perso")
    assert (ok, raison) == (False, "prerequis")


def test_preuve_tardive_d_une_autre_app_ne_libere_pas_la_demande():
    a = _demande()
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["autre"], "P1", T0 + 3600,
                                           utilisateur="perso", maintenant=T0 + 5) == []
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": False}


# ── Revérification à l'usage (S247 revue finale I1) ──────────────────────────

def _avec_preuve(ttl, **kw):
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + ttl,
                                    utilisateur="perso", maintenant=T0)
    return _demande(**kw)


def test_preuve_expiree_entre_creation_et_bouton_refuse_et_rebaisse_le_drapeau():
    a = _avec_preuve(10)
    assert a["prerequis"] == {"preuve_sauvegarde": True}
    ok, raison = approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 11,
                                        utilisateur="perso")
    assert (ok, raison) == (False, "prerequis")
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": False}
    assert approbations.lire(a["id"])["statut"] == "en_attente"


def test_preuve_valide_au_bouton_permet_l_approbation():
    a = _avec_preuve(100)
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 5,
                                  utilisateur="perso") == (True, "ok")


def test_armement_destructif_refuse_si_preuve_expiree():
    a = _avec_preuve(10, niveau="destructif")
    assert approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 11,
                                          utilisateur="perso") == (False, "prerequis")


def test_code_saisi_refuse_si_preuve_expiree_apres_armement():
    a = _avec_preuve(100, niveau="destructif")
    assert approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 5,
                                          utilisateur="perso") == (True, "ok")
    r = approbations.valider_code_saisi("tg:42", approbations.lire(a["id"])["code"],
                                        maintenant=T0 + 101, utilisateur="perso")
    assert r["ok"] is False and r["raison"] == "prerequis"
    assert approbations.lire(a["id"])["statut"] == "en_attente"


def _approuvee(ttl):
    a = _avec_preuve(ttl)
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1,
                                  utilisateur="perso") == (True, "ok")
    return a


def test_consommer_id_refuse_si_preuve_expiree_depuis_l_approbation():
    a = _approuvee(100)
    assert approbations.consommer_id(a["id"], "livraison_reset_app", {"app": "calendrier"},
                                     "donnees", "perso", maintenant=T0 + 101) is False
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_consommer_id_accepte_si_preuve_toujours_valide():
    a = _approuvee(100)
    assert approbations.consommer_id(a["id"], "livraison_reset_app", {"app": "calendrier"},
                                     "donnees", "perso", maintenant=T0 + 50) is True


def test_consommer_refuse_si_preuve_expiree_depuis_l_approbation():
    _approuvee(100)
    assert approbations.consommer("livraison_reset_app", {"app": "calendrier"}, niveau="donnees",
                                  maintenant=T0 + 101, utilisateur="perso") is None


def test_consommer_refuse_si_drapeau_baisse():
    a = _approuvee(100)
    approbations.revoquer_preuve("preuve_sauvegarde", ["calendrier"], utilisateur="perso")
    assert approbations.consommer_id(a["id"], "livraison_reset_app", {"app": "calendrier"},
                                     "donnees", "perso", maintenant=T0 + 50) is False


def test_sans_prerequis_consommation_inchangee():
    a = approbations.creer("x", {"a": 1}, "r", "reversible", maintenant=T0, utilisateur="perso")
    approbations.approuver(a["id"], "tg:1", "telegram", maintenant=T0 + 1, utilisateur="perso")
    assert approbations.consommer_id(a["id"], "x", {"a": 1}, "reversible", "perso",
                                     maintenant=T0 + 2) is True


def test_revoquer_preuve_supprime_et_baisse_les_demandes_ouvertes_et_approuvees():
    ouverte = _avec_preuve(100)
    autre_user = _demande(user="marie")
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "PM", T0 + 100,
                                    utilisateur="marie", maintenant=T0)
    approbations.revoquer_preuve("preuve_sauvegarde", ["Calendrier"], utilisateur="perso")
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso", T0 + 1) is False
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "marie", T0 + 1) is True
    assert approbations.lire(ouverte["id"])["prerequis"] == {"preuve_sauvegarde": False}
    assert _demande(user="perso", niveau="reversible")["prerequis"] == {"preuve_sauvegarde": False}
    assert approbations.lire(autre_user["id"])["prerequis"] == {"preuve_sauvegarde": True}


def test_creer_lit_la_preuve_dans_la_meme_connexion(monkeypatch):
    """La recherche de preuve et l'INSERT partagent une transaction (pas de False périmé)."""
    appels = []
    reel = approbations._conn

    def espion():
        appels.append(1)
        return reel()
    monkeypatch.setattr(approbations, "_conn", espion)
    approbations.creer("livraison_reset_app", {"app": "calendrier"}, "r", "donnees",
                       prerequis=("preuve_sauvegarde",), maintenant=T0, utilisateur="perso")
    assert len(appels) == 2  # 1 pour creer (lecture + insert), 1 pour lire()


def test_consommer_id_sans_preuve_ne_brule_pas_l_approbation_et_reste_reutilisable_apres_reverification():
    """(a) La preuve est contrôlée AVANT la consommation : sans preuve, l'approbation reste
    `approuvee` ; une nouvelle vérification réussie la rend de nouveau consommable (jamais
    d'exécution sans preuve, jamais d'approbation brûlée pour rien)."""
    a = _approuvee(100)
    args = {"app": "calendrier"}
    assert approbations.consommer_id(a["id"], "livraison_reset_app", args, "donnees", "perso",
                                     maintenant=T0 + 101) is False
    assert approbations.lire(a["id"])["statut"] == "approuvee"
    # toujours refusé tant qu'aucune nouvelle preuve n'existe
    assert approbations.consommer_id(a["id"], "livraison_reset_app", args, "donnees", "perso",
                                     maintenant=T0 + 102) is False
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P2", T0 + 3600,
                                    utilisateur="perso", maintenant=T0 + 103)
    assert approbations.consommer_id(a["id"], "livraison_reset_app", args, "donnees", "perso",
                                     maintenant=T0 + 104) is True


def test_consommer_sans_preuve_ne_brule_pas_l_approbation():
    a = _approuvee(100)
    assert approbations.consommer("livraison_reset_app", {"app": "calendrier"}, niveau="donnees",
                                  maintenant=T0 + 101, utilisateur="perso") is None
    assert approbations.lire(a["id"])["statut"] == "approuvee"
