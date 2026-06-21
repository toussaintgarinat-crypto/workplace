"""S92 — l'orchestrateur `POST /demander` : pilotage en un geste, gate JAMAIS court-circuité.

Prouve hors-ligne (agent `factice`, plan en repli local) que `/demander` :
  • sans plan → ouvre + code → s'arrête au gate du DIFF (statut `revue`, diff_stats joint) ;
  • avec plan → ouvre + planifie → s'arrête au gate du PLAN (codage verrouillé tant que pas validé) ;
  • ne touche JAMAIS `main` de lui-même (le filet tient) ; intention vide refusée (422).
"""
import subprocess

import git_atelier
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _main_files():
    return subprocess.run(["git", "-C", git_atelier.REPO, "ls-tree", "--name-only", "main"],
                          capture_output=True, text=True).stdout


def test_demander_sans_plan_code_et_sarrete_au_gate_du_diff():
    avant = _main_files()
    r = client.post("/demander", json={"intention": "ajouter une note de pilotage",
                                       "brique_cible": "mail", "agent": "factice"})
    assert r.status_code == 201, r.text
    ch = r.json()
    # Un geste → l'agent a codé : on est au gate du diff, prêt à relire.
    assert ch["statut"] == "revue"
    assert ch["agent"] == "factice" and ch["resume"]
    assert "diff_stats" in ch and ch["diff_stats"]["fichiers"]
    assert "dev_fusionner" in ch["prochaine_etape"]
    # Le filet : `main` n'a pas bougé (rien n'est fusionné sans le gate).
    assert _main_files() == avant

    # Et la fusion reste un geste confirmé à part : sans confirme → 428.
    r = client.post(f"/chantiers/{ch['id']}/fusionner", json={"confirme": False})
    assert r.status_code == 428
    client.delete(f"/chantiers/{ch['id']}")


def test_demander_avec_plan_sarrete_au_gate_du_plan_et_verrouille_le_code():
    r = client.post("/demander", json={"intention": "ajouter un champ téléphone",
                                       "brique_cible": "mail", "agent": "factice",
                                       "plan_requis": True})
    assert r.status_code == 201, r.text
    ch = r.json()
    cid = ch["id"]
    # Avec plan requis : on s'arrête APRÈS la planification, AVANT de coder.
    assert ch["statut"] == "planifie"
    assert ch["plan"] and ch["plan"].get("texte")
    assert "dev_plan_valider" in ch["prochaine_etape"]

    # Le codage est verrouillé tant que le plan n'est pas validé (1er gate du double gate).
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 409

    # On valide le plan (gate humain) → le codage se débloque.
    r = client.post(f"/chantiers/{cid}/plan/valider", json={"confirme": True})
    assert r.status_code == 200
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 200 and r.json()["statut"] == "revue"
    client.delete(f"/chantiers/{cid}")


def test_demander_intention_vide_refusee():
    r = client.post("/demander", json={"intention": "   "})
    assert r.status_code == 422
