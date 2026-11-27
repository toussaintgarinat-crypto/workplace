import base64
import os

import pytest

import chiffrement as C


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


def test_aller_retour_et_non_deterministe():
    a, b = C.chiffrer(b"secret", "ctx"), C.chiffrer(b"secret", "ctx")
    assert a != b and b"secret" not in a
    assert C.dechiffrer(a, "ctx") == b"secret"


def test_contexte_different_refuse():
    with pytest.raises(C.Illisible):
        C.dechiffrer(C.chiffrer(b"x", "ctx-1"), "ctx-2")


def test_blob_altere_ou_trop_court_refuse():
    blob = bytearray(C.chiffrer(b"x", "c"))
    blob[-1] ^= 1
    for mauvais in (bytes(blob), b"", b"WP1", b"XXX" + bytes(40)):
        with pytest.raises(C.Illisible):
            C.dechiffrer(mauvais, "c")


@pytest.mark.parametrize("valeur", ["", "   ", "pas-du-base64!!", base64.b64encode(b"court").decode()])
def test_cle_absente_ou_invalide(monkeypatch, valeur):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", valeur)
    with pytest.raises(C.CleAbsente):
        C.chiffrer(b"x", "c")


def test_changer_la_cle_rend_illisible(monkeypatch):
    blob = C.chiffrer(b"x", "c")
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(C.Illisible):
        C.dechiffrer(blob, "c")
