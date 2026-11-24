"""Clé service-à-service du Cœur vers la brique données.

Contexte : avec AUTH_ENABLED=true la brique exige un jeton Keycloak ; le Cœur (qui lit/écrit
la config ⚙ Cerveau, app `_config_assistant`) n'en a pas et recevait 401 en boucle.
Correctif : en-tête `X-Service-Key` comparé à DONNEES_SERVICE_KEY. Sans clé configurée, ce
chemin est INACTIF (jamais « clé vide = accepté »).
Lancer : `python3 -m pytest test_cle_service.py`.
"""
import pytest
from fastapi.testclient import TestClient

import auth
import main

_BASE = "/apps/_config_assistant/entites/perso/enregistrements"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    main.DB_PATH = str(tmp_path / "donnees.db")
    main._init_db()
    # Auth Keycloak ACTIVE (comme sur le HP) : sans jeton valide → 401.
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "KEYCLOAK_URL", "http://kc.invalide")
    monkeypatch.setattr(auth, "KEYCLOAK_REALM", "forge")
    with TestClient(main.app) as c:
        yield c


def test_sans_cle_ni_jeton_reste_refuse(client, monkeypatch):
    monkeypatch.setattr(auth, "SERVICE_KEY", "secret-coeur")
    assert client.get(_BASE, headers={"X-Org-ID": "o"}).status_code == 401


def test_bonne_cle_service_passe_et_respecte_l_org(client, monkeypatch):
    monkeypatch.setattr(auth, "SERVICE_KEY", "secret-coeur")
    h = {"X-Service-Key": "secret-coeur", "X-Org-ID": "orgA"}
    assert client.post(_BASE, json={"a": 1}, headers=h).status_code == 201
    assert len(client.get(_BASE, headers=h).json()) == 1
    # L'isolation par organisation reste vraie avec la clé de service.
    h2 = {"X-Service-Key": "secret-coeur", "X-Org-ID": "orgB"}
    assert client.get(_BASE, headers=h2).json() == []


def test_mauvaise_cle_refusee(client, monkeypatch):
    monkeypatch.setattr(auth, "SERVICE_KEY", "secret-coeur")
    r = client.get(_BASE, headers={"X-Service-Key": "autre", "X-Org-ID": "o"})
    assert r.status_code == 401


def test_cle_non_configuree_jamais_acceptee(client, monkeypatch):
    # Clé de service absente côté brique : un en-tête vide ou quelconque ne doit rien ouvrir.
    monkeypatch.setattr(auth, "SERVICE_KEY", "")
    assert client.get(_BASE, headers={"X-Service-Key": "", "X-Org-ID": "o"}).status_code == 401
    assert client.get(_BASE, headers={"X-Service-Key": "x", "X-Org-ID": "o"}).status_code == 401


def test_auth_desactivee_inchangee(tmp_path, monkeypatch):
    main.DB_PATH = str(tmp_path / "d.db")
    main._init_db()
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    with TestClient(main.app) as c:
        assert c.get(_BASE).status_code == 200
