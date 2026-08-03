from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import jeton
from main import app

client = TestClient(app)


def _cookies(identite: str) -> dict:
    return {jeton.COOKIE_NOM: jeton.emettre(identite, ttl=3600)}


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
    r = client.post("/personnages", json={"nom": "Aria", "date_naissance": "1990-09-05"},
                    cookies=_cookies("cree-tenant-1"))
    assert r.status_code == 200
    corps = r.json()
    assert corps["nom"] == "Aria"
    assert corps["snapshot_holistique"]["portrait"]["archetype"] == "Le Sage Contemplatif"


def test_creer_personnage_par_description(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Vorn", "description": "guerrier colérique"},
                    cookies=_cookies("cree-tenant-2"))
    assert r.status_code == 200
    assert r.json()["donnees_naissance"] == {"description": "guerrier colérique"}


def test_creer_personnage_sans_date_ni_description_422():
    r = client.post("/personnages", json={"nom": "Vide"}, cookies=_cookies("cree-tenant-3"))
    assert r.status_code == 422


def test_creer_personnage_nom_banni_422(monkeypatch):
    """Fix S220 revue finale : le filtre de modération (spec § Anti-abus) doit aussi
    s'appliquer à la création de personnage, pas seulement à l'inscription."""
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "SuperConnard", "date_naissance": "1990-01-01"},
                    cookies=_cookies("nom-banni-tenant"))
    assert r.status_code == 422


def test_creer_personnage_nom_trop_long_422():
    r = client.post("/personnages", json={"nom": "x" * 61, "date_naissance": "1990-01-01"},
                    cookies=_cookies("nom-long-tenant"))
    assert r.status_code == 422


def test_rate_limiting_sur_creation_personnage():
    """Fix S220 revue finale : /personnages proxy vers un appel LLM facturable en aval,
    doit être limité en taux comme /inscription et /connexion."""
    import limiteur
    limiteur._reinitialiser()
    ck = _cookies("rate-perso-tenant")
    for _ in range(limiteur.MAX_TENTATIVES):
        client.post("/personnages", json={"nom": "Vide"}, cookies=ck)
    r = client.post("/personnages", json={"nom": "Vide"}, cookies=ck)
    assert r.status_code == 429


def test_creer_personnage_erreur_upstream_5xx_ne_fuit_pas_la_topologie(monkeypatch):
    """Fix S220 revue finale : moteur_personnages.py relaie l'URL interne et l'erreur de
    transport brute sur 5xx (fichier copié verbatim, ne pas éditer) — main.py doit
    intercepter et renvoyer un message générique, sans fuiter la topologie interne."""
    from fastapi import HTTPException as _HTTPException

    async def _portrait_en_panne(fiche, client=None):
        raise _HTTPException(503, "personnages injoignable (http://internal-secret:5900) : "
                                  "some raw transport error")

    async def _ri(description, combien=3, client=None):
        return {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait_en_panne)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)
    r = client.post("/personnages", json={"nom": "Panne", "date_naissance": "1990-01-01"},
                    cookies=_cookies("panne-tenant"))
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "internal-secret" not in detail
    assert "5900" not in detail


def test_creer_personnage_description_sans_date_deduite_422(monkeypatch):
    _patch_moteur(monkeypatch, ri_reponse={"exemple_date": None})
    r = client.post("/personnages", json={"nom": "Flou", "description": "quelque chose"},
                    cookies=_cookies("cree-tenant-4"))
    assert r.status_code == 422


def test_route_personnages_rejette_un_cookie_absent_ou_invalide():
    assert client.get("/personnages").status_code == 401
    assert client.get("/personnages",
                      cookies={jeton.COOKIE_NOM: "pas-un-jeton"}).status_code == 401


def test_lister_et_lire_personnage(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Lu", "date_naissance": "1990-01-01"},
                    cookies=_cookies("lire-tenant"))
    pid = r.json()["id"]
    assert any(p["id"] == pid for p in client.get("/personnages", cookies=_cookies("lire-tenant")).json())
    assert client.get(f"/personnages/{pid}", cookies=_cookies("lire-tenant")).json()["nom"] == "Lu"


def test_lire_personnage_inconnu_404():
    assert client.get("/personnages/inconnu", cookies=_cookies("lire-tenant-2")).status_code == 404


def test_assigner_zone_personnage_inconnu_404():
    r = client.patch("/personnages/inconnu/zone", json={"zone_id": "zone-belier"},
                     cookies=_cookies("zone-tenant-1"))
    assert r.status_code == 404


def test_assigner_zone_inconnue_404(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "SansZone", "date_naissance": "1990-01-01"},
                    cookies=_cookies("zone-tenant-2"))
    pid = r.json()["id"]
    r2 = client.patch(f"/personnages/{pid}/zone", json={"zone_id": "zone-qui-nexiste-pas"},
                      cookies=_cookies("zone-tenant-2"))
    assert r2.status_code == 404


def test_lire_personnage_inclut_progressions_et_competences(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Enrichi", "date_naissance": "1990-01-01"},
                    cookies=_cookies("enrichi-tenant"))
    pid = r.json()["id"]
    detail = client.get(f"/personnages/{pid}", cookies=_cookies("enrichi-tenant")).json()
    assert "progressions" in detail and detail["progressions"] == []
    assert "competences" in detail and detail["competences"] == []


import zones


def test_lister_zones_renvoie_les_12_zones():
    zones.seed_zones()
    r = client.get("/zones", cookies=_cookies("zones-tenant"))
    assert r.status_code == 200
    assert len(r.json()) == 12


def test_lire_zone():
    zones.seed_zones()
    zid = zones.lister_zones()[0]["id"]
    r = client.get(f"/zones/{zid}", cookies=_cookies("zones-tenant-2"))
    assert r.status_code == 200
    assert r.json()["id"] == zid


def test_lire_zone_inconnue_404():
    assert client.get("/zones/inconnue", cookies=_cookies("zones-tenant-3")).status_code == 404


def test_zones_visibles_dun_autre_tenant(monkeypatch):
    """Confirme l'exception au cloisonnement : une autre identité voit les mêmes zones."""
    zones.seed_zones()
    r = client.get("/zones", cookies=_cookies("nimporte-quelle-identite"))
    assert len(r.json()) == 12


import archetypes


def _seed_archetypes():
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()


def test_lister_etapes_archetype_inconnu_404():
    assert client.get("/archetypes/Inexistant/etapes", cookies=_cookies("etapes-tenant")).status_code == 404


def test_lister_etapes_archetype_connu(monkeypatch):
    _seed_archetypes()
    r = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies("etapes-tenant-2"))
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_creer_groupe_et_rejoindre_via_api(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    _seed_archetypes()
    ck = _cookies("groupe-tenant")
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"}, cookies=ck).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes", cookies=ck).json()[0]
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]}, cookies=ck)
    assert r.status_code == 200
    gid = r.json()["id"]
    aide = client.post("/personnages", json={"nom": "Aide", "date_naissance": "1991-01-01"}, cookies=ck).json()
    r2 = client.post(f"/groupes/{gid}/rejoindre", json={"personnage_id": aide["id"]}, cookies=ck)
    assert r2.status_code == 200
    assert aide["id"] in r2.json()["membres"]


def test_creer_groupe_personnage_cible_inconnu_404():
    r = client.post("/groupes", json={"personnage_cible_id": "inconnu", "zone_archetype_id": "x"},
                    cookies=_cookies("groupe-tenant-2"))
    assert r.status_code == 404


def test_creer_groupe_etape_sautee_400(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Sage Contemplatif", "stats": {}},
        "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []})
    _seed_archetypes()
    ck = _cookies("groupe-tenant-3")
    p = client.post("/personnages", json={"nom": "Sauteur2", "date_naissance": "1990-01-01"}, cookies=ck).json()
    etapes = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=ck).json()
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etapes[1]["id"]}, cookies=ck)
    assert r.status_code == 400


def test_lister_competences_personnage_inconnu_404():
    assert client.get("/personnages/inconnu/competences", cookies=_cookies("comp-tenant")).status_code == 404


def test_lister_competences_personnage_connu(monkeypatch):
    _patch_moteur(monkeypatch)
    ck = _cookies("comp-tenant-2")
    p = client.post("/personnages", json={"nom": "Vide2", "date_naissance": "1990-01-01"}, cookies=ck).json()
    r = client.get(f"/personnages/{p['id']}/competences", cookies=ck)
    assert r.status_code == 200
    assert r.json() == []


import combat
import mobs


def test_combat_ws_rejette_une_session_absente():
    with client.websocket_connect("/zones/inconnue/combat?personnage_id=x") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401


def test_combat_ws_zone_ou_personnage_inconnu_est_rejete():
    with client.websocket_connect("/zones/inconnue/combat?personnage_id=inconnu",
                                  cookies=_cookies("combat-tenant-1")) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_ws_connexion_valide_recoit_un_etat_initial(monkeypatch):
    _patch_moteur(monkeypatch)
    zones.seed_zones()
    mobs.seed_mobs()
    ck = _cookies("combat-tenant-2")
    r = client.post("/personnages", json={"nom": "Combattant", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    zone_id = zones.lister_zones()[0]["id"]
    with client.websocket_connect(f"/zones/{zone_id}/combat?personnage_id={pid}", cookies=ck) as ws:
        premier = ws.receive_json()
        assert premier["type"] == "etat"
        assert pid in premier["joueurs"]
    instance = combat._INSTANCES[zone_id][0]
    assert pid not in instance.etat["joueurs"]  # retiré à la déconnexion (finally du handler)


def test_presence_route_ok():
    r = client.post("/presence", cookies=_cookies("presence-tenant"))
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_presence_route_rejette_sans_cookie():
    r = client.post("/presence")
    assert r.status_code == 401


def test_personnages_expose_bonus_idle_actuel(monkeypatch):
    _patch_moteur(monkeypatch)
    _seed_archetypes()
    import main
    monkeypatch.setattr(main.archetypes, "TAUX_IDLE_PAR_HEURE", 1000.0)
    ck = _cookies("idle-tenant-1")
    r = client.post("/personnages", json={"nom": "Idle1", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    with main.stockage._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "idle-tenant-1"))
    items = client.get("/personnages", cookies=ck).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["bonus_idle_actuel"] > 0


def test_personnages_sans_presence_a_bonus_idle_nul(monkeypatch):
    _patch_moteur(monkeypatch)
    _seed_archetypes()
    ck = _cookies("idle-tenant-2")
    r = client.post("/personnages", json={"nom": "Idle2", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    items = client.get("/personnages", cookies=ck).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["bonus_idle_actuel"] == 0


def test_combat_voie_ws_rejette_une_session_absente():
    with client.websocket_connect("/groupes/inconnu/combat?personnage_id=x") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401


def test_combat_voie_ws_groupe_ou_membre_inconnu_est_rejete():
    with client.websocket_connect("/groupes/inconnu/combat?personnage_id=inconnu",
                                  cookies=_cookies("voie-tenant-1")) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_voie_ws_connexion_valide_recoit_un_etat_initial(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    archetypes.seed_zones_archetype()
    import mobs_archetype
    mobs_archetype.seed_mobs_archetype()
    ck = _cookies("voie-tenant-2")
    p = client.post("/personnages", json={"nom": "Voie", "date_naissance": "1990-01-01"},
                    cookies=ck).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes", cookies=ck).json()[0]
    g = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]},
                    cookies=ck).json()
    with client.websocket_connect(f"/groupes/{g['id']}/combat?personnage_id={p['id']}",
                                  cookies=ck) as ws:
        message = ws.receive_json()
        assert message["type"] == "etat"
        assert p["id"] in message["joueurs"]


def test_combat_voie_ws_non_membre_du_groupe_est_rejete(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Sage Contemplatif", "stats": {}},
        "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []})
    archetypes.seed_zones_archetype()
    import mobs_archetype
    mobs_archetype.seed_mobs_archetype()
    ck = _cookies("voie-tenant-3")
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"},
                    cookies=ck).json()
    autre = client.post("/personnages", json={"nom": "PasMembre", "date_naissance": "1990-01-01"},
                        cookies=ck).json()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=ck).json()[0]
    g = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]},
                    cookies=ck).json()
    with client.websocket_connect(f"/groupes/{g['id']}/combat?personnage_id={autre['id']}",
                                  cookies=ck) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_voie_ws_reconnexion_ne_reapplique_pas_le_bonus_idle(monkeypatch):
    """Fix critique (revue S218/S219) : le bonus idle doit se consommer à l'entrée, sinon
    reconnecter (rechargement de page, plusieurs onglets) le réapplique à chaque fois."""
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    archetypes.seed_zones_archetype()
    import mobs_archetype
    mobs_archetype.seed_mobs_archetype()
    import main
    ck = _cookies("voie-tenant-idle")
    p = client.post("/personnages", json={"nom": "Fatigue", "date_naissance": "1990-01-01"},
                    cookies=ck).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes", cookies=ck).json()[0]
    g = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]},
                    cookies=ck).json()
    with main.stockage._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), "voie-tenant-idle"))

    with client.websocket_connect(f"/groupes/{g['id']}/combat?personnage_id={p['id']}",
                                  cookies=ck) as ws:
        premier = ws.receive_json()
    boss_1 = next(m for m in premier["mobs"].values() if m["role"] == "boss")
    pv_boss_1 = boss_1["pv"]
    # pin que le bonus a réellement joué au premier join (sinon l'assertion finale passerait
    # même si tout le mécanisme de bonus idle était supprimé — vue lors de la revue finale).
    assert pv_boss_1 < boss_1["pv_max"]

    with client.websocket_connect(f"/groupes/{g['id']}/combat?personnage_id={p['id']}",
                                  cookies=ck) as ws:
        second = ws.receive_json()
    pv_boss_2 = next(m["pv"] for m in second["mobs"].values() if m["role"] == "boss")

    assert pv_boss_2 >= pv_boss_1


def test_lister_personnages_inclut_prochaine_etape_id(monkeypatch):
    _patch_moteur(monkeypatch)
    _seed_archetypes()
    ck = _cookies("prochaine-tenant-1")
    r = client.post("/personnages", json={"nom": "Prochaine", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    items = client.get("/personnages", cookies=ck).json()
    perso = next(p for p in items if p["id"] == pid)
    assert "prochaine_etape_id" in perso


def test_lister_personnages_prochaine_etape_id_non_none_si_archetype_avec_voie(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    _seed_archetypes()
    ck = _cookies("prochaine-tenant-2")
    r = client.post("/personnages", json={"nom": "Prochaine2", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    items = client.get("/personnages", cookies=ck).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["prochaine_etape_id"] is not None


def test_lister_groupes_rejette_sans_cookie():
    assert client.get("/groupes").status_code == 401


def test_lister_groupes_avec_cookie_ok():
    _seed_archetypes()
    r = client.get("/groupes", cookies=_cookies("groupes-tenant-1"))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_lister_groupes_vide_par_defaut():
    _seed_archetypes()
    r = client.get("/groupes", cookies=_cookies("groupes-tenant-2"))
    assert r.status_code == 200
    assert r.json() == []


def test_lister_groupes_inclut_groupe_actif(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    _seed_archetypes()
    ck = _cookies("groupes-tenant-3")
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"}, cookies=ck).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes", cookies=ck).json()[0]
    groupe = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]}, cookies=ck).json()
    groupes = client.get("/groupes", cookies=ck).json()
    assert len(groupes) == 1
    assert groupes[0]["id"] == groupe["id"]
    assert groupes[0]["personnage_cible_nom"] == "Cible"
    assert groupes[0]["archetype"] == "Le Meneur Charismatique"
    assert groupes[0]["nb_membres"] == 1
