"""Prospection : enrichissement EN LOT d'une zone (S169). Recherche mockée, zéro réseau.

On vérifie le socle du démarchage : enrichir plusieurs entités d'un coup, borner le lot,
sauter les déjà-enrichies, rester honnête (décompte + journal) et cloisonné par tenant.

Chaque test utilise sa PROPRE clé API → son propre tenant (empreinte) → une base vierge de
son point de vue, sans dépendre de l'ordre d'exécution (la DB de test est partagée).
"""
import re
from urllib.parse import urlparse

import httpx
from fastapi.testclient import TestClient

import enrichissement
import main

client = TestClient(main.app)

BBOX = "43.55,2.10,43.70,2.35"   # englobe Castres (lat 43.60, lon 2.24)


class _Rep:
    def __init__(self, status_code, corps):
        self.status_code, self._corps = status_code, corps

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=None)


class _FauxRecherche:
    """Simule la brique recherche pour un LOT : à chaque requête, fabrique un site
    officiel plausible dérivé du nom cherché + une page contact. `sans_site` = noms pour
    lesquels aucun site n'est trouvé (on ne renvoie qu'un annuaire, donc « introuvable »)."""

    def __init__(self, sans_site=()):
        self.sans_site = set(sans_site)

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        corps = json or {}
        if url.endswith("/rechercher"):
            requete = corps.get("requete", "")
            if any(s in requete for s in self.sans_site):
                return _Rep(200, {"resultats":
                                  [{"titre": "PagesJaunes", "url": "https://www.pagesjaunes.fr/x"}]})
            slug = re.sub(r"[^a-z0-9]+", "-", requete.lower()).strip("-")[:40]
            return _Rep(200, {"resultats":
                              [{"titre": requete + " — site officiel", "url": f"https://{slug}.fr/"}]})
        dom = urlparse(corps.get("url", "")).netloc
        return _Rep(200, {"texte": f"Contactez-nous : contact@{dom}", "liens": []})


def _objet(cle, nom, metadata=None):
    meta = {"nom": nom, "commune": "CASTRES"}
    meta.update(metadata or {})
    r = client.post("/objets", headers=cle,
                    json={"latitude": 43.606, "longitude": 2.24, "metadata": meta})
    return r.json()["id"]


def test_prospecter_lot_enrichit_plusieurs_et_rend_prospects(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-multi"}
    for nom in ("Boulangerie du Sidobre", "Restaurant Le Causse", "Garage des Monts"):
        _objet(cle, nom)
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 10})
    assert r.status_code == 200
    corps = r.json()
    assert corps["compte"]["ok"] == 3
    assert corps["traites"] == 3 and corps["tronque"] is False
    assert len(corps["prospects"]) == 3
    p = corps["prospects"][0]
    assert p["nom"] and p["entreprise"] == p["nom"]
    assert p["email"] and p["email"].startswith("contact@")
    assert p["site"] and p["objet_id"]


def test_prospecter_lot_est_borne(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-borne"}
    for i in range(5):
        _objet(cle, f"Entreprise Numero {i}")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 2}).json()
    assert r["traites"] == 2 and r["plafond"] == 2
    assert r["zone_objets"] == 5 and r["tronque"] is True
    assert r["compte"]["ok"] == 2


def test_prospecter_lot_saute_deja_enrichi_sauf_force(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-deja"}
    _objet(cle, "Cabinet Deja Vu", metadata={"email": "dejavu@exemple.fr"})
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 10}).json()
    assert r["compte"]["deja_enrichi"] == 1 and r["compte"]["ok"] == 0
    # Il reste un prospect valable (il a déjà un email) même sans nouvelle recherche.
    assert len(r["prospects"]) == 1
    forcee = client.post("/prospection/enrichir-lot", headers=cle,
                         json={"bbox": BBOX, "limite": 10, "force": True}).json()
    assert forcee["compte"]["ok"] == 1


def test_prospecter_lot_recherche_injoignable_continue_et_journalise(monkeypatch):
    class _Casse:
        def __call__(self, *a, **k):
            raise httpx.ConnectError("refus de connexion")
    monkeypatch.setattr(enrichissement.httpx, "Client", _Casse())
    cle = {"X-API-Key": "lot-panne"}
    _objet(cle, "Societe Injoignable Un")
    _objet(cle, "Societe Injoignable Deux")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 10})
    assert r.status_code == 200          # une panne réseau ne fait pas planter le lot
    assert r.json()["compte"]["erreur"] == 2
    journal = client.get("/enrichissements", headers=cle).json()["enrichissements"]
    assert journal[0]["statut"] == "erreur"


def test_prospecter_lot_introuvable_pas_de_faux_prospect(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client",
                        _FauxRecherche(sans_site=("Fantome",)))
    cle = {"X-API-Key": "lot-introuvable"}
    _objet(cle, "Fantome Sans Site")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 10}).json()
    assert r["compte"]["introuvable"] == 1
    assert r["prospects"] == []          # aucun contact → aucun prospect inventé


def test_prospecter_lot_cloisonne_par_tenant(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    _objet({"X-API-Key": "lot-prive"}, "Prospect Prive")
    autre = client.post("/prospection/enrichir-lot", headers={"X-API-Key": "lot-voisin"},
                        json={"bbox": BBOX, "limite": 10}).json()
    assert autre["traites"] == 0 and autre["prospects"] == []


def test_prospecter_lot_via_zone_id(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-zone"}
    zone = client.post("/zones", headers=cle, json={"nom": "Castres", "bbox": BBOX}).json()
    _objet(cle, "Prospect De La Zone")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"zone_id": zone["id"], "limite": 10})
    assert r.status_code == 200
    assert r.json()["traites"] == 1


def test_prospecter_lot_zone_id_introuvable_404():
    cle = {"X-API-Key": "lot-zone-404"}
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"zone_id": "zone-inexistante", "limite": 10})
    assert r.status_code == 404


def test_prospecter_lot_zone_id_cloisonne_par_tenant(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    zone = client.post("/zones", headers={"X-API-Key": "lot-zone-prop"},
                       json={"nom": "Castres", "bbox": BBOX}).json()
    r = client.post("/prospection/enrichir-lot", headers={"X-API-Key": "lot-zone-voisin"},
                    json={"zone_id": zone["id"], "limite": 10})
    assert r.status_code == 404   # zone d'un autre tenant : invisible, pas 403 (cloisonnement)


def test_prospecter_lot_sans_bbox_ni_zone_id_400():
    r = client.post("/prospection/enrichir-lot", headers={"X-API-Key": "lot-sans-cible"},
                    json={"limite": 10})
    assert r.status_code == 400


def test_prospect_crm_expose_dirigeants_et_effectifs(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-profond"}
    _objet(cle, "Societe Profonde", metadata={
        "dirigeants": [{"nom": "Dupont", "prenom": "Alice", "qualite": "Gérante"}],
        "effectifs": "10 à 19 salariés",
    })
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 10}).json()
    p = r["prospects"][0]
    assert p["dirigeants"] == [{"nom": "Dupont", "prenom": "Alice", "qualite": "Gérante"}]
    assert p["effectifs"] == "10 à 19 salariés"


def _objet_logement(cle, adresse, grade="F"):
    r = client.post("/objets", headers=cle,
                    json={"type": "logement", "latitude": 43.606, "longitude": 2.24,
                          "metadata": {"adresse": adresse, "commune": "CASTRES",
                                      "code_postal": "81100", "grade_dpe": grade,
                                      "surface_m2": 90.0, "periode_construction": "avant 1948"}})
    return r.json()["id"]


def test_prospecter_lot_logement_saute_la_recherche_web():
    """Aucun mock `enrichissement.httpx` posé : si le code appelait la recherche web
    pour un logement, ce test échouerait par une vraie tentative réseau (timeout/erreur)
    plutôt que par une assertion — la garantie est structurelle, pas un mock qui espionne."""
    cle = {"X-API-Key": "lot-logement"}
    _objet_logement(cle, "12 Rue des Lilas 81100 Castres")
    _objet_logement(cle, "4 Impasse du Moulin 81100 Castres", grade="G")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "type": "logement", "limite": 10})
    assert r.status_code == 200
    corps = r.json()
    assert corps["compte"]["ok"] == 2
    assert len(corps["prospects"]) == 2
    p = corps["prospects"][0]
    assert p["adresse"] and p["grade_dpe"] in {"F", "G"}
    assert "email" not in p and "entreprise" not in p and "nom" not in p


def test_prospecter_lot_logement_via_zone_id():
    cle = {"X-API-Key": "lot-logement-zone"}
    zone = client.post("/zones", headers=cle,
                       json={"nom": "Castres logements", "type": "logement",
                             "bbox": BBOX}).json()
    _objet_logement(cle, "7 Chemin de la Combe 81100 Castres")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"zone_id": zone["id"], "limite": 10})
    assert r.status_code == 200 and r.json()["compte"]["ok"] == 1
