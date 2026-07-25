"""Tests — stockage.py (SQLite + fichiers sur disque, tout est réel, rien n'est mocké :
c'est juste du I/O local, pas de dépendance externe)."""
import time
from pathlib import Path

import pytest

import stockage


@pytest.fixture(autouse=True)
def _base_propre(tmp_path, monkeypatch):
    monkeypatch.setattr(stockage, "DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(stockage, "DIR", tmp_path / "fichiers")
    stockage.DIR.mkdir(parents=True, exist_ok=True)
    stockage.init_db()


def test_creer_transfert_genere_un_jeton_upload_et_une_expiration():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    assert t["jeton_upload"]
    assert len(t["jeton_upload"]) >= 32
    assert t["expire_le"] > time.time()


def test_ajouter_fichier_calcule_le_nombre_de_parties():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "photo.jpg", "image/jpeg",
                                  taille_clair=40, taille_partie=16)
    assert f["nb_parties"] == 3   # ceil(40/16) = 3


def test_ajouter_fichier_jeton_invalide_leve():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    with pytest.raises(ValueError, match="jeton"):
        stockage.ajouter_fichier(t["id"], "mauvais-jeton", "x.bin", "application/octet-stream",
                                  taille_clair=10, taille_partie=16)


def test_ecrire_partie_puis_completude():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=20, taille_partie=16)
    # 2 parties attendues : 16 + 4 (clair) => 16+28=44 et 4+28=32 octets chiffrés
    r1 = stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"x" * 44)
    assert r1["complet"] is False
    r2 = stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 1, b"y" * 32)
    assert r2["complet"] is True
    assert r2["parties_recues"] == 2


def test_ecrire_partie_reecriture_idempotente():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=10, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"z" * 38)
    r = stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"z" * 38)  # retry réseau
    assert r["parties_recues"] == 1   # pas doublé


def test_finaliser_avant_completude_leve():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                              taille_clair=20, taille_partie=16)
    with pytest.raises(ValueError, match="complet"):
        stockage.finaliser_transfert(t["id"], t["jeton_upload"])


def test_finaliser_concatene_les_parties_dans_l_ordre():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=20, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 44)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 1, b"B" * 32)
    res = stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    assert res["jeton_public"]
    chemin = stockage.chemin_ciphertext(t["id"], f["id"])
    assert chemin.read_bytes() == b"A" * 44 + b"B" * 32


def test_lire_transfert_public_apres_finalisation():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=20, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 44)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 1, b"B" * 32)
    res = stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    pub = stockage.lire_transfert_public(res["jeton_public"])
    assert pub["statut"] == "actif"
    assert len(pub["fichiers"]) == 1
    assert pub["fichiers"][0]["nom"] == "x.bin"


def test_lire_transfert_public_inconnu_est_none():
    assert stockage.lire_transfert_public("nimporte-quoi") is None


def test_lire_transfert_public_expire():
    t = stockage.creer_transfert("perso", expiration_heures=-1)  # déjà expiré
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=1, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 29)
    res = stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    pub = stockage.lire_transfert_public(res["jeton_public"])
    assert pub["statut"] == "expire"


def test_lister_transferts_scope_par_proprietaire():
    stockage.creer_transfert("alice", expiration_heures=1)
    stockage.creer_transfert("bob", expiration_heures=1)
    assert len(stockage.lister_transferts("alice")) == 1
    assert len(stockage.lister_transferts("bob")) == 1


def test_revoquer_supprime_les_fichiers_sur_disque():
    t = stockage.creer_transfert("perso", expiration_heures=1)
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=10, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 38)
    stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    chemin = stockage.chemin_ciphertext(t["id"], f["id"])
    assert chemin.exists()
    assert stockage.revoquer(t["id"], "perso") is True
    assert not chemin.exists()
    assert stockage.lister_transferts("perso") == []


def test_revoquer_mauvais_proprietaire_refuse():
    t = stockage.creer_transfert("alice", expiration_heures=1)
    assert stockage.revoquer(t["id"], "bob") is False


def test_purger_expires_supprime_disque_et_db():
    t = stockage.creer_transfert("perso", expiration_heures=-1)  # déjà expiré
    f = stockage.ajouter_fichier(t["id"], t["jeton_upload"], "x.bin", "application/octet-stream",
                                  taille_clair=1, taille_partie=16)
    stockage.ecrire_partie(t["id"], f["id"], t["jeton_upload"], 0, b"A" * 29)
    stockage.finaliser_transfert(t["id"], t["jeton_upload"])
    chemin = stockage.chemin_ciphertext(t["id"], f["id"])
    assert chemin.exists()
    assert stockage.purger_expires() == 1
    assert not chemin.exists()
    assert stockage.lister_transferts("perso") == []
