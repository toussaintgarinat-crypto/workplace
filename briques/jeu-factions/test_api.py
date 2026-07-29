from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}


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


def test_assigner_zone_inconnue_404(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "SansZone", "date_naissance": "1990-01-01"})
    pid = r.json()["id"]
    r2 = client.patch(f"/personnages/{pid}/zone", json={"zone_id": "zone-qui-nexiste-pas"})
    assert r2.status_code == 404


def test_lire_personnage_inclut_progressions_et_competences(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Enrichi", "date_naissance": "1990-01-01"})
    pid = r.json()["id"]
    detail = client.get(f"/personnages/{pid}").json()
    assert "progressions" in detail and detail["progressions"] == []
    assert "competences" in detail and detail["competences"] == []


import zones


def test_lister_zones_renvoie_les_12_zones():
    zones.seed_zones()
    r = client.get("/zones")
    assert r.status_code == 200
    assert len(r.json()) == 12


def test_lire_zone():
    zones.seed_zones()
    zid = zones.lister_zones()[0]["id"]
    r = client.get(f"/zones/{zid}")
    assert r.status_code == 200
    assert r.json()["id"] == zid


def test_lire_zone_inconnue_404():
    assert client.get("/zones/inconnue").status_code == 404


def test_zones_visibles_dun_autre_tenant(monkeypatch):
    """Confirme l'exception au cloisonnement : une autre clé API voit les mêmes zones."""
    zones.seed_zones()
    r = client.get("/zones", headers={"X-API-Key": "nimporte-quelle-cle"})
    assert len(r.json()) == 12


import archetypes


def _seed_archetypes():
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()


def test_lister_etapes_archetype_inconnu_404():
    assert client.get("/archetypes/Inexistant/etapes").status_code == 404


def test_lister_etapes_archetype_connu(monkeypatch):
    _seed_archetypes()
    r = client.get("/archetypes/Le Sage Contemplatif/etapes")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_creer_groupe_et_rejoindre_via_api(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    _seed_archetypes()
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"}).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes").json()[0]
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]})
    assert r.status_code == 200
    gid = r.json()["id"]
    aide = client.post("/personnages", json={"nom": "Aide", "date_naissance": "1991-01-01"}).json()
    r2 = client.post(f"/groupes/{gid}/rejoindre", json={"personnage_id": aide["id"]})
    assert r2.status_code == 200
    assert aide["id"] in r2.json()["membres"]


def test_creer_groupe_personnage_cible_inconnu_404():
    r = client.post("/groupes", json={"personnage_cible_id": "inconnu", "zone_archetype_id": "x"})
    assert r.status_code == 404


def test_creer_groupe_etape_sautee_400(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Sage Contemplatif", "stats": {}},
        "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []})
    _seed_archetypes()
    p = client.post("/personnages", json={"nom": "Sauteur2", "date_naissance": "1990-01-01"}).json()
    etapes = client.get("/archetypes/Le Sage Contemplatif/etapes").json()
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etapes[1]["id"]})
    assert r.status_code == 400


def test_lister_competences_personnage_inconnu_404():
    assert client.get("/personnages/inconnu/competences").status_code == 404


def test_lister_competences_personnage_connu(monkeypatch):
    _patch_moteur(monkeypatch)
    p = client.post("/personnages", json={"nom": "Vide2", "date_naissance": "1990-01-01"}).json()
    r = client.get(f"/personnages/{p['id']}/competences")
    assert r.status_code == 200
    assert r.json() == []


import combat
import mobs


def test_combat_ws_rejette_une_cle_invalide(monkeypatch):
    import main
    main.API_KEYS = {"bonnecle"}
    try:
        with client.websocket_connect(
                "/zones/inconnue/combat?personnage_id=x&api_key=mauvaise") as ws:
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message["code"] == 4401
    finally:
        main.API_KEYS = set()


def test_combat_ws_zone_ou_personnage_inconnu_est_rejete():
    with client.websocket_connect(
            "/zones/inconnue/combat?personnage_id=inconnu&api_key=") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_ws_connexion_valide_recoit_un_etat_initial(monkeypatch):
    _patch_moteur(monkeypatch)
    zones.seed_zones()
    mobs.seed_mobs()
    r = client.post("/personnages", json={"nom": "Combattant", "date_naissance": "1990-01-01"})
    pid = r.json()["id"]
    zone_id = zones.lister_zones()[0]["id"]
    with client.websocket_connect(f"/zones/{zone_id}/combat?personnage_id={pid}") as ws:
        premier = ws.receive_json()
        assert premier["type"] == "etat"
        assert pid in premier["joueurs"]
    instance = combat._INSTANCES[zone_id][0]
    assert pid not in instance.etat["joueurs"]  # retiré à la déconnexion (finally du handler)
