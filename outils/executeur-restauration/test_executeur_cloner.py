import re
import pytest
import executeur
from executeur import ErreurExecuteur
from test_executeur import FauxRunner, CFG, CORPS, _sql

NOUVELLE = "temoin_v0a1b2c3d"
CLONE = {**CORPS, "nouvelle_base": NOUVELLE}


def test_cloner_nominal_renomme_et_reattribue_au_compte_de_l_application():
    r = FauxRunner()
    out = executeur.cloner(r, CFG, dict(CLONE))
    assert out["ok"] is True and out["verdict"] == "valide" and out["nouvelle_base"] == NOUVELLE
    assert out["comptages_origine"] == out["comptages_restaures"] == {"evenements": 42}
    sqls = [a[-1] for a in r.commandes() if a[:2] == ["docker", "exec"] and "pg_restore" not in a]
    assert any(re.match(r"reassign owned by restore_\w+ to temoin", s) for s in sqls)
    assert any(re.match(rf"alter database restore_\w+ rename to {NOUVELLE}", s) for s in sqls)
    assert any(s.startswith("drop role if exists restore_") for s in sqls)
    # la base finale n'est pas supprimée
    assert not _sql(r, "drop database if exists restore_")


def test_cloner_reassign_owned_connecte_a_la_base_jetable():
    r = FauxRunner()
    executeur.cloner(r, CFG, dict(CLONE))
    cmd = [a for a in r.commandes() if a[:2] == ["docker", "exec"] and a[-1].startswith("reassign owned")][0]
    assert cmd[cmd.index("-d") + 1].startswith("restore_")


def test_cloner_comptages_differents_ne_cree_pas_la_base_finale():
    r = FauxRunner(restaure={"evenements": 41})
    out = executeur.cloner(r, CFG, dict(CLONE))
    assert out["verdict"] == "invalide" and out["nouvelle_base"] is None
    assert not any("rename to" in a[-1] for a in r.commandes() if a[:2] == ["docker", "exec"])
    assert len(_sql(r, "drop database if exists restore_")) == 1
    assert len(_sql(r, "drop role if exists restore_")) == 1


def test_cloner_echec_du_renommage_est_invalide_et_nettoie():
    class Casse(FauxRunner):
        def run(self, argv, stdin=None, timeout=300):
            if argv[:2] == ["docker", "exec"] and "rename to" in argv[-1]:
                self.appels.append((list(argv), stdin))
                return 1, b"", b"boom"
            return super().run(argv, stdin, timeout)
    r = Casse()
    out = executeur.cloner(r, CFG, dict(CLONE))
    assert out["verdict"] == "invalide" and out["nouvelle_base"] is None
    assert len(_sql(r, "drop database if exists restore_")) == 1
    assert len(_sql(r, "drop role if exists restore_")) == 1


@pytest.mark.parametrize("nom", ["temoin", "temoin_v1", "Temoin_v0a1b2c3d", "temoin_v0a1b2c3d;x",
                                 "temoin_v0a1b2c3d\n", ""])
def test_cloner_refuse_un_nom_de_base_finale_hors_format(nom):
    r = FauxRunner()
    with pytest.raises(ErreurExecuteur) as e:
        executeur.cloner(r, CFG, {**CORPS, "nouvelle_base": nom})
    assert e.value.statut == 400 and r.appels == []


def test_cloner_refuse_nouvelle_base_egale_a_base():
    r = FauxRunner()
    with pytest.raises(ErreurExecuteur) as e:
        executeur.cloner(r, CFG, {**CORPS, "base": NOUVELLE, "nouvelle_base": NOUVELLE})
    assert e.value.statut == 400 and r.appels == []


def test_cloner_archive_invalide_ne_touche_pas_a_la_base():
    r = FauxRunner(dump=b"pas un dump")
    out = executeur.cloner(r, CFG, dict(CLONE))
    assert out["verdict"] == "invalide" and out["nouvelle_base"] is None
    assert not _sql(r, "create database")


def test_supprimer_base_refuse_une_base_d_origine():
    r = FauxRunner()
    for nom in ("temoin", "postgres", "template1", "restore_0a1b2c3d"):
        with pytest.raises(ErreurExecuteur) as e:
            executeur.supprimer_base(r, CFG, {"service": CORPS["service"], "utilisateur": "temoin", "base": nom})
        assert e.value.statut == 400
    assert r.appels == []


def test_supprimer_base_generee_ok():
    r = FauxRunner()
    assert executeur.supprimer_base(r, CFG, {"service": CORPS["service"], "utilisateur": "temoin",
                                              "base": NOUVELLE}) == {"ok": True}
    assert len(_sql(r, f"drop database if exists {NOUVELLE} with (force)")) == 1


def test_comptages_lecture_seule():
    r = FauxRunner()
    out = executeur.lire_comptages(r, CFG, {"service": CORPS["service"], "utilisateur": "temoin", "base": "temoin"})
    assert out == {"ok": True, "comptages": {"evenements": 42}}
    assert not _sql(r, "create") and not _sql(r, "drop")


def test_routes_http_cloner_comptages_supprimer(monkeypatch):
    import json, threading, urllib.request
    from http.server import ThreadingHTTPServer
    r = FauxRunner()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), executeur.fabrique_handler(r, CFG))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def post(chemin, corps, cle="cle-exec"):
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}{chemin}",
                                         data=json.dumps(corps).encode(), method="POST",
                                         headers={"X-API-Key": cle, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as rep:
                    return rep.status, json.loads(rep.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        assert post("/cloner", CLONE)[1]["verdict"] == "valide"
        assert post("/comptages", {"service": CORPS["service"], "utilisateur": "temoin", "base": "temoin"})[1]["ok"]
        assert post("/supprimer-base", {"service": CORPS["service"], "utilisateur": "temoin", "base": NOUVELLE}) == (200, {"ok": True})
        assert post("/cloner", CLONE, cle="mauvaise")[0] == 401
        assert post("/inconnu", CLONE)[0] == 404
    finally:
        srv.shutdown()
