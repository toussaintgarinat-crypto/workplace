"""Parcours complet en mode MOCK honnête (aucune clé Stripe) : config → créer un vendeur →
onboarding → encaisser avec commission → rembourser. Plus les garde-fous (encaisser avant
onboarding, double remboursement, webhook non signé)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
H = {"X-API-Key": "solution-resto"}


def _compte():
    return client.post("/comptes-connectes", headers=H, json={"nom": "Le Banc d'Essai"}).json()


def test_config_est_mock_sans_cle():
    c = client.get("/config", headers=H).json()
    assert c["configure"] is False and c["fournisseur"] == "mock"


def test_compte_naît_incomplet_et_ne_peut_pas_encore_encaisser():
    compte = _compte()
    assert compte["statut"] == "incomplet"
    vu = client.get(f"/comptes-connectes/{compte['id']}", headers=H).json()
    assert vu["peut_encaisser"] is False
    # Encaisser avant la fin de l'onboarding → refus 409.
    r = client.post("/paiements", headers=H,
                    json={"compte_connecte_id": compte["id"], "montant_cents": 5000})
    assert r.status_code == 409


def test_onboarding_puis_encaissement_avec_commission_puis_remboursement():
    compte = _compte()
    # Lien d'onboarding (mock → page interne).
    lien = client.post(f"/comptes-connectes/{compte['id']}/onboarding", headers=H).json()
    assert lien["mode"] == "mock" and f"/demo/onboarding/{compte['id']}" in lien["url"]
    # « Visite » de la page d'onboarding mock → le compte s'active.
    assert client.get(f"/demo/onboarding/{compte['id']}").status_code == 200
    vu = client.get(f"/comptes-connectes/{compte['id']}", headers=H).json()
    assert vu["statut"] == "actif" and vu["peut_encaisser"] is True

    # Encaissement 50,00 € avec 2,5 % de commission plateforme.
    p = client.post("/paiements", headers=H, json={
        "compte_connecte_id": compte["id"], "montant_cents": 5000,
        "commission_bps": 250, "description": "Table 7"}).json()
    assert p["statut"] == "paye" and p["mode"] == "mock"
    assert p["montant_cents"] == 5000 and p["commission_cents"] == 125 and p["net_cents"] == 4875

    # Remboursement → état remboursé ; un 2ᵉ remboursement est refusé (transition gardée).
    r = client.post(f"/paiements/{p['id']}/rembourser", headers=H)
    assert r.status_code == 200 and r.json()["statut"] == "rembourse"
    assert client.post(f"/paiements/{p['id']}/rembourser", headers=H).status_code == 409


def test_montant_nul_refuse():
    compte = _compte()
    client.get(f"/demo/onboarding/{compte['id']}")
    r = client.post("/paiements", headers=H,
                    json={"compte_connecte_id": compte["id"], "montant_cents": 0})
    assert r.status_code == 400


def test_webhook_non_signe_est_refuse():
    # Sans STRIPE_WEBHOOK_SECRET, on ne traite aucun webhook (503, pas de trou de sécurité).
    r = client.post("/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "x"})
    assert r.status_code == 503
