import json

import pytest

import paquets as P

H = "0123456789abcdef"


def _enreg(pid=None, t=1000.0, app="studio"):
    pid = pid or P.nouveau_id()
    return P.enregistrer(pid, app, H, P.cle_objet(app, H, pid), "emp", {"series": 1}, "1", t)


def test_empreinte_utilisateur_stable_et_sans_clair():
    assert P.empreinte_utilisateur("claire") == P.empreinte_utilisateur("claire")
    assert len(P.empreinte_utilisateur("claire")) == 16 and "claire" not in P.empreinte_utilisateur("claire")


def test_cle_objet_forme_valide():
    import re
    pid = P.nouveau_id()
    assert re.fullmatch(r"contrat/[a-z0-9_-]{1,40}/[0-9a-f]{16}/[0-9a-f]{32}\.bin",
                        P.cle_objet("studio", H, pid))


@pytest.mark.parametrize("app", ["../x", "Studio", "a/b", "", "x" * 41])
def test_cle_objet_refuse_app_dangereuse(app):
    with pytest.raises(ValueError):
        P.cle_objet(app, H, P.nouveau_id())


def test_enregistrer_lire_retention_14_jours():
    r = _enreg(t=1000.0)
    assert P.lire(r["id"])["expire_a"] == 1000.0 + 14 * 86400
    assert P.lire(r["id"])["verifie_a"] is None and "utilisateur" not in r


def test_marquer_verifie_et_inconnu():
    r = _enreg()
    assert P.marquer_verifie(r["id"], 2000.0)["verifie_a"] == 2000.0
    assert P.marquer_verifie("0" * 32) is None


def test_expires_et_retirer():
    a, b = _enreg(t=0.0), _enreg(t=10 * 86400.0)
    ids = [x["id"] for x in P.expires(maintenant=15 * 86400.0)]
    assert ids == [a["id"]]
    P.retirer(a["id"])
    assert P.lire(a["id"]) is None and P.lire(b["id"]) is not None
    P.retirer(a["id"])  # idempotent


def test_registre_illisible_se_lit_comme_vide(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "paquets.json").write_text("{pas du json")
    assert P.lire("0" * 32) is None and P.expires() == []


def test_journal_sans_donnee_perso():
    P.journaliser("exporter", "studio", H, "a" * 32, True, 5.0)
    import os
    ligne = json.loads(open(os.path.join(os.environ["LIVRAISON_DATA"], "acces.jsonl")).read().strip())
    assert ligne == {"t": 5.0, "operation": "exporter", "app": "studio", "h": H,
                     "paquet": "a" * 32, "ok": True}


def test_registre_corrompu_non_ecrase_par_les_ecrivains(tmp_path):
    f = tmp_path / "data" / "paquets.json"
    f.parent.mkdir()
    f.write_text("{pas du json")
    with pytest.raises(OSError):
        _enreg()
    with pytest.raises(OSError):
        P.retirer("0" * 32)
    assert f.read_text() == "{pas du json"
    f.write_text("[1]")
    with pytest.raises(OSError):
        _enreg()
    assert f.read_text() == "[1]"


def test_registre_absent_enregistrer_fonctionne():
    r = _enreg()
    assert P.lire(r["id"]) is not None


def test_expire_a_illisible_compte_comme_expire():
    r = _enreg()
    f = P._chemin()
    d = json.loads(f.read_text())
    d[r["id"]]["expire_a"] = "n'importe quoi"
    f.write_text(json.dumps(d))
    assert [x["id"] for x in P.expires(maintenant=0.0)] == [r["id"]]


def _verifie(t_exp, t_ver, app="studio", h=H):
    r = _enreg(t=t_exp, app=app)
    tout = P._lire_tout()
    tout[r["id"]] = {**tout[r["id"]], "h": h}
    P._ecrire_tout(tout)
    P.marquer_verifie(r["id"], t_ver)
    return r["id"]


def test_dernier_verifie_prend_le_plus_recent_verifie():
    _verifie(0.0, 100.0)
    b = _verifie(0.0, 200.0)
    assert P.dernier_verifie("studio", H, maintenant=300.0)["id"] == b


def test_dernier_verifie_ignore_non_verifie_expire_perime_consomme_autre_cible():
    _enreg(t=0.0)                                           # non vérifié
    assert P.dernier_verifie("studio", H, 10.0) is None
    vieux = _verifie(0.0, 1.0)                              # vérifié mais preuve de 6 h dépassée
    assert P.dernier_verifie("studio", H, 1.0 + 6 * 3600 + 1) is None
    assert P.dernier_verifie("studio", H, 1.0 + 6 * 3600 + 1, preuve_s=None)["id"] == vieux
    assert P.dernier_verifie("studio", H, 15 * 86400.0, preuve_s=None) is None   # rétention dépassée
    assert P.dernier_verifie("studio", "f" * 16, 10.0) is None
    assert P.dernier_verifie("autre", H, 10.0) is None
    P.marquer_consomme(vieux, 5.0)
    assert P.dernier_verifie("studio", H, 10.0, preuve_s=None) is None


def test_dernier_verifie_inclure_consommes():
    pid = _verifie(0.0, 1.0)
    P.marquer_consomme(pid, 5.0)
    assert P.dernier_verifie("studio", H, 10.0) is None
    assert P.dernier_verifie("studio", H, 10.0, inclure_consommes=True)["id"] == pid


def test_enregistrer_pose_consomme_a_none_et_marquer_consomme_inconnu():
    assert _enreg()["consomme_a"] is None
    assert P.marquer_consomme("0" * 32) is None


def test_marquer_consomme_pose_la_date():
    pid = _verifie(0.0, 1.0)
    assert P.marquer_consomme(pid, 7.0)["consomme_a"] == 7.0
    assert P.lire(pid)["consomme_a"] == 7.0


def test_marquer_consomme_registre_corrompu_leve_et_ne_touche_pas(tmp_path):
    f = tmp_path / "data" / "paquets.json"
    f.parent.mkdir()
    f.write_text("{pas du json")
    with pytest.raises(OSError):
        P.marquer_consomme("0" * 32)
    assert f.read_text() == "{pas du json"


def test_dernier_verifie_ignore_dates_illisibles():
    bon = _verifie(0.0, 100.0)
    for champ in ("verifie_a", "expire_a"):
        mauvais = _verifie(0.0, 200.0)
        tout = P._lire_tout()
        tout[mauvais][champ] = "n'importe quoi"
        P._ecrire_tout(tout)
        assert P.dernier_verifie("studio", H, 300.0)["id"] == bon
        P.retirer(mauvais)


# --- S248 3b fix : restitue_a, dernier_a_restituer, dates non finies / futures ---

def _verifie_a(t_verif, t_cree=1.0, consomme=None, restitue=None, app="studio"):
    r = _enreg(t=t_cree, app=app)
    P.marquer_verifie(r["id"], t_verif)
    if consomme is not None:
        P.marquer_consomme(r["id"], consomme)
    if restitue is not None:
        P.marquer_restitue(r["id"], restitue)
    return r["id"]


def test_enregistrer_pose_restitue_a_none_et_marquer_restitue():
    r = _enreg()
    assert r["restitue_a"] is None
    assert P.marquer_restitue(r["id"], 42.0)["restitue_a"] == 42.0
    assert P.lire(r["id"])["restitue_a"] == 42.0
    assert P.marquer_restitue("0" * 32, 1.0) is None


def test_marquer_restitue_refuse_registre_corrompu(tmp_path):
    _enreg()
    (P._dossier() / "paquets.json").write_text("{pas du json")
    with pytest.raises(OSError):
        P.marquer_restitue("0" * 32, 1.0)


def test_dernier_a_restituer_prefere_le_consomme_non_restitue_le_plus_recemment_consomme():
    a = _verifie_a(10.0, consomme=100.0)
    b = _verifie_a(20.0, consomme=200.0)
    _verifie_a(500.0)                                   # plus frais verifié, non consommé
    assert P.dernier_a_restituer("studio", H, 1000.0)["id"] == b
    P.marquer_restitue(b, 300.0)
    assert P.dernier_a_restituer("studio", H, 1000.0)["id"] == a


def test_dernier_a_restituer_repli_sur_dernier_verifie_non_consomme_ou_none():
    assert P.dernier_a_restituer("studio", H, 1000.0) is None
    x = _verifie_a(10.0, consomme=100.0, restitue=150.0)
    assert P.dernier_a_restituer("studio", H, 1000.0) is None
    y = _verifie_a(20.0)
    assert P.dernier_a_restituer("studio", H, 1000.0)["id"] == y
    assert x != y


def test_dernier_a_restituer_ignore_expire_non_verifie_autre_cible():
    _verifie_a(10.0, consomme=100.0)
    assert P.dernier_a_restituer("studio", H, 1.0 + 14 * 86400) is None      # expire_a == now exclu
    assert P.dernier_a_restituer("studio", H, 1.0 + 14 * 86400 - 1) is not None
    assert P.dernier_a_restituer("autre", H, 1000.0) is None
    assert P.dernier_a_restituer("studio", "f" * 16, 1000.0) is None
    r = _enreg(t=1.0)
    P.marquer_consomme(r["id"], 5.0)                                          # non vérifié
    assert P.dernier_a_restituer("studio", H, 1000.0)["id"] != r["id"]


@pytest.mark.parametrize("v", [float("nan"), float("inf"), "abc", 10 ** 12])
def test_dernier_a_restituer_dates_illisibles_ou_futures_inegibles(v):
    r = _enreg(t=1.0)
    tout = json.loads((P._dossier() / "paquets.json").read_text())
    tout[r["id"]]["verifie_a"] = v
    tout[r["id"]]["consomme_a"] = 5.0
    (P._dossier() / "paquets.json").write_text(json.dumps(tout))   # json.dumps écrit NaN/Infinity
    assert P.dernier_a_restituer("studio", H, 1000.0) is None


def test_dernier_a_restituer_consomme_a_non_fini_inegible():
    r = _enreg(t=1.0)
    P.marquer_verifie(r["id"], 10.0)
    tout = json.loads((P._dossier() / "paquets.json").read_text())
    tout[r["id"]]["consomme_a"] = float("nan")
    (P._dossier() / "paquets.json").write_text(json.dumps(tout))
    assert P.dernier_a_restituer("studio", H, 1000.0) is None


def test_dernier_verifie_frontieres_exactes_et_dates_futures():
    pid = _verifie_a(100.0)
    assert P.dernier_verifie("studio", H, 100.0 + P.PREUVE_TTL_S) is None          # == exclu
    assert P.dernier_verifie("studio", H, 100.0 + P.PREUVE_TTL_S - 1)["id"] == pid
    assert P.dernier_verifie("studio", H, 99.0) is None                            # verifie_a futur
    assert P.dernier_verifie("studio", H, 99.0, preuve_s=None) is None
    assert P.dernier_verifie("studio", H, 100.0)["id"] == pid                      # == now accepté


def test_dernier_verifie_nan_inf_et_expire_a_non_fini():
    r = _enreg(t=1.0)
    P.marquer_verifie(r["id"], 10.0)
    tout = json.loads((P._dossier() / "paquets.json").read_text())
    for cle, val in (("verifie_a", float("nan")), ("verifie_a", float("inf"))):
        t2 = json.loads(json.dumps(tout))
        t2[r["id"]][cle] = val
        (P._dossier() / "paquets.json").write_text(json.dumps(t2))
        assert P.dernier_verifie("studio", H, 20.0, preuve_s=None) is None
    t3 = json.loads(json.dumps(tout))
    t3[r["id"]]["expire_a"] = float("inf")
    (P._dossier() / "paquets.json").write_text(json.dumps(t3))
    assert P.dernier_verifie("studio", H, 20.0, preuve_s=None) is None
    assert P.expires(20.0)
