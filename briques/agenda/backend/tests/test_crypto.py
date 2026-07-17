"""Chiffrement au repos des champs (S180) — primitive, clé, enveloppe versionnée."""

from __future__ import annotations

import base64
import hashlib

import pytest

import crypto
from config import settings


def test_chiffrer_dechiffrer_roundtrip():
    token = crypto.chiffrer("Rendez-vous médecin 14h")
    assert isinstance(token, str)
    assert "médecin" not in token  # bien chiffré
    assert crypto.dechiffrer(token) == "Rendez-vous médecin 14h"


def test_enveloppe_versionnee():
    token = crypto.chiffrer("x")
    blob = base64.b64decode(token)
    assert blob[0] == crypto.VERSION  # octet de version en tête
    assert len(blob) >= 1 + 12 + 16    # version + nonce + tag GCM minimum


def test_nonce_unique_par_appel():
    assert crypto.chiffrer("meme-texte") != crypto.chiffrer("meme-texte")


def test_cle_dediee_prioritaire_sur_repli():
    settings.AGENDA_ENCRYPTION_KEY = "cle-dediee-de-test-32-octets-min-xx"
    attendu = hashlib.sha256(settings.AGENDA_ENCRYPTION_KEY.encode()).digest()
    assert crypto.field_key() == attendu
    settings.AGENDA_ENCRYPTION_KEY = ""


def test_repli_hkdf_distinct_du_coffre():
    """Sans clé dédiée, la clé des champs dérive de VAULT_SECRET mais N'EST PAS
    SHA-256(VAULT_SECRET) (= la clé du coffre OAuth) : usages séparés."""
    settings.AGENDA_ENCRYPTION_KEY = ""
    cle_coffre = hashlib.sha256(settings.VAULT_SECRET.encode()).digest()
    assert crypto.field_key() != cle_coffre
    assert crypto.field_key() == crypto.field_key()  # déterministe


def test_fail_closed_sans_aucune_cle():
    settings.AGENDA_ENCRYPTION_KEY = ""
    ancien = settings.VAULT_SECRET
    settings.VAULT_SECRET = ""
    try:
        with pytest.raises(RuntimeError):
            crypto.chiffrer("x")
    finally:
        settings.VAULT_SECRET = ancien


def test_dechiffrer_mauvaise_cle_leve():
    token = crypto.chiffrer("secret")
    settings.AGENDA_ENCRYPTION_KEY = "une-autre-cle-completement-differente"
    try:
        with pytest.raises(Exception):
            crypto.dechiffrer(token)
    finally:
        settings.AGENDA_ENCRYPTION_KEY = ""
