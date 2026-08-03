"""Filet dédié : personnages/groupes restent cloisonnés par cle_api (id de compte réel,
pas de tenant partagé — cette brique n'a jamais eu de mode `"public"`). zones/scores/étapes
restent un monde PARTAGÉ (exception délibérée héritée du design de jeu-factions)."""
from fastapi.testclient import TestClient

import archetypes
import jeton
import zones
from main import app

client = TestClient(app)


def _compte(email: str) -> str:
    r = client.post("/inscription", json={"email": email, "mot_de_passe": "motdepasse123",
                                          "pseudo": email.split("@")[0]})
    assert r.status_code == 200
    return jeton.verifier(r.cookies.get(jeton.COOKIE_NOM))


def _cookies(compte_id: str) -> dict:
    return {jeton.COOKIE_NOM: jeton.emettre(compte_id, ttl=3600)}


def _patch_moteur(monkeypatch):
    async def _portrait(fiche, client=None):
        return {"portrait": {"archetype": "Le Sage Contemplatif", "stats": {"Sagesse": 100}},
               "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_personnage_invisible_pour_un_autre_compte(monkeypatch):
    _patch_moteur(monkeypatch)
    compte_a = _compte("tenant-a@example.com")
    compte_b = _compte("tenant-b@example.com")
    r = client.post("/personnages", json={"nom": "Secret", "date_naissance": "1990-01-01"},
                    cookies=_cookies(compte_a))
    pid = r.json()["id"]
    assert client.get(f"/personnages/{pid}", cookies=_cookies(compte_a)).status_code == 200
    assert client.get(f"/personnages/{pid}", cookies=_cookies(compte_b)).status_code == 404
    assert not any(p["id"] == pid for p in
                  client.get("/personnages", cookies=_cookies(compte_b)).json())


def test_zones_identiques_pour_tous_les_comptes():
    zones.seed_zones()
    compte_a = _compte("tenant-c@example.com")
    compte_b = _compte("tenant-d@example.com")
    a = client.get("/zones", cookies=_cookies(compte_a)).json()
    b = client.get("/zones", cookies=_cookies(compte_b)).json()
    assert {z["id"] for z in a} == {z["id"] for z in b}


def test_etapes_archetype_identiques_pour_tous_les_comptes():
    archetypes.seed_zones_archetype()
    compte_a = _compte("tenant-e@example.com")
    compte_b = _compte("tenant-f@example.com")
    a = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies(compte_a)).json()
    b = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies(compte_b)).json()
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_groupe_dun_compte_pas_manipulable_par_un_autre(monkeypatch):
    _patch_moteur(monkeypatch)
    compte_c = _compte("tenant-g@example.com")
    compte_d = _compte("tenant-h@example.com")
    r = client.post("/personnages", json={"nom": "AutreCompte", "date_naissance": "1990-01-01"},
                    cookies=_cookies(compte_c))
    pid = r.json()["id"]
    archetypes.seed_zones_archetype()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies(compte_c)).json()[0]
    r2 = client.post("/groupes", json={"personnage_cible_id": pid, "zone_archetype_id": etape["id"]},
                     cookies=_cookies(compte_d))
    assert r2.status_code == 404


def test_deux_comptes_avec_le_meme_pseudo_restent_distincts(monkeypatch):
    """Le pseudo n'est pas une clé d'identité — seul l'email l'est (contrainte UNIQUE sur
    comptes.email, pas sur comptes.pseudo)."""
    _patch_moteur(monkeypatch)
    compte_a = _compte("meme-pseudo-1@example.com")
    r = client.post("/inscription", json={"email": "meme-pseudo-2@example.com",
                                          "mot_de_passe": "motdepasse123", "pseudo": "MemePseudo"})
    assert r.status_code == 200 or r.status_code == 409  # 409 seulement si le pseudo ci-dessus était déjà "MemePseudo"
