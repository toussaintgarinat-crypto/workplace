"""Tests — API de la brique transferts."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True


import os


def test_configuration_expose_la_taille_de_partie():
    r = c.get("/configuration")
    assert r.status_code == 200
    d = r.json()
    assert d["taille_partie_octets"] == int(os.environ["TAILLE_PARTIE_OCTETS"])


def test_creer_transfert_sans_cle_api_ouvert_en_dev():
    r = c.post("/transferts", json={"expiration_heures": 1})
    assert r.status_code == 200
    assert "jeton_upload" in r.json()


def test_parcours_complet_upload_finalisation_telechargement():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid, jeton_upload = creation["id"], creation["jeton_upload"]

    fichier = c.post(f"/transferts/{tid}/fichiers",
                      json={"nom": "x.bin", "type_mime": "application/octet-stream",
                            "taille_clair": 20, "taille_partie": 16},
                      headers={"X-Upload-Token": jeton_upload}).json()
    fid = fichier["id"]
    assert fichier["nb_parties"] == 2

    r0 = c.put(f"/transferts/{tid}/fichiers/{fid}/parties/0",
               content=b"A" * 44, headers={"X-Upload-Token": jeton_upload})
    assert r0.status_code == 200 and r0.json()["complet"] is False
    r1 = c.put(f"/transferts/{tid}/fichiers/{fid}/parties/1",
               content=b"B" * 32, headers={"X-Upload-Token": jeton_upload})
    assert r1.json()["complet"] is True

    fin = c.post(f"/transferts/{tid}/finaliser", headers={"X-Upload-Token": jeton_upload}).json()
    jeton_public = fin["jeton_public"]

    meta = c.get(f"/t/{jeton_public}/meta").json()
    assert meta["statut"] == "actif"
    assert meta["fichiers"][0]["nom"] == "x.bin"

    brut = c.get(f"/t/{jeton_public}/fichiers/{fid}/chiffre")
    assert brut.status_code == 200
    assert brut.content == b"A" * 44 + b"B" * 32
    assert brut.headers["content-type"] == "application/octet-stream"


def test_upload_partie_mauvais_jeton_refuse():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid = creation["id"]
    fichier = c.post(f"/transferts/{tid}/fichiers",
                      json={"nom": "x.bin", "type_mime": "application/octet-stream",
                            "taille_clair": 10, "taille_partie": 16},
                      headers={"X-Upload-Token": creation["jeton_upload"]}).json()
    r = c.put(f"/transferts/{tid}/fichiers/{fichier['id']}/parties/0",
              content=b"z" * 38, headers={"X-Upload-Token": "faux-jeton"})
    assert r.status_code == 403


def test_meta_transfert_inconnu_404():
    assert c.get("/t/nimporte-quoi/meta").status_code == 404


def test_lister_et_revoquer():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid = creation["id"]
    assert any(t["id"] == tid for t in c.get("/transferts").json())
    r = c.post(f"/transferts/{tid}/revoquer")
    assert r.status_code == 200
    assert not any(t["id"] == tid for t in c.get("/transferts").json())


def test_revoquer_transfert_inconnu_404():
    assert c.post("/transferts/nimporte-quoi/revoquer").status_code == 404


def test_purge_executer_sans_cle_horloge_ouvert_en_dev():
    r = c.post("/purge/executer")
    assert r.status_code == 200
    assert "purges" in r.json()
