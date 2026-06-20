"""Stock & rupture automatique (S80).

Un plat peut porter un stock (unités restantes) décompté ATOMIQUEMENT à chaque commande :
- décompte unité par unité,
- rupture à 0 → le plat disparaît de la carte client (et n'est plus commandable),
- anti-survente : on ne peut jamais commander plus que le stock (fail-closed),
- réapprovisionnement → le plat réapparaît,
- stock illimité par défaut (None) : aucune limite."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _resto():
    email = f"stock-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Chez Stock"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def _plat(h, resto, **champs):
    return client.post(f"/restaurants/{resto}/plats", headers=h, json=champs).json()


def _carte(code):
    return client.get(f"/t/{code}").json()["carte"]


def test_decompte_a_la_commande():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "1"}).json()
    cote = _plat(h, resto, nom="Côte de bœuf", prix_cents=3200, stock=6)
    assert cote["stock"] == 6 and cote["epuise"] is False

    client.post(f"/t/{table['code']}/commander",
                json={"convive": "A", "plats": [{"plat_id": cote["id"], "quantite": 2}]})
    plats = client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"]
    assert next(p for p in plats if p["id"] == cote["id"])["stock"] == 4


def test_rupture_a_zero_retire_le_plat_et_refuse_la_commande():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "2"}).json()
    code = table["code"]
    dessert = _plat(h, resto, nom="Tarte du jour", prix_cents=700, stock=2)

    # Visible au départ.
    assert any(p["id"] == dessert["id"] for p in _carte(code))

    # On épuise le stock (2 unités).
    r = client.post(f"/t/{code}/commander",
                    json={"convive": "B", "plats": [{"plat_id": dessert["id"], "quantite": 2}]})
    assert r.status_code == 200
    assert dessert["id"] in r.json()["ruptures"]

    # Épuisé → hors carte client, et plus commandable (fail-closed → 400).
    assert not any(p["id"] == dessert["id"] for p in _carte(code))
    r2 = client.post(f"/t/{code}/commander",
                     json={"convive": "C", "plats": [{"plat_id": dessert["id"], "quantite": 1}]})
    assert r2.status_code == 400

    # Côté back-office, le plat est marqué épuisé (pas supprimé).
    plats = client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"]
    p = next(p for p in plats if p["id"] == dessert["id"])
    assert p["stock"] == 0 and p["epuise"] is True


def test_anti_survente_la_quantite_ne_descend_jamais_sous_zero():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "3"}).json()
    code = table["code"]
    huitres = _plat(h, resto, nom="Douzaine d'huîtres", prix_cents=2400, stock=1)

    # Deux convives tentent la dernière unité : un seul l'obtient, l'autre est refusé.
    r1 = client.post(f"/t/{code}/commander",
                     json={"convive": "X", "plats": [{"plat_id": huitres["id"], "quantite": 1}]})
    r2 = client.post(f"/t/{code}/commander",
                     json={"convive": "Y", "plats": [{"plat_id": huitres["id"], "quantite": 1}]})
    assert r1.status_code == 200
    assert r2.status_code == 400  # plus rien en stock → commande vide → refusée

    plats = client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"]
    assert next(p for p in plats if p["id"] == huitres["id"])["stock"] == 0


def test_commande_superieure_au_stock_est_refusee_sans_partiel():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "4"}).json()
    code = table["code"]
    plat = _plat(h, resto, nom="Plat rare", prix_cents=1500, stock=3)

    # On demande 5 alors qu'il n'en reste que 3 : la ligne est rejetée en bloc (fail-closed),
    # le stock n'est pas entamé et la commande (vide) est refusée.
    r = client.post(f"/t/{code}/commander",
                    json={"convive": "Z", "plats": [{"plat_id": plat["id"], "quantite": 5}]})
    assert r.status_code == 400
    plats = client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"]
    assert next(p for p in plats if p["id"] == plat["id"])["stock"] == 3


def test_reapprovisionnement_fait_reapparaitre_le_plat():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "5"}).json()
    code = table["code"]
    plat = _plat(h, resto, nom="Soupe", prix_cents=600, stock=1)
    client.post(f"/t/{code}/commander",
                json={"convive": "A", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    assert not any(p["id"] == plat["id"] for p in _carte(code))

    # Réappro à 10 → réapparaît et redevient commandable.
    client.patch(f"/restaurants/{resto}/plats/{plat['id']}", headers=h, json={"stock": 10})
    assert any(p["id"] == plat["id"] for p in _carte(code))


def test_stock_illimite_par_defaut_et_repassage_en_illimite():
    session, resto = _resto()
    h = _h(session)
    table = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "6"}).json()
    code = table["code"]
    cafe = _plat(h, resto, nom="Café", prix_cents=200)   # sans stock → illimité
    assert cafe["stock"] is None and cafe["epuise"] is False

    # 50 cafés ne creusent aucun stock.
    for _ in range(50):
        client.post(f"/t/{code}/commander",
                    json={"convive": "A", "plats": [{"plat_id": cafe["id"], "quantite": 1}]})
    plats = client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"]
    assert next(p for p in plats if p["id"] == cafe["id"])["stock"] is None
    assert any(p["id"] == cafe["id"] for p in _carte(code))

    # On limite à 4 puis on repasse en illimité (stock=null) : le plat n'est plus épuisable.
    client.patch(f"/restaurants/{resto}/plats/{cafe['id']}", headers=h, json={"stock": 4})
    p = next(p for p in client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"] if p["id"] == cafe["id"])
    assert p["stock"] == 4
    client.patch(f"/restaurants/{resto}/plats/{cafe['id']}", headers=h, json={"stock": None})
    p = next(p for p in client.get(f"/restaurants/{resto}/plats", headers=h).json()["plats"] if p["id"] == cafe["id"])
    assert p["stock"] is None
