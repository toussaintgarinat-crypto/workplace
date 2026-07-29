from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}


import httpx
import stockage


def _patch_moteur(monkeypatch, portrait_reponse=None, ri_reponse=None):
    async def _portrait(fiche, client=None):
        return portrait_reponse or {"portrait": {"archetype": "Le Sage Contemplatif",
                                                  "stats": {"Sagesse": 100}},
                                     "traditions": {"signe_solaire": {"nom": "Vierge"}},
                                     "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return ri_reponse if ri_reponse is not None else {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_creer_personnage_par_date(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Aria", "date_naissance": "1990-09-05"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["nom"] == "Aria"
    assert corps["snapshot_holistique"]["portrait"]["archetype"] == "Le Sage Contemplatif"


def test_creer_personnage_par_description(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Vorn", "description": "guerrier colérique"})
    assert r.status_code == 200
    assert r.json()["donnees_naissance"] == {"description": "guerrier colérique"}


def test_creer_personnage_sans_date_ni_description_422():
    r = client.post("/personnages", json={"nom": "Vide"})
    assert r.status_code == 422


def test_creer_personnage_description_sans_date_deduite_422(monkeypatch):
    _patch_moteur(monkeypatch, ri_reponse={"exemple_date": None})
    r = client.post("/personnages", json={"nom": "Flou", "description": "quelque chose"})
    assert r.status_code == 422


def test_lister_et_lire_personnage(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Lu", "date_naissance": "1990-01-01"})
    pid = r.json()["id"]
    assert any(p["id"] == pid for p in client.get("/personnages").json())
    assert client.get(f"/personnages/{pid}").json()["nom"] == "Lu"


def test_lire_personnage_inconnu_404():
    assert client.get("/personnages/inconnu").status_code == 404


def test_assigner_zone_personnage_inconnu_404():
    r = client.patch("/personnages/inconnu/zone", json={"zone_id": "zone-belier"})
    assert r.status_code == 404
