"""Formats / tailles d'un plat (ex. bière 25cl/50cl/1L/girafe 2,5L).

Prouve qu'un plat peut porter des formats (prix par taille), que la carte les expose, que le
prix de carte = « à partir de » (le moins cher), et surtout que la COMMANDE d'un format
enregistre le bon prix et le bon libellé (snapshot) côté addition."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _resto():
    email = f"fmt-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Bar"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


FORMATS = [{"taille": "25cl", "prix_cents": 350}, {"taille": "50cl", "prix_cents": 700},
           {"taille": "1L", "prix_cents": 1300}, {"taille": "Girafe 2,5L", "prix_cents": 2800}]


def test_creer_plat_avec_formats():
    s, resto = _resto()
    p = client.post(f"/restaurants/{resto}/plats", headers=_h(s),
                    json={"nom": "Carlsberg", "categorie": "Bières", "formats": FORMATS}).json()
    assert len(p["formats"]) == 4
    # Prix de carte = « à partir de » = le moins cher (25cl).
    assert p["prix_cents"] == 350
    # La carte publique (vue client) expose bien les formats.
    pub = client.get(f"/t/{_code(s, resto)}").json()["carte"]
    assert pub[0]["formats"][3]["taille"] == "Girafe 2,5L"


def _code(s, resto):
    t = client.post(f"/restaurants/{resto}/tables", headers=_h(s), json={"numero": "1"}).json()
    return t["code"]


def test_commander_un_format_enregistre_prix_et_libelle():
    s, resto = _resto()
    p = client.post(f"/restaurants/{resto}/plats", headers=_h(s),
                    json={"nom": "Colomba", "categorie": "Bières", "formats": FORMATS}).json()
    code = _code(s, resto)
    # Le client commande une Girafe 2,5L.
    client.post(f"/t/{code}/commander",
                json={"convive": "Thomas", "plats": [{"plat_id": p["id"], "format": "Girafe 2,5L", "quantite": 1}]})
    add = client.get(f"/t/{code}/addition").json()
    detail = add["convives"][0]["details"][0]
    assert detail["nom_plat"] == "Colomba (Girafe 2,5L)"
    assert detail["prix_cents"] == 2800          # le prix du format choisi, pas le « à partir de »


def test_format_inconnu_retombe_sur_le_premier():
    s, resto = _resto()
    p = client.post(f"/restaurants/{resto}/plats", headers=_h(s),
                    json={"nom": "Kwak", "formats": FORMATS}).json()
    code = _code(s, resto)
    client.post(f"/t/{code}/commander",
                json={"convive": "A", "plats": [{"plat_id": p["id"], "format": "999cl", "quantite": 1}]})
    d = client.get(f"/t/{code}/addition").json()["convives"][0]["details"][0]
    assert d["prix_cents"] == 350 and d["nom_plat"] == "Kwak (25cl)"


def test_maj_formats_puis_retour_prix_unique():
    s, resto = _resto()
    p = client.post(f"/restaurants/{resto}/plats", headers=_h(s),
                    json={"nom": "Triple", "prix_cents": 600}).json()
    assert p["formats"] == []
    maj = client.patch(f"/restaurants/{resto}/plats/{p['id']}", headers=_h(s),
                       json={"formats": FORMATS}).json()
    assert maj["prix_cents"] == 350 and len(maj["formats"]) == 4
    # Liste vide → repasse en prix unique (les formats disparaissent).
    retour = client.patch(f"/restaurants/{resto}/plats/{p['id']}", headers=_h(s),
                          json={"formats": []}).json()
    assert retour["formats"] == []


def test_formats_tolere_prix_en_euros_et_ignore_invalides():
    s, resto = _resto()
    # `prix` en euros + une entrée sans taille (ignorée) + un doublon de taille (ignoré).
    p = client.post(f"/restaurants/{resto}/plats", headers=_h(s), json={
        "nom": "Pression", "formats": [
            {"taille": "25cl", "prix": 3.5}, {"prix_cents": 100},
            {"taille": "25cl", "prix_cents": 999}, {"taille": "50cl", "prix_cents": 700}]}).json()
    tailles = [f["taille"] for f in p["formats"]]
    assert tailles == ["25cl", "50cl"]
    assert p["formats"][0]["prix_cents"] == 350    # 3,5 € → 350 c
