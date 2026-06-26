"""Cloisonnement multi-tenant : une solution ne voit pas les numéros/messages d'une autre."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

A = {"X-API-Key": "cle-solution-A"}
B = {"X-API-Key": "cle-solution-B"}


def test_numeros_et_sms_cloisonnes_par_cle():
    # Solution A achète un numéro et envoie un SMS.
    num_a = client.post("/numeros", json={"pays": "FR"}, headers=A).json()
    client.post("/sms", json={"de": num_a["numero"], "vers": "+33698765432", "corps": "à A"},
                headers=A)

    # B ne voit ni le numéro ni le SMS de A.
    assert client.get("/numeros", headers=B).json()["numeros"] == []
    assert client.get("/sms", headers=B).json()["messages"] == []

    # B ne peut pas émettre depuis le numéro de A (pas possédé par B) → 409.
    r = client.post("/sms", json={"de": num_a["numero"], "vers": "+33698765432", "corps": "vol"},
                    headers=B)
    assert r.status_code == 409

    # A, lui, retrouve bien son numéro et son SMS.
    assert any(n["numero"] == num_a["numero"] for n in client.get("/numeros", headers=A).json()["numeros"])
    assert len(client.get("/sms", headers=A).json()["messages"]) >= 1
