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
