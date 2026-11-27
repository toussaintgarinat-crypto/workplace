import hashlib
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
CLE = "contrat/studio/0123456789abcdef/" + "a" * 32 + ".bin"


class FauxS3:
    def __init__(self, echec=0):
        self.objets, self.appels, self.echec = {}, [], echec

    def run(self, argv, stdin=None, timeout=300):
        self.appels.append((list(argv), stdin))
        if self.echec:
            return self.echec, b"", b""
        url = argv[-1]
        if "-T" in argv:
            self.objets[url] = Path(argv[argv.index("-T") + 1]).read_bytes()
        elif "DELETE" in argv:
            self.objets.pop(url, None)
        else:
            Path(argv[argv.index("-o") + 1]).write_bytes(self.objets[url])
        return 0, b"", b""


def test_cle_objet_valide_et_refus():
    assert executeur.cle_objet("/objets/" + CLE) == CLE
    for mauvais in ("/objets/../x", "/objets/contrat/../../x.bin", "/objets/autre/x.bin",
                    "/objets/contrat/Studio/0123456789abcdef/" + "a" * 32 + ".bin",
                    "/objets/" + CLE + "\n", "/objets/"):
        with pytest.raises(ErreurExecuteur) as e:
            executeur.cle_objet(mauvais)
        assert e.value.statut == 400


def test_deposer_lire_supprimer_et_secret_hors_argv(tmp_path):
    r = FauxS3()
    src = tmp_path / "p.bin"
    src.write_bytes(b"chiffre")
    executeur.deposer_objet(r, CFG, CLE, src)
    argv, stdin = r.appels[0]
    assert SECRET not in " ".join(argv) and SECRET.encode() in stdin
    assert "x-amz-content-sha256: " + hashlib.sha256(b"chiffre").hexdigest() in argv
    dest = tmp_path / "out.bin"
    executeur.lire_objet(r, CFG, CLE, dest)
    assert dest.read_bytes() == b"chiffre"
    executeur.supprimer_objet(r, CFG, CLE)
    assert r.objets == {}


def test_echec_curl_502_message_fixe(tmp_path):
    src = tmp_path / "p.bin"
    src.write_bytes(b"x")
    with pytest.raises(ErreurExecuteur) as e:
        executeur.deposer_objet(FauxS3(echec=22), CFG, CLE, src)
    assert e.value.statut == 502 and SECRET not in e.value.message


@pytest.fixture
def serveur():
    r = FauxS3()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), executeur.fabrique_handler(r, CFG))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", r
    srv.shutdown()


def _req(base, methode, chemin, corps=None, cle="cle-exec"):
    q = urllib.request.Request(base + chemin, data=corps, method=methode,
                               headers={"X-API-Key": cle})
    try:
        with urllib.request.urlopen(q) as rep:
            return rep.status, rep.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_http_put_get_delete(serveur):
    base, r = serveur
    assert _req(base, "PUT", "/objets/" + CLE, b"octets-chiffres")[0] == 200
    assert _req(base, "GET", "/objets/" + CLE) == (200, b"octets-chiffres")
    assert _req(base, "DELETE", "/objets/" + CLE)[0] == 200
    assert r.objets == {}


def test_http_401_et_cle_invalide_et_corps_trop_gros(serveur, monkeypatch):
    base, _ = serveur
    assert _req(base, "PUT", "/objets/" + CLE, b"x", cle="fausse")[0] == 401
    assert _req(base, "GET", "/objets/" + CLE, cle="fausse")[0] == 401
    assert _req(base, "PUT", "/objets/autre/x.bin", b"x")[0] == 400
    monkeypatch.setattr(executeur, "MAX_OBJET", 3)
    assert _req(base, "PUT", "/objets/" + CLE, b"xxxx")[0] == 413
