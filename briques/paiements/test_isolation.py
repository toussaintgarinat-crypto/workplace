"""Cloisonnement multi-tenant : une solution ne voit JAMAIS les comptes/paiements d'une autre.
La clé API identifie la solution (par empreinte) ; fail-closed (404, on ne révèle pas l'existence)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _h(cle):
    return {"X-API-Key": cle}


def test_un_compte_est_invisible_pour_une_autre_solution():
    # Solution A crée un compte connecté.
    a = client.post("/comptes-connectes", headers=_h("solution-A"), json={"nom": "Resto A"}).json()
    # Solution B ne le voit pas (liste vide + lecture 404).
    assert client.get("/comptes-connectes", headers=_h("solution-B")).json()["comptes"] == []
    assert client.get(f"/comptes-connectes/{a['id']}", headers=_h("solution-B")).status_code == 404
    # …mais A le voit bien.
    assert client.get(f"/comptes-connectes/{a['id']}", headers=_h("solution-A")).status_code == 200


def test_paiement_sur_le_compte_d_autrui_refuse():
    a = client.post("/comptes-connectes", headers=_h("solution-A"), json={"nom": "Resto A"}).json()
    # B tente d'encaisser sur le compte de A → compte introuvable pour B (404).
    r = client.post("/paiements", headers=_h("solution-B"),
                    json={"compte_connecte_id": a["id"], "montant_cents": 1000})
    assert r.status_code == 404
