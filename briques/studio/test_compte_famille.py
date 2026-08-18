"""Tests — nom de famille cosmétique par compte (V1 saga familiale).

Ce n'est PAS l'entité `Famille` écartée par l'ADR 2026-08-18 (aucune donnée d'enfant
ici) — juste une étiquette d'affichage, scopée comme le reste par `cree_par`/`cle_api`."""
import os

import studio as A
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_compte_path_hache_lidentite():
    p1 = A._compte_path("cle-secrete-abc")
    p2 = A._compte_path("cle-secrete-abc")
    assert p1 == p2
    assert "cle-secrete-abc" not in p1
    assert os.path.dirname(p1) == A.COMPTES_DIR


def test_load_compte_absent_renvoie_nom_famille_none():
    assert A._load_compte("compte-inexistant") == {"nom_famille": None}


def test_save_puis_load_roundtrip():
    A._save_compte("cle-x", {"nom_famille": "Famille Martin"})
    assert A._load_compte("cle-x") == {"nom_famille": "Famille Martin"}


def test_get_famille_par_defaut():
    r = client.get("/famille", headers={"X-API-Key": "test-famille-defaut"})
    assert r.status_code == 200
    assert r.json() == {"nom_famille": None}


def test_patch_puis_get_roundtrip():
    entetes = {"X-API-Key": "test-famille-roundtrip"}
    r = client.patch("/famille", json={"nom_famille": "Famille Martin"}, headers=entetes)
    assert r.status_code == 200
    assert r.json() == {"nom_famille": "Famille Martin"}
    assert client.get("/famille", headers=entetes).json() == {"nom_famille": "Famille Martin"}


def test_famille_isolee_par_identite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire-famille"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina-famille"}
    client.patch("/famille", json={"nom_famille": "Famille Claire"}, headers=entetes_claire)
    assert client.get("/famille", headers=entetes_marina).json() == {"nom_famille": None}
