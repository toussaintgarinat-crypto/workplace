"""Identité de l'appelant pour ecoute (S184) — motif agenda S182 : cercle privé par personne."""
import pytest
from fastapi import HTTPException

import auth


def test_sans_cle_configuree_repli_perso(monkeypatch):
    monkeypatch.delenv("ECOUTE_KEY", raising=False)
    assert auth.identite(x_api_key=None, authorization=None, x_user_id=None) == "perso"
    assert auth.identite(x_api_key=None, authorization=None, x_user_id="alice") == "alice"


def test_avec_cle_configuree_et_bonne_cle_honore_x_user_id(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    assert auth.identite(x_api_key="cle-coeur", authorization=None, x_user_id="alice") == "alice"
    assert auth.identite(x_api_key="cle-coeur", authorization=None, x_user_id=None) == "perso"


def test_avec_cle_configuree_mauvaise_cle_401(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.identite(x_api_key="mauvaise", authorization=None, x_user_id="alice")
    assert exc.value.status_code == 401


def test_avec_cle_configuree_sans_cle_presentee_401(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.identite(x_api_key=None, authorization=None, x_user_id="alice")
    assert exc.value.status_code == 401


def test_bearer_authorization_accepte(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    assert auth.identite(
        x_api_key=None, authorization="Bearer cle-coeur", x_user_id="bob") == "bob"


def test_service_key_sans_cle_configuree_ouvert(monkeypatch):
    monkeypatch.delenv("ECOUTE_KEY", raising=False)
    auth.service_key(x_api_key=None, authorization=None)  # ne lève pas


def test_service_key_avec_cle_valide_ok(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    auth.service_key(x_api_key="cle-coeur", authorization=None)  # ne lève pas


def test_service_key_avec_mauvaise_cle_401(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.service_key(x_api_key="mauvaise", authorization=None)
    assert exc.value.status_code == 401
