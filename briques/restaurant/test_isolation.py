"""Frontière multi-tenant : un restaurateur ne touche JAMAIS au restaurant d'un autre.

C'est le test qui prouve la promesse « plusieurs restaurants cloisonnés ». On monte
deux comptes (A et B), chacun avec son resto, et on vérifie que A se heurte à un 404
sur TOUTES les surfaces de B (lecture carte, tables, cuisine, addition, écritures)."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _compte(nom_resto: str):
    email = f"iso-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": nom_resto}).json()
    return r["session"], r["restaurant"]["id"]


def _h(session: str):
    return {"Authorization": f"Bearer {session}"}


def test_un_restaurateur_ne_voit_pas_le_resto_d_un_autre():
    sa, resto_a = _compte("Resto A")
    sb, resto_b = _compte("Resto B")

    # B se crée une carte et une table.
    plat_b = client.post(f"/restaurants/{resto_b}/plats", headers=_h(sb),
                         json={"nom": "Secret B", "prix_cents": 1500}).json()
    table_b = client.post(f"/restaurants/{resto_b}/tables", headers=_h(sb),
                          json={"numero": "1"}).json()

    # A ne voit NI le resto, NI la carte, NI les tables, NI la cuisine de B.
    assert client.get(f"/restaurants/{resto_b}", headers=_h(sa)).status_code == 404
    assert client.get(f"/restaurants/{resto_b}/plats", headers=_h(sa)).status_code == 404
    assert client.get(f"/restaurants/{resto_b}/tables", headers=_h(sa)).status_code == 404
    assert client.get(f"/restaurants/{resto_b}/cuisine", headers=_h(sa)).status_code == 404

    # A ne peut RIEN écrire chez B (créer un plat, modifier celui de B, supprimer la table).
    assert client.post(f"/restaurants/{resto_b}/plats", headers=_h(sa),
                       json={"nom": "intrusion", "prix_cents": 1}).status_code == 404
    assert client.patch(f"/restaurants/{resto_b}/plats/{plat_b['id']}", headers=_h(sa),
                        json={"prix_cents": 1}).status_code == 404
    assert client.delete(f"/restaurants/{resto_b}/tables/{table_b['id']}",
                        headers=_h(sa)).status_code == 404

    # A ne voit que SON resto dans la liste.
    mes = client.get("/restaurants", headers=_h(sa)).json()["restaurants"]
    ids = {r["id"] for r in mes}
    assert resto_a in ids and resto_b not in ids


def test_addition_d_une_table_inaccessible_a_un_autre_compte():
    sa, _ = _compte("Resto A")
    sb, resto_b = _compte("Resto B")
    table_b = client.post(f"/restaurants/{resto_b}/tables", headers=_h(sb),
                          json={"numero": "7"}).json()
    # A tente de lire l'addition d'une table de B → 404.
    assert client.get(f"/restaurants/{resto_b}/tables/{table_b['id']}/addition",
                     headers=_h(sa)).status_code == 404
    # A tente de valider un paiement espèces chez B → 404.
    assert client.post(f"/restaurants/{resto_b}/tables/{table_b['id']}/paiement-especes",
                      headers=_h(sa), json={"convive": "Thomas"}).status_code == 404


def test_ws_cuisine_refuse_un_compte_etranger():
    sa, _ = _compte("Resto A")
    _, resto_b = _compte("Resto B")
    # A ouvre le WS cuisine de B avec SA session → la socket doit se fermer (fail-closed).
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/cuisine/{resto_b}?session={sa}") as ws:
            ws.receive_json()
