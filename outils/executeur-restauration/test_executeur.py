import gzip
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import executeur
from executeur import ErreurExecuteur

SECRET = "s3cr3t-tres-long-et-unique"
CFG = {"KEY": "cle-exec", "S3_ENDPOINT": "http://s3.test:9106", "S3_BUCKET": "dokploy-backups",
       "S3_KEY": "AKIATEST", "S3_SECRET": SECRET, "S3_REGION": "us-east-1"}
CORPS = {"service": "postgres-abc-def", "utilisateur": "temoin", "base": "temoin",
         "objet": "postgres-abc-def/s247-pg/2026-11-26T10-00-00-000Z.sql.gz"}


class FauxRunner:
    def __init__(self, origine=None, restaure=None, dump=b"PGDMP\x01\x0f\x00donnees",
                 pg_restore=0, curl=0, ids="abc123\n"):
        self.origine = {"evenements": 42} if origine is None else origine
        self.restaure = dict(self.origine) if restaure is None else restaure
        self.dump, self.pg_restore, self.curl, self.ids = dump, pg_restore, curl, ids
        self.appels = []

    def run(self, argv, stdin=None, timeout=300):
        self.appels.append((list(argv), stdin))
        if argv[:2] == ["docker", "ps"]:
            return 0, self.ids.encode(), b""
        if argv[0] == "curl":
            if self.curl:
                return self.curl, b"", b""
            Path(argv[argv.index("-o") + 1]).write_bytes(gzip.compress(self.dump))
            return 0, b"", b""
        if argv[:2] == ["docker", "exec"]:
            if "pg_restore" in argv:
                return self.pg_restore, b"", b""
            sql, base = argv[-1], argv[argv.index("-d") + 1]
            if "create database" in sql or "drop database" in sql:
                return 0, b"", b""
            tables = self.restaure if base.startswith("restore_") else self.origine
            if "information_schema" in sql:
                return 0, "\n".join(tables).encode(), b""
            return 0, str(tables[re.search(r'from "(\w+)"', sql).group(1)]).encode(), b""
        raise AssertionError(argv)

    def commandes(self):
        return [a for a, _ in self.appels]


def _sql(r, motif):
    return [a for a in r.commandes() if a[:2] == ["docker", "exec"] and motif in a[-1]]


def test_nominal_valide_et_base_jetable_supprimee():
    r = FauxRunner()
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["ok"] is True and out["verdict"] == "valide" and out["raison"] is None
    assert out["nettoyage"] == "ok"
    assert out["comptages_origine"] == out["comptages_restaures"] == {"evenements": 42}
    assert len(_sql(r, "create database restore_")) == 1
    assert len(_sql(r, "drop database if exists restore_")) == 1


def test_comptages_differents_invalide_et_base_supprimee():
    r = FauxRunner(restaure={"evenements": 41})
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "comptages" in out["raison"]
    assert len(_sql(r, "drop database if exists restore_")) == 1


def test_dump_qui_n_est_pas_un_pg_dump_est_refuse_sans_creer_de_base():
    r = FauxRunner(dump=b"pas un dump")
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "format" in out["raison"]
    assert _sql(r, "create database") == []


def test_archive_non_gzip_est_invalide():
    class R(FauxRunner):
        def run(self, argv, stdin=None, timeout=300):
            if argv[0] == "curl" and not self.curl:
                self.appels.append((list(argv), stdin))
                Path(argv[argv.index("-o") + 1]).write_bytes(b"ceci n'est pas du gzip")
                return 0, b"", b""
            return super().run(argv, stdin, timeout)
    out = executeur.verifier(R(), CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "illisible" in out["raison"]


def test_pg_restore_en_echec_invalide_et_base_supprimee():
    r = FauxRunner(pg_restore=1)
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "pg_restore" in out["raison"]
    assert len(_sql(r, "drop database if exists restore_")) == 1


def test_base_sans_table_ne_prouve_rien():
    out = executeur.verifier(FauxRunner(origine={}, restaure={}), CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "aucune table" in out["raison"]


@pytest.mark.parametrize("champ,valeur", [
    ("service", "postgres-x; rm"), ("service", "mysql-abc-def"), ("service", "postgres-ab"),
    ("base", "Temoin"), ("base", "a;b"), ("utilisateur", "x y"),
    ("objet", "../etc/passwd"), ("objet", "/abs/chemin"), ("objet", "a/../b"), ("objet", "a b"),
    ("objet", ""), ("service", "postgres-abc-def\n"), ("utilisateur", "temoin\n"),
    ("base", "temoin\n"), ("objet", "a/b.gz\n")])
def test_arguments_invalides_refuses_avant_tout_appel(champ, valeur):
    r = FauxRunner()
    corps = {**CORPS, champ: valeur}
    with pytest.raises(ErreurExecuteur) as e:
        executeur.verifier(r, CFG, corps)
    assert e.value.statut == 400 and r.appels == []


def test_corps_non_objet_refuse():
    with pytest.raises(ErreurExecuteur) as e:
        executeur.verifier(FauxRunner(), CFG, ["x"])
    assert e.value.statut == 400


def test_conteneur_introuvable_ou_ambigu_404():
    for ids in ("", "a1\nb2\n"):
        with pytest.raises(ErreurExecuteur) as e:
            executeur.verifier(FauxRunner(ids=ids), CFG, dict(CORPS))
        assert e.value.statut == 404


def test_telechargement_en_echec_502():
    with pytest.raises(ErreurExecuteur) as e:
        executeur.verifier(FauxRunner(curl=22), CFG, dict(CORPS))
    assert e.value.statut == 502 and SECRET not in e.value.message


def test_le_secret_s3_ne_passe_jamais_dans_argv_seulement_par_stdin():
    r = FauxRunner()
    executeur.verifier(r, CFG, dict(CORPS))
    assert all(SECRET not in " ".join(a) for a in r.commandes())
    curl = [(a, s) for a, s in r.appels if a[0] == "curl"][0]
    assert SECRET.encode() in curl[1] and "-K" in curl[0]


def test_config_incomplete_refusee():
    with pytest.raises(ErreurExecuteur):
        executeur.charger_config({"EXECUTEUR_KEY": "k"})
    cfg = executeur.charger_config({"EXECUTEUR_KEY": "k", "EXECUTEUR_S3_ENDPOINT": "http://x",
                                    "EXECUTEUR_S3_BUCKET": "b", "EXECUTEUR_S3_KEY": "a",
                                    "EXECUTEUR_S3_SECRET": "s"})
    assert cfg["S3_REGION"] == "us-east-1"


@pytest.fixture
def serveur():
    runner = FauxRunner()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), executeur.fabrique_handler(runner, CFG))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", runner
    srv.shutdown()
    srv.server_close()


def _post(url, corps, cle=None):
    h = {"Content-Type": "application/json"}
    if cle:
        h["X-API-Key"] = cle
    req = urllib.request.Request(url + "/verifier", data=json.dumps(corps).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http_sans_cle_ou_mauvaise_cle_401_et_rien_execute(serveur):
    url, runner = serveur
    assert _post(url, CORPS)[0] == 401
    assert _post(url, CORPS, "mauvaise")[0] == 401
    assert runner.appels == []


def test_http_nominal_200(serveur):
    url, _ = serveur
    code, corps = _post(url, CORPS, "cle-exec")
    assert code == 200 and corps["verdict"] == "valide"


def test_http_validation_400(serveur):
    url, _ = serveur
    assert _post(url, {**CORPS, "objet": "../x"}, "cle-exec")[0] == 400


def test_http_une_verification_a_la_fois_409(serveur):
    url, _ = serveur
    assert executeur.VERROU.acquire(blocking=False)
    try:
        assert _post(url, CORPS, "cle-exec")[0] == 409
    finally:
        executeur.VERROU.release()


def test_http_sante_et_route_inconnue(serveur):
    url, _ = serveur
    with urllib.request.urlopen(url + "/sante", timeout=10) as r:
        assert json.loads(r.read())["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url + "/autre", timeout=10)
    assert e.value.code == 404


def test_pg_restore_timeout_124_invalide_et_base_supprimee_avec_force():
    r = FauxRunner(pg_restore=124)
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "pg_restore" in out["raison"]
    drops = _sql(r, "drop database if exists restore_")
    assert len(drops) == 1 and drops[0][-1].endswith("with (force)")


def test_nettoyage_en_echec_signale():
    class R(FauxRunner):
        def run(self, argv, stdin=None, timeout=300):
            if argv[:2] == ["docker", "exec"] and "drop database" in argv[-1]:
                self.appels.append((list(argv), stdin))
                return 1, b"", b""
            return super().run(argv, stdin, timeout)
    out = executeur.verifier(R(), CFG, dict(CORPS))
    assert out["verdict"] == "valide" and out["nettoyage"] == "echec"


def test_flux_deflate_corrompu_est_invalide():
    import zlib
    class R(FauxRunner):
        def run(self, argv, stdin=None, timeout=300):
            if argv[0] == "curl":
                self.appels.append((list(argv), stdin))
                bon = gzip.compress(b"PGDMP" + b"x" * 5000)
                Path(argv[argv.index("-o") + 1]).write_bytes(bon[:20] + b"\xff\xfe\xfd" * 10 + bon[50:])
                return 0, b"", b""
            return super().run(argv, stdin, timeout)
    out = executeur.verifier(R(), CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "illisible" in out["raison"]


def test_runner_convertit_timeout_en_124():
    code, _, err = executeur.Runner().run(["sleep", "5"], timeout=1)
    assert code == 124 and err == b"timeout"


def test_http_exception_inattendue_500_sans_detail(serveur):
    url, runner = serveur
    def boom(argv, stdin=None, timeout=300):
        raise ValueError("secret interne")
    runner.run = boom
    code, corps = _post(url, CORPS, "cle-exec")
    assert code == 500 and corps == {"erreur": "erreur interne de l'exécuteur"}
    assert not executeur.VERROU.locked()


def test_config_refuse_caracteres_dangereux_pour_curl():
    base = {"EXECUTEUR_KEY": "k", "EXECUTEUR_S3_ENDPOINT": "http://x", "EXECUTEUR_S3_BUCKET": "b",
            "EXECUTEUR_S3_KEY": "a", "EXECUTEUR_S3_SECRET": "s"}
    for champ in ("S3_ENDPOINT", "S3_BUCKET", "S3_KEY", "S3_SECRET"):
        for mauvais in ('a"b', "a\\b", "a\rb", "a\nb"):
            with pytest.raises(ErreurExecuteur) as e:
                executeur.charger_config({**base, "EXECUTEUR_" + champ: mauvais})
            assert e.value.statut == 500


def test_handler_timeout_socket():
    assert executeur.fabrique_handler(FauxRunner(), CFG).timeout == 30


def test_curl_plafonne_la_taille_et_filtre_conteneur_avec_point():
    r = FauxRunner()
    executeur.verifier(r, CFG, dict(CORPS))
    curl = [a for a in r.commandes() if a[0] == "curl"][0]
    assert "--max-filesize" in curl and curl[curl.index("--max-filesize") + 1] == "536870912"
    ps = [a for a in r.commandes() if a[:2] == ["docker", "ps"]][0]
    assert "name=^postgres-abc-def\\." in ps
