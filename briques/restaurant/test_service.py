"""Chemin de SERVICE : la carte pilotée par le Cœur (capacités MCP), clé de service.

Prouve que le Cœur (clé RESTAURANT_KEY) peut lire/écrire la carte d'un restaurant SANS le
mot de passe du restaurateur, que c'est fail-closed (sans clé / mauvaise clé → refus), et
que le résultat est cohérent avec la vue restaurateur classique."""
import os
import uuid

from fastapi.testclient import TestClient

os.environ["RESTAURANT_KEY"] = "cle-service-de-test"   # lu paresseusement par service_ok

import main

client = TestClient(main.app)
CLE = {"X-API-Key": "cle-service-de-test"}


def _resto():
    email = f"svc-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Chez Service"}).json()
    return r["session"], r["restaurant"]["id"]


def test_service_exige_la_cle():
    _, resto = _resto()
    # Sans clé → 401 ; mauvaise clé → 401 ; bonne clé → 200.
    assert client.get(f"/service/restaurants/{resto}/plats").status_code == 401
    assert client.get(f"/service/restaurants/{resto}/plats",
                      headers={"X-API-Key": "fausse"}).status_code == 401
    assert client.get(f"/service/restaurants/{resto}/plats", headers=CLE).status_code == 200


def test_service_lister_restaurants_decouverte():
    """S103 : l'assistant découvre les ids des restaurants sans qu'on les fournisse.
    Fail-closed (clé requise) et le resto créé apparaît bien dans la liste."""
    _, resto = _resto()
    assert client.get("/service/restaurants").status_code == 401
    assert client.get("/service/restaurants", headers={"X-API-Key": "fausse"}).status_code == 401
    r = client.get("/service/restaurants", headers=CLE)
    assert r.status_code == 200
    restos = r.json()["restaurants"]
    ids = {x["id"] for x in restos}
    assert resto in ids
    # Chaque entrée porte au moins l'id et le nom (contexte pour l'assistant).
    cible = next(x for x in restos if x["id"] == resto)
    assert cible["nom"] == "Chez Service"


def test_service_cycle_de_vie_d_un_plat():
    session, resto = _resto()
    # Le Cœur ajoute un plat (action).
    p = client.post(f"/service/restaurants/{resto}/plats", headers=CLE,
                    json={"nom": "Velouté", "prix_cents": 850, "categorie": "Entrées"})
    assert p.status_code == 200
    pid = p.json()["id"]

    # Il apparaît côté SERVICE et côté RESTAURATEUR (même donnée, deux portes).
    svc = client.get(f"/service/restaurants/{resto}/plats", headers=CLE).json()["plats"]
    resto_vue = client.get(f"/restaurants/{resto}/plats",
                           headers={"Authorization": f"Bearer {session}"}).json()["plats"]
    assert any(x["id"] == pid and x["nom"] == "Velouté" for x in svc)
    assert any(x["id"] == pid for x in resto_vue)

    # Modifier puis supprimer via le service.
    m = client.patch(f"/service/restaurants/{resto}/plats/{pid}", headers=CLE,
                     json={"prix_cents": 900, "disponible": False})
    assert m.status_code == 200 and m.json()["prix_cents"] == 900 and m.json()["disponible"] is False
    d = client.delete(f"/service/restaurants/{resto}/plats/{pid}", headers=CLE)
    assert d.status_code == 200 and d.json()["supprime"] is True
    restant = client.get(f"/service/restaurants/{resto}/plats", headers=CLE).json()["plats"]
    assert all(x["id"] != pid for x in restant)


def test_service_infos_resto():
    _, resto = _resto()
    r = client.get(f"/service/restaurants/{resto}", headers=CLE)
    assert r.status_code == 200 and r.json()["nom"] == "Chez Service"


def test_service_restaurant_inconnu_404():
    assert client.get(f"/service/restaurants/{uuid.uuid4().hex}/plats",
                      headers=CLE).status_code == 404
    assert client.post(f"/service/restaurants/{uuid.uuid4().hex}/plats", headers=CLE,
                       json={"nom": "fantôme"}).status_code == 404


def test_service_eteint_si_pas_de_cle(monkeypatch):
    # RESTAURANT_KEY absent ⇒ chemin de service ÉTEINT (503), jamais ouvert par défaut.
    monkeypatch.delenv("RESTAURANT_KEY", raising=False)
    _, resto = _resto()
    assert client.get(f"/service/restaurants/{resto}/plats", headers=CLE).status_code == 503
