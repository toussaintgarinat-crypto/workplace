"""Parcours bout-en-bout en mode MOCK honnête (aucun appel réseau) via l'API HTTP."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_config_mock_honnete():
    r = client.get("/config")
    assert r.status_code == 200
    c = r.json()
    assert c["configure"] is False and c["fournisseur"] == "mock"


def test_acheter_numero_puis_sms_puis_appel():
    # 1) acheter un numéro
    r = client.post("/numeros", json={"pays": "FR"})
    assert r.status_code == 201, r.text
    num = r.json()
    assert num["mode"] == "mock" and num["numero"].startswith("+")
    emetteur = num["numero"]

    # 2) envoyer un SMS depuis ce numéro
    r = client.post("/sms", json={"de": emetteur, "vers": "+33698765432", "corps": "Bonjour !"})
    assert r.status_code == 201, r.text
    sms = r.json()
    assert sms["statut"] == "envoye" and sms["mode"] == "mock" and sms["sens"] == "sortant"

    # 3) passer un appel depuis ce numéro
    r = client.post("/appels", json={"de": emetteur, "vers": "+33698765432",
                                     "message": "Rappelez-moi"})
    assert r.status_code == 201, r.text
    appel = r.json()
    assert appel["statut"] == "termine" and appel["mode"] == "mock"

    # 4) les historiques contiennent bien ce qu'on a fait
    assert any(m["id"] == sms["id"] for m in client.get("/sms").json()["messages"])
    assert any(a["id"] == appel["id"] for a in client.get("/appels").json()["appels"])


def test_sms_depuis_numero_non_possede_refuse():
    r = client.post("/sms", json={"de": "+33600000000", "vers": "+33698765432", "corps": "x"})
    assert r.status_code == 409


def test_numero_destinataire_invalide_refuse():
    r = client.post("/numeros", json={"pays": "FR"})
    emetteur = r.json()["numero"]
    r = client.post("/sms", json={"de": emetteur, "vers": "0612345678", "corps": "x"})
    assert r.status_code == 400


def test_webhook_non_configure_refuse():
    # Sans TWILIO_AUTH_TOKEN (mode mock), on ne peut pas vérifier la signature → 503.
    r = client.post("/webhooks/twilio", data={"From": "+33611112222", "Body": "salut"})
    assert r.status_code == 503
