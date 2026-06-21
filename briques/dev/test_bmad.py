"""S88 — flux BMAD léger de bout en bout via l'API : le PLAN d'abord, double gate.

On prouve le DOUBLE gate : (1) le codage est verrouillé tant que le plan n'est pas validé ;
(2) le plan validé est injecté à l'agent codeur (la story porte le contexte). Et la rétrocompat :
sans `plan_requis`, le flux direct `cree → en_cours` de S86 est inchangé."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_flux_bmad_plan_avant_code():
    # 1) Chantier BMAD (plan requis) → reste en `cree`.
    r = client.post("/chantiers", json={"intention": "ajouter un champ reference",
                                        "brique_cible": "mail", "agent": "factice",
                                        "plan_requis": True})
    assert r.status_code == 201, r.text
    ch = r.json()
    cid = ch["id"]
    assert ch["statut"] == "cree" and ch["plan_requis"] is True

    # 2) Coder AVANT le plan → verrouillé (409) : tout l'intérêt du « plan d'abord ».
    assert client.post(f"/chantiers/{cid}/lancer").status_code == 409

    # 3) Planifier → plan structuré (mini-PRD + stories + domaine), statut `planifie`.
    r = client.post(f"/chantiers/{cid}/planifier", json={"lang": "fr"})
    assert r.status_code == 200, r.text
    ch = r.json()
    assert ch["statut"] == "planifie" and ch["plan_valide"] is False
    assert ch["plan"]["prd"] and ch["plan"]["stories"] and ch["plan"]["domaine"]

    # 4) Toujours verrouillé tant que le plan n'est pas VALIDÉ.
    assert client.post(f"/chantiers/{cid}/lancer").status_code == 409

    # 5) Valider sans confirmation → 428 (1er gate du double gate).
    assert client.post(f"/chantiers/{cid}/plan/valider", json={"confirme": False}).status_code == 428

    # 6) Valider le plan (gate) → débloque le codage.
    r = client.post(f"/chantiers/{cid}/plan/valider", json={"confirme": True})
    assert r.status_code == 200 and r.json()["plan_valide"] is True

    # 7) Coder → OK, et le plan validé est INJECTÉ à l'agent (la note factice le porte).
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 200 and r.json()["statut"] == "revue"
    d = client.get(f"/chantiers/{cid}/diff").json()
    assert "Plan validé suivi" in d["diff"]

    client.delete(f"/chantiers/{cid}")


def test_flux_direct_sans_plan_inchange():
    # Rétrocompat S86 : sans `plan_requis`, on code directement (cree → en_cours → revue).
    r = client.post("/chantiers", json={"intention": "petit ajout", "agent": "factice"})
    cid = r.json()["id"]
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 200 and r.json()["statut"] == "revue"
    client.delete(f"/chantiers/{cid}")


def test_planifier_refuse_une_fois_le_code_commence():
    r = client.post("/chantiers", json={"intention": "encore", "agent": "factice"})
    cid = r.json()["id"]
    client.post(f"/chantiers/{cid}/lancer")  # passe en revue
    # On ne planifie qu'AVANT de coder.
    assert client.post(f"/chantiers/{cid}/planifier").status_code == 409
    client.delete(f"/chantiers/{cid}")


def test_valider_sans_plan_refuse():
    r = client.post("/chantiers", json={"intention": "rien", "agent": "factice"})
    cid = r.json()["id"]  # état `cree`, aucun plan
    assert client.post(f"/chantiers/{cid}/plan/valider", json={"confirme": True}).status_code == 409
    client.delete(f"/chantiers/{cid}")
