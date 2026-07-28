"""Le chiffrement des configurations de source (S214)."""
import base64
import importlib
import json
import os

import pytest

import coffre


def test_aller_retour():
    config = {"repository": "toussaintgarinat-crypto/workplace", "credentials": {"personal_access_token": "ghp_secret"}}
    assert coffre.dechiffrer(coffre.chiffrer(config)) == config


def test_le_chiffre_ne_contient_pas_le_secret_en_clair():
    """Le test qui compte : un `grep` sur le fichier SQLite ne doit rien rendre."""
    jeton = coffre.chiffrer({"token": "ghp_UN_SECRET_RECONNAISSABLE"})
    assert "ghp_UN_SECRET_RECONNAISSABLE" not in jeton
    assert b"ghp_UN_SECRET_RECONNAISSABLE" not in base64.b64decode(jeton)


def test_deux_chiffrements_du_meme_clair_different():
    """Nonce aléatoire : sinon deux sources au même jeton seraient reconnaissables à l'œil."""
    config = {"token": "identique"}
    assert coffre.chiffrer(config) != coffre.chiffrer(config)


def test_enveloppe_versionnee():
    """Le premier octet est la version — réservé pour une rotation de clé."""
    assert base64.b64decode(coffre.chiffrer({"a": 1}))[0] == coffre.VERSION


def test_masquer_rend_les_cles_pas_les_valeurs():
    masque = coffre.masquer({"token": "ghp_secret", "org": "", "repo": "workplace"})
    assert masque == {"token": "(renseigné)", "org": "(vide)", "repo": "(renseigné)"}
    assert "ghp_secret" not in json.dumps(masque)


def test_sans_aucune_cle_on_refuse_plutot_que_d_ecrire_en_clair(monkeypatch):
    """Fail-closed : pas de repli silencieux en clair si le coffre n'est pas configuré."""
    monkeypatch.delenv("CONNECTEURS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("VAULT_SECRET", raising=False)
    with pytest.raises(coffre.SecretIndisponible):
        coffre.chiffrer({"token": "x"})


def test_repli_hkdf_sur_vault_secret_et_sel_distinct_de_l_agenda(monkeypatch):
    """Sans clé dédiée, la clé dérive de VAULT_SECRET — mais PAS avec le même sel que
    l'agenda : une racine partagée ne doit jamais produire la même clé pour deux briques."""
    monkeypatch.delenv("CONNECTEURS_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("VAULT_SECRET", "racine-commune-du-coffre")
    cle_connecteurs = coffre.cle()
    assert len(cle_connecteurs) == 32

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    cle_agenda = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"agenda-fields-v1",
                      info=b"chiffrement-champs-agenda").derive(b"racine-commune-du-coffre")
    assert cle_connecteurs != cle_agenda


def test_la_cle_dediee_prime_sur_vault_secret(monkeypatch):
    monkeypatch.setenv("VAULT_SECRET", "racine")
    monkeypatch.setenv("CONNECTEURS_ENCRYPTION_KEY", "dediee")
    avec_dediee = coffre.cle()
    monkeypatch.delenv("CONNECTEURS_ENCRYPTION_KEY")
    assert avec_dediee != coffre.cle()


def test_secrets_stdlib_n_est_pas_masque():
    """Ce module s'est d'abord appelé `secrets.py` — il masquait alors le module stdlib du
    même nom pour tout ce qui partage le sys.path de la brique. Le renommage en `coffre.py`
    est tenu par ce test, pas par la mémoire."""
    stdlib = importlib.import_module("secrets")
    assert hasattr(stdlib, "token_hex"), "le `secrets` importé n'est pas celui de la stdlib"
    assert not os.path.exists(os.path.join(os.path.dirname(__file__), "secrets.py"))
