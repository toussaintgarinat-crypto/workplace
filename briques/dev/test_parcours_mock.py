"""Parcours complet via l'API, avec le mock honnête : ouvrir → lancer → diff → jeter.

Prouve l'incrément 1 de bout en bout sans aucun binaire d'agent réel, et que `main` ne bouge
jamais."""
import subprocess

import git_atelier
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _main_files():
    return subprocess.run(["git", "-C", git_atelier.REPO, "ls-tree", "--name-only", "main"],
                          capture_output=True, text=True).stdout


def test_sante_voit_le_filet():
    r = client.get("/sante")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["depot_git"] is True
    assert "factice" in body["agents_disponibles"]  # toujours dispo (mock honnête)


def test_parcours_complet_diff_sans_deploiement():
    # 1) Ouvrir un chantier → worktree + branche neuve.
    #    On force l'agent `factice` : ce test prouve le FILET de façon déterministe et
    #    hors-ligne, sans invoquer un vrai agent (Claude Code/OpenCode peuvent être présents).
    r = client.post("/chantiers", json={"intention": "ajouter une note",
                                         "brique_cible": "mail", "agent": "factice"})
    assert r.status_code == 201, r.text
    ch = r.json()
    assert ch["statut"] == "cree" and ch["branche"].startswith("dev/")
    cid = ch["id"]

    avant = _main_files()

    # 2) Lancer l'agent (aucun binaire réel → mock factice honnête, qui commite)
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 200, r.text
    ch = r.json()
    assert ch["agent"] == "factice" and ch["statut"] == "revue"

    # 3) Diff : la note apparaît, prête à être relue
    r = client.get(f"/chantiers/{cid}/diff")
    assert r.status_code == 200
    d = r.json()
    assert "ATELIER_DEV_NOTE.md" in d["diff"]
    # Chantier ciblant `mail` → la note atterrit dans briques/mail/ (rebuild ciblé possible).
    assert "briques/mail/ATELIER_DEV_NOTE.md" in d["stats"]["fichiers"]

    # 4) La prod (main) n'a PAS bougé pendant tout ça
    assert _main_files() == avant
    assert "ATELIER_DEV_NOTE.md" not in _main_files()

    # 5) Jeter : worktree détruit, chantier marqué jeté
    r = client.delete(f"/chantiers/{cid}")
    assert r.status_code == 200 and r.json()["statut"] == "jete"


def test_intention_vide_refusee():
    r = client.post("/chantiers", json={"intention": "   "})
    assert r.status_code == 422


def test_relancer_chantier_jete_refuse():
    r = client.post("/chantiers", json={"intention": "x"})
    cid = r.json()["id"]
    client.delete(f"/chantiers/{cid}")
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 409
