"""Parcours bout-en-bout : carte → QR → commande par convive → addition partagée → paiement.

Reproduit l'exemple de l'idée (Table 4 : Thomas, Sarah, Lucas), et vérifie que le
« reste à payer » de la table descend au fur et à mesure des règlements."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _resto():
    email = f"parc-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Banc d'Essai"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def test_parcours_complet_addition_partagee():
    session, resto = _resto()
    h = _h(session)

    # 1) Le restaurateur compose sa carte.
    pizza = client.post(f"/restaurants/{resto}/plats", headers=h,
                        json={"nom": "Pizza Reine", "prix_cents": 1400}).json()
    biere = client.post(f"/restaurants/{resto}/plats", headers=h,
                       json={"nom": "Bière IPA", "prix_cents": 700}).json()
    cesar = client.post(f"/restaurants/{resto}/plats", headers=h,
                       json={"nom": "Salade César", "prix_cents": 1850}).json()

    # 2) Il crée la Table 4 → un code (QR).
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "4"}).json()
    code = table["code"]

    # 3) Côté client : le QR ouvre la carte publique (3 plats disponibles).
    vue = client.get(f"/t/{code}").json()
    assert vue["table"]["numero"] == "4"
    assert len(vue["carte"]) == 3

    # 4) Thomas commande pizza + bière ; Sarah commande la salade.
    client.post(f"/t/{code}/commander", json={
        "convive": "Thomas", "plats": [{"plat_id": pizza["id"], "quantite": 1},
                                       {"plat_id": biere["id"], "quantite": 1}]})
    client.post(f"/t/{code}/commander", json={
        "convive": "Sarah", "plats": [{"plat_id": cesar["id"], "quantite": 1}]})

    # 5) Addition de la table : Thomas doit 21,00 €, Sarah 18,50 €, total 39,50 €.
    etat = client.get(f"/t/{code}/addition").json()
    parts = {c["convive"]: c for c in etat["convives"]}
    assert parts["Thomas"]["du_cents"] == 2100
    assert parts["Sarah"]["du_cents"] == 1850
    assert etat["total_cents"] == 3950
    assert etat["reste_cents"] == 3950

    # 6) Thomas paie sa part en ligne (mock) → son reste tombe à 0, table = 18,50 € restants.
    pay = client.post(f"/t/{code}/payer", json={"convive": "Thomas"}).json()
    assert pay["demo"] is True
    assert pay["paiement"]["montant_cents"] == 2100
    assert pay["etat"]["reste_cents"] == 1850

    # 7) Re-payer Thomas ne fait rien (déjà réglé) → 400.
    assert client.post(f"/t/{code}/payer", json={"convive": "Thomas"}).status_code == 400

    # 8) Sarah paie au comptoir en espèces : le restaurateur valide → reste table = 0.
    esp = client.post(f"/restaurants/{resto}/tables/{table['id']}/paiement-especes",
                     headers=h, json={"convive": "Sarah"}).json()
    assert esp["paiement"]["moyen"] == "especes"
    assert esp["etat"]["reste_cents"] == 0


def test_rupture_de_stock_retire_le_plat_de_la_carte_client():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "2"}).json()
    saumon = client.post(f"/restaurants/{resto}/plats", headers=h,
                        json={"nom": "Saumon", "prix_cents": 2200}).json()

    # Présent au départ.
    assert any(p["nom"] == "Saumon" for p in client.get(f"/t/{table['code']}").json()["carte"])

    # Rupture : le restaurateur bascule la dispo.
    client.patch(f"/restaurants/{resto}/plats/{saumon['id']}", headers=h, json={"disponible": False})

    # Disparu de la carte client → impossible à commander.
    assert not any(p["nom"] == "Saumon" for p in client.get(f"/t/{table['code']}").json()["carte"])
    r = client.post(f"/t/{table['code']}/commander",
                   json={"convive": "X", "plats": [{"plat_id": saumon["id"], "quantite": 1}]})
    assert r.status_code == 400


def test_qr_table_genere_un_svg_avec_url_client():
    import pytest
    pytest.importorskip("segno")
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "3"}).json()
    r = client.get(f"/restaurants/{resto}/tables/{table['id']}/qr.svg", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text
    assert table["code"] in r.headers["x-url-client"]


def test_prix_fige_au_moment_de_la_commande():
    # Si le restaurateur change le prix APRÈS la commande, l'addition du convive ne bouge pas.
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "9"}).json()
    cafe = client.post(f"/restaurants/{resto}/plats", headers=h,
                      json={"nom": "Café", "prix_cents": 200}).json()
    client.post(f"/t/{table['code']}/commander",
               json={"convive": "Lucas", "plats": [{"plat_id": cafe["id"], "quantite": 2}]})
    client.patch(f"/restaurants/{resto}/plats/{cafe['id']}", headers=h, json={"prix_cents": 999})
    etat = client.get(f"/t/{table['code']}/addition").json()
    assert etat["convives"][0]["du_cents"] == 400   # 2 × 200, pas 2 × 999
