"""Parcours veille : zones (CRUD + isolation), ingestion idempotente, nouveautés, push."""
from fastapi.testclient import TestClient

import geographie
import main

client = TestClient(main.app)

CLE = {"X-API-Key": "veilleur-tarn"}


# ── Géographie mock ──────────────────────────────────────────────
class _FauxGeoAPI:
    """Simule geo.api.gouv.fr : CP « 11000 » → Carcassonne."""
    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        import types
        if params.get("codePostal") == "11000":
            corps = [{"code": "11069", "nom": "Carcassonne",
                      "contour": {"type": "Polygon",
                                  "coordinates": [[[2.35, 43.20], [2.36, 43.20],
                                                   [2.36, 43.21], [2.35, 43.21], [2.35, 43.20]]]}}]
        else:
            corps = []
        return types.SimpleNamespace(status_code=200, json=lambda: corps,
                                     raise_for_status=lambda: None)


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


def test_zone_porte_son_filtre_naf():
    r = client.post("/zones", json={"nom": "Restos Castres", "naf": "56.10A",
                                    "lat": 43.606, "lon": 2.241, "rayon_km": 15},
                    headers=CLE)
    assert r.status_code == 201 and r.json()["naf"] == "56.10A"


def test_fournisseur_reel_ignore_les_zones_sans_naf(monkeypatch):
    """En réel, une zone sans NAF n'est PAS énumérable (cap API) : ignorée avec un
    avertissement honnête, sans aucun appel réseau."""
    monkeypatch.setenv("GEO_FOURNISSEUR", "reel")
    monkeypatch.setattr(
        main.fournisseurs.RechercheEntreprises, "entreprises_recentes",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("appel réseau interdit")))
    cle = {"X-API-Key": "reel-sans-naf"}
    client.post("/zones", json={"nom": "Sans filtre", "lat": 43.6, "lon": 2.2,
                                "rayon_km": 10}, headers=cle)
    res = client.post("/ingestion/executer", headers=cle).json()
    assert res["nouveaux"] == 0 and res["fournisseur"] == "recherche-entreprises"
    assert len(res["avertissements"]) == 1 and "NAF" in res["avertissements"][0]


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
    assert res == {"zones": 0, "nouveaux": 0, "maj": 0, "fournisseur": "mock",
                   "fournisseur_logements": "mock-logements", "avertissements": []}


def test_ingestion_traite_zone_logement_avec_son_propre_fournisseur(monkeypatch):
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    cle = {"X-API-Key": "ingestion-logements"}
    client.post("/zones", json={"nom": "Passoires", "type": "logement",
                                "communes": ["11000"],
                                "parametres": {"grades_dpe": ["E", "F", "G"]}},
                headers=cle)
    res = client.post("/ingestion/executer", headers=cle).json()
    assert res["fournisseur"] == "mock"                  # entreprises : inchangé
    assert res["fournisseur_logements"] == "mock-logements"
    assert res["nouveaux"] >= 5
    objets = client.get("/objets", params={"bbox": "43.0,2.0,43.5,2.5"},
                        headers=cle).json()
    assert any(o["type"] == "logement" for o in objets["objets"])


def test_ingestion_zone_logement_sans_communes_avertit(monkeypatch):
    cle = {"X-API-Key": "ingestion-logements-sans-communes"}
    client.post("/zones", json={"nom": "Rayon logement", "type": "logement",
                                "lat": 43.6, "lon": 2.2, "rayon_km": 10}, headers=cle)
    res = client.post("/ingestion/executer", headers=cle).json()
    assert res["nouveaux"] == 0
    assert len(res["avertissements"]) == 1 and "commune" in res["avertissements"][0].lower()


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


# ── Parametres ───────────────────────────────────────────────────
def test_zone_porte_ses_parametres(monkeypatch):
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    r = client.post("/zones", json={"nom": "Passoires Carcassonne", "type": "logement",
                                    "communes": ["11000"],
                                    "parametres": {"grades_dpe": ["E", "F", "G"]}},
                    headers=CLE)
    assert r.status_code == 201
    assert r.json()["parametres"] == {"grades_dpe": ["E", "F", "G"]}


def test_zone_sans_parametres_rend_dict_vide():
    r = client.post("/zones", json={"nom": "Sans param", "lat": 43.6, "lon": 2.2,
                                    "rayon_km": 10}, headers=CLE)
    assert r.json()["parametres"] == {}
