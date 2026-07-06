"""Parcours veille : zones (CRUD + isolation), ingestion idempotente, nouveautés, push."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

CLE = {"X-API-Key": "veilleur-tarn"}


def _creer_zone(nom="Castres", **extra):
    corps = {"nom": nom, "lat": 43.606, "lon": 2.241, "rayon_km": 15, **extra}
    return client.post("/zones", json=corps, headers=CLE)


# ── Zones ────────────────────────────────────────────────────────
def test_creer_zone_par_rayon_puis_lister():
    r = _creer_zone()
    assert r.status_code == 201
    zone = r.json()
    assert zone["lat_min"] < 43.606 < zone["lat_max"]
    assert zone["lon_min"] < 2.241 < zone["lon_max"]
    assert any(z["id"] == zone["id"] for z in
               client.get("/zones", headers=CLE).json()["zones"])


def test_creer_zone_par_bbox():
    r = client.post("/zones", json={"nom": "Tarn", "bbox": "43.4,1.9,43.9,2.6"},
                    headers=CLE)
    assert r.status_code == 201


def test_zone_sans_geometrie_renvoie_400():
    assert client.post("/zones", json={"nom": "Nulle part"},
                       headers=CLE).status_code == 400


def test_zones_isolees_par_tenant():
    autre = {"X-API-Key": "un-autre"}
    ids_vus = {z["id"] for z in client.get("/zones", headers=autre).json()["zones"]}
    ids_moi = {z["id"] for z in client.get("/zones", headers=CLE).json()["zones"]}
    assert not (ids_moi & ids_vus)
    # …et on ne peut pas supprimer la zone d'un autre (404, rien révélé).
    zone_id = next(iter(ids_moi))
    assert client.delete(f"/zones/{zone_id}", headers=autre).status_code == 404


def test_supprimer_sa_zone():
    zone = _creer_zone("Éphémère").json()
    assert client.delete(f"/zones/{zone['id']}", headers=CLE).status_code == 200


# ── Ingestion ────────────────────────────────────────────────────
def test_ingestion_mock_upsert_idempotent(monkeypatch):
    pousses = []
    monkeypatch.setattr(main, "_pousser_connexion", lambda t: pousses.append(t))
    cle = {"X-API-Key": "ingestion-fraiche"}
    client.post("/zones", json={"nom": "Zone", "lat": 43.6, "lon": 2.2, "rayon_km": 10},
                headers=cle)
    premiere = client.post("/ingestion/executer", headers=cle).json()
    assert premiere["fournisseur"] == "mock"
    assert premiere["zones"] == 1 and premiere["nouveaux"] >= 5 and premiere["maj"] == 0
    assert len(pousses) == 1 and "nouvelle(s) entreprise(s)" in pousses[0]
    # Rejouée : le mock est déterministe → tout est déjà connu, 0 nouveau, pas de push.
    seconde = client.post("/ingestion/executer", headers=cle).json()
    assert seconde["nouveaux"] == 0 and seconde["maj"] == premiere["nouveaux"]
    assert len(pousses) == 1
    # La zone porte la trace de la dernière passe.
    zones = client.get("/zones", headers=cle).json()["zones"]
    assert zones[0]["derniere_ingestion"]


def test_ingestion_sans_zone_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(main, "_pousser_connexion",
                        lambda t: (_ for _ in ()).throw(AssertionError("pas de push")))
    res = client.post("/ingestion/executer",
                      headers={"X-API-Key": "personne"}).json()
    assert res == {"zones": 0, "nouveaux": 0, "maj": 0, "fournisseur": "mock"}


def test_push_connexion_absente_reste_silencieux(monkeypatch):
    # La brique connexion n'écoute pas sur ce port : l'ingestion doit réussir quand même.
    monkeypatch.setenv("CONNEXION_URL", "http://127.0.0.1:59999")
    cle = {"X-API-Key": "sans-messagerie"}
    client.post("/zones", json={"nom": "Zone", "lat": 43.6, "lon": 2.2, "rayon_km": 10},
                headers=cle)
    r = client.post("/ingestion/executer", headers=cle)
    assert r.status_code == 200 and r.json()["nouveaux"] >= 5


def test_nouveautes_expose_les_decouvertes():
    cle = {"X-API-Key": "sans-messagerie"}   # réutilise l'ingestion du test précédent
    res = client.get("/nouveautes", params={"jours": 1}, headers=cle).json()
    assert len(res["nouveautes"]) >= 5
    assert all(o["source"] == "simule" for o in res["nouveautes"])
