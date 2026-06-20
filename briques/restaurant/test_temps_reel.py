"""Temps réel (WebSocket) : la cuisine et la table reçoivent les évènements en direct."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _resto():
    email = f"ws-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "WS Resto"}).json()
    return r["session"], r["restaurant"]["id"]


def test_cuisine_recoit_la_nouvelle_commande_en_direct():
    session, resto = _resto()
    h = {"Authorization": f"Bearer {session}"}
    plat = client.post(f"/restaurants/{resto}/plats", headers=h,
                      json={"nom": "Burger", "prix_cents": 1600}).json()
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "4"}).json()

    with client.websocket_connect(f"/ws/cuisine/{resto}?session={session}") as ws:
        client.post(f"/t/{table['code']}/commander",
                   json={"convive": "Thomas", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
        msg = ws.receive_json()
        assert msg["type"] == "nouvelle_commande"
        assert msg["table_numero"] == "4"
        assert msg["commande"]["convive"] == "Thomas"


def test_table_recoit_le_paiement_en_direct():
    session, resto = _resto()
    h = {"Authorization": f"Bearer {session}"}
    plat = client.post(f"/restaurants/{resto}/plats", headers=h,
                      json={"nom": "Thé", "prix_cents": 300}).json()
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "5"}).json()
    client.post(f"/t/{table['code']}/commander",
               json={"convive": "Sarah", "plats": [{"plat_id": plat["id"], "quantite": 1}]})

    with client.websocket_connect(f"/ws/t/{table['code']}") as ws:
        client.post(f"/t/{table['code']}/payer", json={"convive": "Sarah"})
        msg = ws.receive_json()
        assert msg["type"] == "paiement"
        assert msg["etat"]["reste_cents"] == 0
