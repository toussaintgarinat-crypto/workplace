"""Preuve « par cible » (S248 3b) : liée à l'utilisateur de l'approbation, à l'app ET à l'utilisateur visé."""
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402

T0 = 1_000_000.0
PV = "paquet_verifie"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _demande(cible, app="studio", user="perso"):
    return approbations.creer("livraison_donnees_reinitialiser", {"app": app, "utilisateur": cible},
                              "Remise à zéro", "donnees", prerequis=(PV,), maintenant=T0,
                              utilisateur=user)


def _preuve(cible, app="studio", user="perso", pid="P1", expire=T0 + 3600):
    args = {"app": app, "utilisateur": cible}
    k = approbations.cle_preuve(PV, args)
    return approbations.enregistrer_preuve(PV, [k], pid, expire, utilisateur=user,
                                           maintenant=T0, app_id=k)


def test_cle_par_cible_ne_contient_pas_l_identite_en_clair():
    k = approbations.cle_preuve(PV, {"app": "Studio", "utilisateur": "claire"})
    assert k.startswith("studio|") and "claire" not in k and len(k) == len("studio|") + 16


def test_cle_inchangee_pour_les_preuves_par_app():
    assert approbations.cle_preuve("preuve_sauvegarde", {"app": "Calendrier", "utilisateur": "x"}) == "Calendrier"


@pytest.mark.parametrize("args", [None, {}, {"app": "studio"}, {"utilisateur": "c"},
                                  {"app": "", "utilisateur": "c"}, {"app": "studio", "utilisateur": "  "},
                                  {"app": "studio", "utilisateur": 5}, {"app": 3, "utilisateur": "c"}])
def test_args_incomplets_donnent_aucune_cle(args):
    assert approbations.cle_preuve(PV, args) is None


def test_sans_preuve_non_satisfait():
    assert _demande("claire")["prerequis"] == {PV: False}


def test_preuve_de_claire_satisfait_claire():
    _preuve("claire")
    assert _demande("claire")["prerequis"] == {PV: True}


def test_preuve_de_claire_ne_satisfait_pas_paul():
    _preuve("claire")
    assert _demande("paul")["prerequis"] == {PV: False}


def test_preuve_de_claire_ne_satisfait_pas_une_autre_app():
    _preuve("claire")
    assert _demande("claire", app="calendrier")["prerequis"] == {PV: False}


def test_preuve_par_app_ne_vaut_pas_preuve_par_cible():
    approbations.enregistrer_preuve(PV, ["studio"], "P0", T0 + 3600, utilisateur="perso", maintenant=T0)
    assert _demande("claire")["prerequis"] == {PV: False}


def test_preuve_enregistree_apres_la_demande_libere_seulement_la_bonne_cible():
    d_claire, d_paul = _demande("claire"), _demande("paul")
    liberees = _preuve("claire")
    assert liberees == [d_claire["id"]]
    assert approbations.lire(d_paul["id"])["prerequis"] == {PV: False}


def test_revocation_ne_touche_que_la_cible():
    _preuve("claire")
    _preuve("paul", pid="P2")
    d_c, d_p = _demande("claire"), _demande("paul")
    k = approbations.cle_preuve(PV, {"app": "studio", "utilisateur": "claire"})
    assert approbations.revoquer_preuve(PV, [k], utilisateur="perso", app_id=k) == [d_c["id"]]
    assert approbations.lire(d_p["id"])["prerequis"] == {PV: True}


def test_preuve_d_un_autre_utilisateur_d_approbation_ne_compte_pas():
    _preuve("claire", user="autre-admin")
    assert _demande("claire", user="perso")["prerequis"] == {PV: False}


def test_preuve_expiree_perdue_a_l_usage():
    _preuve("claire", expire=T0 + 50)
    d = _demande("claire")
    assert approbations.consommer_id(d["id"], "livraison_donnees_reinitialiser",
                                     {"app": "studio", "utilisateur": "claire"}, "donnees", "perso",
                                     maintenant=T0 + 100) is False


def test_approbation_pour_claire_ne_s_applique_pas_a_paul():
    """L'empreinte de l'approbation couvre les arguments : approuver claire n'autorise pas paul."""
    _preuve("claire")
    _preuve("paul", pid="P2")
    d = _demande("claire")
    assert approbations.approuver(d["id"], "tg:42", "telegram", maintenant=T0 + 10,
                                  utilisateur="perso") == (True, "ok")
    assert approbations.consommer("livraison_donnees_reinitialiser",
                                  {"app": "studio", "utilisateur": "paul"}, niveau="donnees",
                                  maintenant=T0 + 20, utilisateur="perso") is None


def test_mutation_cle_sans_cible_est_detectee(monkeypatch):
    """Si la clé ignorait l'utilisateur visé, l'isolation tomberait : ce test le prouverait."""
    monkeypatch.setattr(approbations, "cle_preuve", lambda nom, args: (args or {}).get("app"))
    _preuve("claire")
    assert _demande("paul")["prerequis"] == {PV: True}   # la mutation CASSE l'isolation
