"""Zones par commune(s) : contour→bbox, résolution nom/CP, branche /search du réel."""
import httpx
import pytest
from fastapi.testclient import TestClient

import domaine
import fournisseurs
import geographie
import main

client = TestClient(main.app)

CLE = {"X-API-Key": "villageois"}

CONTOUR_CARRE = {"type": "Polygon",
                 "coordinates": [[[2.15, 43.52], [2.21, 43.52],
                                  [2.21, 43.57], [2.15, 43.57], [2.15, 43.52]]]}


# ── Géométrie pure ───────────────────────────────────────────────
def test_bbox_depuis_contour_polygon_et_multipolygon():
    assert domaine.bbox_depuis_contour(CONTOUR_CARRE) == (43.52, 2.15, 43.57, 2.21)
    multi = {"type": "MultiPolygon", "coordinates": [CONTOUR_CARRE["coordinates"],
             [[[2.30, 43.60], [2.32, 43.60], [2.32, 43.62], [2.30, 43.62], [2.30, 43.60]]]]}
    assert domaine.bbox_depuis_contour(multi) == (43.52, 2.15, 43.62, 2.32)
    assert domaine.bbox_depuis_contour(None) is None
    assert domaine.bbox_depuis_contour({"type": "Polygon", "coordinates": []}) is None


def test_bbox_union():
    a, b = (43.0, 2.0, 43.5, 2.5), (43.4, 2.4, 43.9, 2.9)
    assert domaine.bbox_union([a, b]) == (43.0, 2.0, 43.9, 2.9)
    with pytest.raises(ValueError):
        domaine.bbox_union([])


# ── Résolution de communes (annuaire mocké, zéro réseau) ─────────
class _FauxGeoAPI:
    """Simule geo.api.gouv.fr : nom connu → 1 commune ; CP « 81290 » → 2 communes."""
    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        import types
        if params.get("codePostal") == "81290":
            corps = [{"code": "81325", "nom": "Viviers-lès-Montagnes",
                      "contour": CONTOUR_CARRE},
                     {"code": "81092", "nom": "Escoussens", "contour": CONTOUR_CARRE}]
        elif (params.get("nom") or "").lower().startswith("viviers"):
            corps = [{"code": "81325", "nom": "Viviers-lès-Montagnes",
                      "contour": CONTOUR_CARRE}]
        else:
            corps = []
        return types.SimpleNamespace(status_code=200, json=lambda: corps,
                                     raise_for_status=lambda: None)


def test_resoudre_nom_et_code_postal_dedoublonne(monkeypatch):
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    communes = geographie.resoudre_communes(["Viviers-lès-Montagnes", "81290"])
    assert {c["code"] for c in communes} == {"81325", "81092"}   # dédoublonné
    assert all(c["bbox"] for c in communes)


def test_resoudre_commune_introuvable_leve(monkeypatch):
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    with pytest.raises(ValueError):
        geographie.resoudre_communes(["Atlantide"])


# ── API zones ────────────────────────────────────────────────────
def test_creer_zone_par_communes(monkeypatch):
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    r = client.post("/zones", headers=CLE,
                    json={"nom": "Mes villages", "communes": ["Viviers-lès-Montagnes"]})
    assert r.status_code == 201
    zone = r.json()
    assert zone["communes"] == [{"code": "81325", "nom": "Viviers-lès-Montagnes"}]
    assert (zone["lat_min"], zone["lon_min"]) == (43.52, 2.15)   # bbox du contour


def test_creer_zone_commune_introuvable_400(monkeypatch):
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    r = client.post("/zones", headers=CLE,
                    json={"nom": "Nulle part", "communes": ["Atlantide"]})
    assert r.status_code == 400 and "introuvable" in r.json()["detail"]


def test_ingestion_reelle_accepte_commune_sans_naf(monkeypatch):
    """En réel, une zone à COMMUNES est énumérable sans NAF : pas d'avertissement,
    le fournisseur est bien appelé."""
    monkeypatch.setenv("GEO_FOURNISSEUR", "reel")
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    appels = []
    monkeypatch.setattr(main.fournisseurs.RechercheEntreprises, "entreprises_recentes",
                        lambda self, zone, depuis=None: appels.append(zone) or [])
    cle = {"X-API-Key": "reel-communes"}
    client.post("/zones", headers=cle,
                json={"nom": "Village seul", "communes": ["Viviers-lès-Montagnes"]})
    res = client.post("/ingestion/executer", headers=cle).json()
    assert res["avertissements"] == []
    assert len(appels) == 1 and appels[0]["communes"][0]["code"] == "81325"


# ── Branche /search du fournisseur réel ──────────────────────────
def test_fournisseur_reel_cible_par_code_commune(monkeypatch):
    class _FauxSirene:
        def __init__(self):
            self.requetes = []

        def __call__(self, *a, **k):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None):
            import types
            self.requetes.append((url, params))
            return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                         json=lambda: {"results": [], "total_pages": 1})

    faux = _FauxSirene()
    monkeypatch.setattr(fournisseurs.httpx, "Client", faux)
    zone = {"id": "z1", "nom": "V", "naf": None, "type": "entreprise",
            "lat_min": 43.52, "lon_min": 2.15,
            "lat_max": 43.57, "lon_max": 2.21, "derniere_ingestion": None,
            "communes": [{"code": "81325", "nom": "Viviers-lès-Montagnes"},
                         {"code": "81092", "nom": "Escoussens"}]}
    fournisseurs.RechercheEntreprises().entreprises_recentes(zone)
    url, params = faux.requetes[0]
    assert url.endswith("/search")
    assert params["code_commune"] == "81325,81092"
    assert "activite_principale" not in params and "est_association" not in params
    # Zone ASSOCIATIONS → même /search, avec le filtre est_association.
    fournisseurs.RechercheEntreprises().entreprises_recentes({**zone, "type": "association"})
    _, params_asso = faux.requetes[-1]
    assert params_asso["est_association"] == "true"
    # …et la zone à rayon garde le near_point.
    zone_rayon = {**zone, "communes": [], "naf": "56.10A"}
    fournisseurs.RechercheEntreprises().entreprises_recentes(zone_rayon)
    url2, params2 = faux.requetes[-1]
    assert url2.endswith("/near_point") and params2["activite_principale"] == "56.10A"


def test_ingestion_reelle_associations_exigent_des_communes(monkeypatch):
    """Zone associations à RAYON en réel : ignorée avec un avertissement honnête
    (le filtre n'existe pas sur near_point) ; à COMMUNES : acceptée."""
    monkeypatch.setenv("GEO_FOURNISSEUR", "reel")
    monkeypatch.setattr(geographie.httpx, "Client", _FauxGeoAPI())
    appels = []
    monkeypatch.setattr(main.fournisseurs.RechercheEntreprises, "entreprises_recentes",
                        lambda self, zone, depuis=None: appels.append(zone["nom"]) or [])
    cle = {"X-API-Key": "assos"}
    client.post("/zones", headers=cle, json={"nom": "Assos rayon", "type": "association",
                                             "lat": 43.6, "lon": 2.2, "rayon_km": 10})
    client.post("/zones", headers=cle, json={"nom": "Assos village", "type": "association",
                                             "communes": ["Viviers-lès-Montagnes"]})
    res = client.post("/ingestion/executer", headers=cle).json()
    assert len(res["avertissements"]) == 1 and "associations" in res["avertissements"][0].lower()
    assert appels == ["Assos village"]
