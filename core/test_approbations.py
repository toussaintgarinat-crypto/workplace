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
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 10) == (True, "ok")
    lue = approbations.lire(a["id"])
    assert lue["statut"] == "approuvee" and lue["decide_par"] == "tg:42"


def test_double_approbation_refusee():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 2) == (False, "deja_decidee")


def test_approuver_apres_expiration_marque_expiree():
    a = _demande()
    ok, raison = approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 31 * 60)
    assert (ok, raison) == (False, "expiree")
    assert approbations.lire(a["id"])["statut"] == "expiree"


def test_destructif_ne_s_approuve_pas_par_bouton_seul():
    a = _demande("destructif")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (False, "code_requis")
    assert approbations.lire(a["id"])["statut"] == "en_attente"


def test_id_inconnu():
    assert approbations.approuver("0" * 32, "tg:42", "telegram") == (False, "introuvable")
    assert approbations.refuser("0" * 32, "tg:42", "telegram") == (False, "introuvable")


def test_refuser_puis_plus_d_approbation():
    a = _demande()
    assert approbations.refuser(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (True, "ok")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 2) == (False, "deja_decidee")


def test_journal_append_only_trace_chaque_transition():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    assert [e["evenement"] for e in approbations.journal(a["id"])] == ["creee", "approuvee"]
    with sqlite3.connect(approbations.DB) as c:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute("UPDATE approbations_journal SET evenement='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute("DELETE FROM approbations_journal")


def test_persistance_apres_redemarrage():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    approbations.init_db()  # « redémarrage » : la base reste, init_db est idempotent
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_prerequis_bloquent_l_approbation():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee",))
    assert a["prerequis"] == {"sauvegarde_verifiee": False}
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (False, "prerequis")
