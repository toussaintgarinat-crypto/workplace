"""Tests — CRUD des profils lecteurs (S231), scopés par identité comme les séries (S187)."""
import json
import os

from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def test_creer_profil_ok():
    r = client.post("/profils", json={"nom": "Fils", "cible": "7-9"})
    assert r.status_code == 200
    body = r.json()
    assert body["nom"] == "Fils" and body["cible"] == "7-9"
    assert body["id"] and body["cree_le"]


def test_creer_profil_cible_inconnue_400():
    r = client.post("/profils", json={"nom": "Fille", "cible": "pas-une-cible"})
    assert r.status_code == 400


def test_creer_profil_nom_vide_422():
    r = client.post("/profils", json={"nom": "   ", "cible": "0-3"})
    assert r.status_code == 422


def test_lister_profils_contient_le_profil_cree():
    r = client.post("/profils", json={"nom": "Lister-moi", "cible": "4-6"})
    pid = r.json()["id"]
    ids = [p["id"] for p in client.get("/profils").json()]
    assert pid in ids


def test_modifier_cible_profil_le_fait_vieillir():
    pid = client.post("/profils", json={"nom": "Grandit", "cible": "0-3"}).json()["id"]
    r = client.patch(f"/profils/{pid}", json={"cible": "4-6"})
    assert r.status_code == 200 and r.json()["cible"] == "4-6"


def test_modifier_cible_inconnue_400():
    pid = client.post("/profils", json={"nom": "X", "cible": "0-3"}).json()["id"]
    r = client.patch(f"/profils/{pid}", json={"cible": "pas-une-cible"})
    assert r.status_code == 400


def test_renommer_profil():
    pid = client.post("/profils", json={"nom": "AncienNom", "cible": "0-3"}).json()["id"]
    r = client.patch(f"/profils/{pid}", json={"nom": "NouveauNom"})
    assert r.status_code == 200 and r.json()["nom"] == "NouveauNom"


def test_supprimer_profil():
    pid = client.post("/profils", json={"nom": "Ephemere", "cible": "0-3"}).json()["id"]
    assert client.delete(f"/profils/{pid}").status_code == 204
    assert client.get("/profils/inexistant-après-suppression").status_code in (404, 405)
    ids = [p["id"] for p in client.get("/profils").json()]
    assert pid not in ids


def test_profil_dautrui_404_en_lecture_modification_suppression(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    pid = client.post("/profils", json={"nom": "DeClaire", "cible": "0-3"},
                       headers=_entetes("claire")).json()["id"]
    entetes_marina = _entetes("marina")
    assert client.patch(f"/profils/{pid}", json={"nom": "Vole"},
                        headers=entetes_marina).status_code == 404
    assert client.delete(f"/profils/{pid}", headers=entetes_marina).status_code == 404
    ids_marina = [p["id"] for p in client.get("/profils", headers=entetes_marina).json()]
    assert pid not in ids_marina
    ids_claire = [p["id"] for p in client.get("/profils", headers=_entetes("claire")).json()]
    assert pid in ids_claire


def test_supprimer_profil_supprime_aussi_son_journal():
    """Fix revue finale : supprimer un profil orphelinait son journal pour toujours."""
    pid = client.post("/profils", json={"nom": "AvecJournal", "cible": "0-3"}).json()["id"]
    S._ajouter_evenement(pid, {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    assert os.path.exists(S._journal_path(pid))
    assert client.delete(f"/profils/{pid}").status_code == 204
    assert os.path.exists(S._journal_path(pid)) is False


def test_lister_profils_exclut_les_fichiers_journal():
    """Fix revue finale : garde le fichier journal hors de GET /profils par son NOM de
    fichier (`-journal.json`), pas par accident de valeur.

    Sans ce durcissement, ce test passait déjà AVANT le fix filename-based, par accident :
    le journal n'a pas de clé `cree_par`, donc l'ancien filtre `p.get("cree_par") != cle`
    l'excluait tout seul (None != "public"). On neutralise cet accident en donnant au
    journal un `cree_par` qui MATCHE l'identité appelante ("public" en mode ouvert sans
    en-têtes, cf. conftest.py API_KEYS="" et main.cle_api) : seul le filtre par nom de
    fichier peut alors encore sauver ce test."""
    pid = client.post("/profils", json={"nom": "Solo", "cible": "0-3"}).json()["id"]
    S._ajouter_evenement(pid, {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    assert os.path.exists(S._journal_path(pid))
    with open(S._journal_path(pid), encoding="utf-8") as f:
        journal = json.load(f)
    journal["cree_par"] = "public"
    with open(S._journal_path(pid), "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    profils = client.get("/profils").json()
    ids = [p["id"] for p in profils]
    assert ids.count(pid) == 1
    assert all(not p["id"].endswith("-journal") for p in profils)
    assert all("evenements" not in p for p in profils)
