"""Cloisonnement par personne (S184) : commandes de mot-clé sur mesure privées, catalogue
partagé. Motif copié de briques/mail/test_isolation.py, adapté à l'identité par X-User-Id
sous une clé de service partagée (ECOUTE_KEY) — pas une clé par tenant."""
import os

import pytest
from fastapi.testclient import TestClient

os.environ["ECOUTE_KEY"] = "cle-coeur-test"

import main  # noqa: E402 (import après avoir posé ECOUTE_KEY)

client = TestClient(main.app)
ALICE = {"X-API-Key": "cle-coeur-test", "X-User-Id": "alice"}
BOB = {"X-API-Key": "cle-coeur-test", "X-User-Id": "bob"}


@pytest.fixture(autouse=True)
def _sans_stripe(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)


def test_sans_cle_commandes_401():
    assert client.get("/commandes").status_code == 401


def test_commande_d_alice_invisible_pour_bob():
    cree = client.post("/commandes", json={"nom_marque": "Acme Alice"}, headers=ALICE).json()
    cid = cree["commande"]["id"]
    assert client.get(f"/commandes/{cid}", headers=BOB).status_code == 404
    assert client.get(f"/commandes/{cid}", headers=ALICE).status_code == 200


def test_liste_des_commandes_filtree_par_personne():
    client.post("/commandes", json={"nom_marque": "Marque Alice"}, headers=ALICE)
    client.post("/commandes", json={"nom_marque": "Marque Bob"}, headers=BOB)
    marques_alice = {c["nom_marque"] for c in client.get("/commandes", headers=ALICE).json()}
    marques_bob = {c["nom_marque"] for c in client.get("/commandes", headers=BOB).json()}
    assert "Marque Alice" in marques_alice and "Marque Alice" not in marques_bob
    assert "Marque Bob" in marques_bob and "Marque Bob" not in marques_alice


def test_bob_ne_peut_pas_payer_la_commande_d_alice():
    cree = client.post("/commandes", json={"nom_marque": "Payer Alice"}, headers=ALICE).json()
    cid = cree["commande"]["id"]
    assert client.post(f"/commandes/{cid}/payer", headers=BOB).status_code == 404


def test_noms_reste_partage_entre_alice_et_bob():
    assert client.get("/noms", headers=ALICE).json() == client.get("/noms", headers=BOB).json()


def test_entrainement_traiter_exige_la_cle_de_service():
    assert client.post("/entrainement/traiter").status_code == 401
    r = client.post("/entrainement/traiter", headers={"X-API-Key": "cle-coeur-test"})
    assert r.status_code == 200
    assert "resume" in r.json()
