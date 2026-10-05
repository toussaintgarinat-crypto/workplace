"""Garde de la brique dev sur TOUTES les routes (revue S240, C-B).

La brique monte le dépôt Workplace en écriture et le socket Docker : un appel non
authentifié = exécution arbitraire sur l'hôte. Avant S240, `DEV_KEY` vide laissait tout
ouvert, et même avec une clé, l'IDE SpearCode (`/ide/*` : écrire, exécuter des fichiers)
n'avait AUCUNE garde. Désormais :
- `DEV_KEY` posée → exigée sur toute route sauf `/sante` (sonde Docker) ;
- `DEV_KEY` vide + `AUTH_ENABLED=true` (stack Workplace authentifiée) → tout est refusé
  (503, fail closed) sauf `/sante` ;
- `DEV_KEY` vide + auth coupée → atelier local ouvert (comportement historique, tests).
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

ROUTES = [("GET", "/chantiers"), ("PUT", "/ide/file"), ("POST", "/ide/run"),
          ("GET", "/ide/file"), ("GET", "/ide/tree"), ("POST", "/demander"), ("GET", "/skills")]


@pytest.fixture
def cle(monkeypatch):
    monkeypatch.setenv("DEV_KEY", "cle-dev-test")
    monkeypatch.delenv("AUTH_ENABLED", raising=False)


@pytest.mark.parametrize("methode,chemin", ROUTES)
def test_cle_exigee_partout_y_compris_ide(cle, methode, chemin):
    r = client.request(methode, chemin, json={})
    assert r.status_code == 401, (methode, chemin)


def test_bonne_cle_passe(cle):
    r = client.get("/ide/tree", headers={"X-API-Key": "cle-dev-test"})
    assert r.status_code != 401


def test_sante_reste_ouverte(cle):
    assert client.get("/sante").status_code == 200


@pytest.mark.parametrize("methode,chemin", ROUTES)
def test_sans_cle_avec_auth_workplace_fail_closed(monkeypatch, methode, chemin):
    monkeypatch.delenv("DEV_KEY", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    r = client.request(methode, chemin, json={}, headers={"X-API-Key": "nimporte"})
    assert r.status_code == 503
    assert client.get("/sante").status_code == 200


def test_sans_cle_sans_auth_atelier_local_ouvert(monkeypatch):
    monkeypatch.delenv("DEV_KEY", raising=False)
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    assert client.get("/ide/health").status_code == 200
