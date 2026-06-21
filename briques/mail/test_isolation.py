"""Cloisonnement multi-tenant : deux clés API = deux boîtes étanches.

Sans `API_KEYS` (retiré par conftest), le tenant est l'empreinte de la clé présentée : deux
clés différentes ⇒ deux tenants ⇒ caches et brouillons invisibles l'un pour l'autre (fail-closed,
404 plutôt que 403 — on ne révèle pas l'existence)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
A = {"X-API-Key": "cle-alice"}
B = {"X-API-Key": "cle-bob"}


def test_message_d_un_tenant_invisible_pour_l_autre():
    msg_a = client.get("/mail", headers=A).json()["messages"][0]
    # Le même id sous une autre clé n'existe pas (cache propre à chaque tenant).
    assert client.get(f"/mail/{msg_a['id']}", headers=B).status_code == 404
    # …mais existe bien pour son propriétaire.
    assert client.get(f"/mail/{msg_a['id']}", headers=A).status_code == 200


def test_brouillon_d_un_tenant_invisible_pour_l_autre():
    msg_a = client.get("/mail", headers=A).json()["messages"][0]
    cree = client.post("/mail/brouillon", json={"message_id": msg_a["id"]}, headers=A).json()
    ids_b = [b["id"] for b in client.get("/brouillons", headers=B).json()["brouillons"]]
    assert cree["brouillon"]["id"] not in ids_b
    ids_a = [b["id"] for b in client.get("/brouillons", headers=A).json()["brouillons"]]
    assert cree["brouillon"]["id"] in ids_a


def test_brouillon_sur_message_d_un_autre_tenant_404():
    msg_a = client.get("/mail", headers=A).json()["messages"][0]
    # Bob ne peut pas répondre à un message qu'il ne possède pas.
    r = client.post("/mail/brouillon", json={"message_id": msg_a["id"]}, headers=B)
    assert r.status_code == 404
