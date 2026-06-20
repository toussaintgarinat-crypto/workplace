"""S81 — un seul panier mêlant PLUSIEURS convives (« pour qui » par ligne) crée une
commande par convive ; les notes de ligne sont conservées ; le stock reste atomique sur
tout le lot (pas de survente entre convives)."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _resto():
    email = f"multi-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Partage"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def _plat(h, resto, **kw):
    return client.post(f"/restaurants/{resto}/plats", headers=h, json=kw).json()


def test_panier_multi_convive_se_repartit_par_personne():
    session, resto = _resto()
    h = _h(session)
    pizza = _plat(h, resto, nom="Pizza", prix_cents=1400)
    biere = _plat(h, resto, nom="Bière", prix_cents=700)
    cesar = _plat(h, resto, nom="César", prix_cents=1850)
    code = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "7"}).json()["code"]

    # Un SEUL appel, panier mixte : Thomas (pizza+bière) + Sarah (césar, avec note).
    r = client.post(f"/t/{code}/commander", json={"convive": "Thomas", "plats": [
        {"plat_id": pizza["id"], "quantite": 1, "convive": "Thomas"},
        {"plat_id": biere["id"], "quantite": 1, "convive": "Thomas"},
        {"plat_id": cesar["id"], "quantite": 1, "convive": "Sarah", "notes": "sans anchois"},
    ]})
    assert r.status_code == 200
    assert len(r.json()["commandes"]) == 2          # une commande par convive

    etat = client.get(f"/t/{code}/addition").json()
    parts = {c["convive"]: c for c in etat["convives"]}
    assert parts["Thomas"]["du_cents"] == 2100
    assert parts["Sarah"]["du_cents"] == 1850
    # La note de ligne est conservée et remontée dans l'addition.
    assert parts["Sarah"]["details"][0]["notes"] == "sans anchois"


def test_ligne_sans_convive_retombe_sur_le_defaut():
    session, resto = _resto()
    h = _h(session)
    cafe = _plat(h, resto, nom="Café", prix_cents=200)
    code = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "1"}).json()["code"]
    client.post(f"/t/{code}/commander", json={"convive": "Léa", "plats": [
        {"plat_id": cafe["id"], "quantite": 2}]})        # pas de convive sur la ligne
    etat = client.get(f"/t/{code}/addition").json()
    assert etat["convives"][0]["convive"] == "Léa"
    assert etat["convives"][0]["du_cents"] == 400


def test_stock_atomique_entre_convives_dans_un_meme_panier():
    session, resto = _resto()
    h = _h(session)
    plat = _plat(h, resto, nom="Dernière part", prix_cents=900, stock=1)
    code = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "9"}).json()["code"]
    # Thomas ET Sarah veulent la même part (stock=1) dans le même envoi : une seule passe.
    r = client.post(f"/t/{code}/commander", json={"convive": "Thomas", "plats": [
        {"plat_id": plat["id"], "quantite": 1, "convive": "Thomas"},
        {"plat_id": plat["id"], "quantite": 1, "convive": "Sarah"},
    ]})
    assert r.status_code == 200
    etat = client.get(f"/t/{code}/addition").json()
    # Une seule part a été servie au total (anti-survente), pour un seul convive.
    assert etat["total_cents"] == 900
    assert plat["id"] in r.json()["ruptures"]
