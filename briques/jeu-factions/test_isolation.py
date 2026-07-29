# test_isolation.py
"""Filet dédié : personnages/groupes restent cloisonnés par cle_api, zones/scores/étapes
restent un monde PARTAGÉ (exception délibérée documentée dans le spec — cf.
docs/superpowers/specs/2026-07-29-jeu-factions-design.md § Architecture)."""
from fastapi.testclient import TestClient

import archetypes
import zones
from main import app

client = TestClient(app)


def _patch_moteur(monkeypatch):
    """Évite l'appel HTTP réel vers `personnages` (PERSONNAGES_URL invalide en test, cf.
    conftest.py) — même patch que test_api.py::_patch_moteur, nécessaire pour toute création
    de personnage via la route /personnages."""
    async def _portrait(fiche, client=None):
        return {"portrait": {"archetype": "Le Sage Contemplatif", "stats": {"Sagesse": 100}},
               "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_personnage_invisible_pour_un_autre_tenant(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Secret", "date_naissance": "1990-01-01"},
                    headers={"X-API-Key": "tenant-a"})
    pid = r.json()["id"]
    assert client.get(f"/personnages/{pid}", headers={"X-API-Key": "tenant-a"}).status_code == 200
    assert client.get(f"/personnages/{pid}", headers={"X-API-Key": "tenant-b"}).status_code == 404
    assert not any(p["id"] == pid for p in
                  client.get("/personnages", headers={"X-API-Key": "tenant-b"}).json())


def test_zones_identiques_pour_tous_les_tenants():
    zones.seed_zones()
    a = client.get("/zones", headers={"X-API-Key": "tenant-a"}).json()
    b = client.get("/zones", headers={"X-API-Key": "tenant-b"}).json()
    assert {z["id"] for z in a} == {z["id"] for z in b}


def test_etapes_archetype_identiques_pour_tous_les_tenants():
    archetypes.seed_zones_archetype()
    a = client.get("/archetypes/Le Sage Contemplatif/etapes",
                   headers={"X-API-Key": "tenant-a"}).json()
    b = client.get("/archetypes/Le Sage Contemplatif/etapes",
                   headers={"X-API-Key": "tenant-b"}).json()
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_groupe_dun_tenant_pas_manipulable_par_un_autre(monkeypatch):
    """Un joueur ne peut pas créer un groupe pour un personnage qu'il ne possède pas —
    même si ce personnage existe (appartient à un autre tenant)."""
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "AutreTenant", "date_naissance": "1990-01-01"},
                    headers={"X-API-Key": "tenant-c"})
    pid = r.json()["id"]
    archetypes.seed_zones_archetype()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes").json()[0]
    r2 = client.post("/groupes", json={"personnage_cible_id": pid, "zone_archetype_id": etape["id"]},
                     headers={"X-API-Key": "tenant-d"})
    assert r2.status_code == 404
