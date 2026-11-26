import calendar
import re
import time
from pathlib import Path

import pytest

import sauvegarde_forgejo
from executeur import ErreurExecuteur

SECRET = "s3cr3t-tres-long-et-unique"
CFG = {"KEY": "k", "S3_ENDPOINT": "http://s3.test:9106", "S3_BUCKET": "dokploy-backups",
       "S3_KEY": "AKIATEST", "S3_SECRET": SECRET, "S3_REGION": "us-east-1"}
MAINT = calendar.timegm((2026, 11, 26, 3, 15, 0))


class Faux:
    def __init__(self, anciens=(), taille_s3=None, dump=0, upload=0, liste=0):
        self.anciens, self.taille_s3, self.dump, self.upload, self.liste = \
            list(anciens), taille_s3, dump, upload, liste
        self.appels, self.supprimes = [], []

    def run(self, argv, stdin=None, timeout=300):
        self.appels.append((list(argv), stdin))
        if argv[:2] == ["docker", "exec"] and "dump" in argv:
            return self.dump, b"", b""
        if argv[:2] == ["docker", "cp"]:
            Path(argv[3]).write_bytes(b"Z" * 1000)
            return 0, b"", b""
        if argv[:2] == ["docker", "exec"] and "rm" in argv:
            return 0, b"", b""
        if argv[0] == "curl":
            if "-T" in argv:
                return self.upload, b"", b""
            if "-I" in argv:
                t = 1000 if self.taille_s3 is None else self.taille_s3
                return 0, f"HTTP/1.1 200 OK\r\nContent-Length: {t}\r\n\r\n".encode(), b""
            if "DELETE" in argv:
                self.supprimes.append(argv[-1].rsplit("/", 1)[-1])
                return 0, b"", b""
            if self.liste:
                return self.liste, b"", b""
            cles = "".join(f"<Key>forgejo/{n}</Key>" for n in self.anciens)
            return 0, f"<ListBucketResult>{cles}</ListBucketResult>".encode(), b""
        raise AssertionError(argv)


def test_nominal_envoie_verifie_et_garde_les_7_dernieres(tmp_path):
    anciens = [f"forgejo-2026110{i}T031500Z.zip" for i in range(1, 9)]   # 8 anciennes
    f = Faux(anciens)
    r = sauvegarde_forgejo.sauvegarder(f, CFG, garder=7, maintenant=MAINT, dossier=tmp_path)
    assert r["fichier"] == "forgejo-20261126T031500Z.zip" and r["taille"] == 1000
    # 8 anciennes + la nouvelle (la liste du faux ne contient pas la nouvelle) : on en garde 7 en
    # tout, la nouvelle comprise => 2 supprimées parmi les 8 anciennes (les plus vieilles).
    assert f.supprimes == ["forgejo-20261101T031500Z.zip", "forgejo-20261102T031500Z.zip"]
    assert r["supprimes"] == f.supprimes


def test_ne_supprime_jamais_la_nouvelle_ni_rien_si_peu_de_sauvegardes(tmp_path):
    f = Faux(["forgejo-20261101T031500Z.zip"])
    r = sauvegarde_forgejo.sauvegarder(f, CFG, garder=7, maintenant=MAINT, dossier=tmp_path)
    assert r["supprimes"] == [] and f.supprimes == []


def test_taille_differente_sur_le_s3_leve_et_ne_supprime_rien(tmp_path):
    f = Faux([f"forgejo-2026110{i}T031500Z.zip" for i in range(1, 9)], taille_s3=999)
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(f, CFG, garder=7, maintenant=MAINT, dossier=tmp_path)
    assert f.supprimes == []


def test_dump_en_echec_n_envoie_rien(tmp_path):
    f = Faux(dump=1)
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert not [a for a, _ in f.appels if a[0] == "curl"]


def test_upload_en_echec_leve(tmp_path):
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(Faux(upload=22), CFG, maintenant=MAINT, dossier=tmp_path)


def test_liste_en_echec_ne_supprime_rien_mais_la_sauvegarde_reste_valide(tmp_path):
    f = Faux(liste=22)
    r = sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert r["supprimes"] == [] and f.supprimes == []


def test_le_dump_est_toujours_retire_du_conteneur(tmp_path):
    f = Faux(upload=22)
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert any(a[:2] == ["docker", "exec"] and "rm" in a for a, _ in f.appels)


def test_secret_jamais_dans_argv(tmp_path):
    f = Faux()
    sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert all(SECRET not in " ".join(a) for a, _ in f.appels)
    assert any(s and SECRET.encode() in s for a, s in f.appels if a[0] == "curl")


def test_nom_de_fichier_horodate_trie_chronologiquement():
    assert re.fullmatch(r"forgejo-\d{8}T\d{6}Z\.zip", sauvegarde_forgejo.nom_fichier(MAINT))
