"""Tests API de veille-prospection : CRUD campagnes isolé par personne, gate du
déclenchement horloge. TestClient direct — motif briques/veille-info/test_main.py.

Identifiants préfixés `main-` (jamais utilisés dans test_stockage.py/test_orchestration.py).
Les tests `/campagnes/executer` mockent `main.orchestration.executer_campagnes` : ils ne
vérifient QUE le gate d'authentification, pas le pipeline (déjà couvert par
test_orchestration.py) — sans ce mock, l'appel réel traiterait toutes les campagnes de la DB
partagée, y compris celles créées par d'autres fichiers de test."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_creer_lister_supprimer_campagne(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    r = client.post("/campagnes", headers=_entetes("main-alice"),
                    json={"zone_id": "zone-a"})
    assert r.status_code == 201
    campagne_id = r.json()["id"]

    r = client.get("/campagnes", headers=_entetes("main-alice"))
    assert len(r.json()) == 1

    r = client.delete(f"/campagnes/{campagne_id}", headers=_entetes("main-alice"))
    assert r.status_code == 200
    assert client.get("/campagnes", headers=_entetes("main-alice")).json() == []


def test_campagnes_isolees_par_x_user_id(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    client.post("/campagnes", headers=_entetes("main-bob"),
               json={"zone_id": "zone-de-bob"})
    r = client.get("/campagnes", headers=_entetes("main-carol"))
    assert all(c["zone_id"] != "zone-de-bob" for c in r.json())


def test_supprimer_campagne_dune_autre_personne_echoue(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    r = client.post("/campagnes", headers=_entetes("main-dave"),
                    json={"zone_id": "zone-privee"})
    campagne_id = r.json()["id"]
    r = client.delete(f"/campagnes/{campagne_id}", headers=_entetes("main-mallory"))
    assert r.status_code == 404


def test_x_user_id_sans_cle_est_ignore(monkeypatch):
    """Régression : un X-User-Id SEUL (sans clé API) ne doit JAMAIS être honoré — sinon
    n'importe quel appelant non authentifié pourrait usurper l'identité de n'importe
    quel membre du foyer (bug déjà trouvé et corrigé une fois dans ce projet)."""
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    # POST avec SEUL X-User-Id (pas de clé) → doit atterrir dans "public", pas "perso:main-usurpateur"
    r = client.post("/campagnes", headers={"X-User-Id": "main-usurpateur"},
                   json={"zone_id": "zone-usurpee"})
    assert r.status_code == 201
    # GET authentifié AS main-usurpateur avec clé valide → ne voit PAS la campagne créée ci-dessus
    r = client.get("/campagnes", headers=_entetes("main-usurpateur"))
    assert all(c["zone_id"] != "zone-usurpee" for c in r.json())


def test_campagnes_executer_ouvert_si_pas_de_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.orchestration, "executer_campagnes",
                        lambda: {"campagnes_executees": 0})
    r = client.post("/campagnes/executer")
    assert r.status_code == 200
    assert "campagnes_executees" in r.json()


def test_campagnes_executer_gate_si_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.orchestration, "executer_campagnes",
                        lambda: {"campagnes_executees": 0})
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "secret-horloge")
    r = client.post("/campagnes/executer")
    assert r.status_code == 401
    r = client.post("/campagnes/executer",
                    headers={"Authorization": "Bearer secret-horloge"})
    assert r.status_code == 200


def test_creer_campagne_type_b2c(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration.httpx, "get",
                       lambda *a, **k: (_ for _ in ()).throw(Exception("réseau interdit dans ce test")))
    r = client.post("/campagnes", headers=_entetes("main-eve"),
                    json={"zone_id": "zone-logements-eve", "type": "b2c"})
    assert r.status_code == 201 and r.json()["type"] == "b2c"


def test_creer_campagne_type_par_defaut_reste_b2b(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration.httpx, "get",
                       lambda *a, **k: (_ for _ in ()).throw(Exception("réseau interdit dans ce test")))
    r = client.post("/campagnes", headers=_entetes("main-frank"),
                    json={"zone_id": "zone-frank"})
    assert r.status_code == 201 and r.json()["type"] == "b2b"


def test_creer_campagne_type_invalide_422(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration.httpx, "get",
                       lambda *a, **k: (_ for _ in ()).throw(Exception("réseau interdit dans ce test")))
    r = client.post("/campagnes", headers=_entetes("main-gina"),
                    json={"zone_id": "zone-gina", "type": "b2x"})
    assert r.status_code == 422


def test_creer_campagne_resout_zone_nom_via_geo(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo",
                        lambda zone_id: {"id": zone_id, "nom": "Restos Castres", "type": "entreprise"})
    r = client.post("/campagnes", headers=_entetes("main-henri"),
                    json={"zone_id": "zone-castres"})
    assert r.status_code == 201
    assert r.json()["zone_nom"] == "Restos Castres"


def test_creer_campagne_zone_nom_none_si_geo_injoignable(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    def _casse(zone_id):
        raise Exception("geo down")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", _casse)
    r = client.post("/campagnes", headers=_entetes("main-ines"),
                    json={"zone_id": "zone-hs"})
    assert r.status_code == 201
    assert r.json()["zone_nom"] is None


def test_creer_campagne_resout_zone_nom_une_seule_fois(monkeypatch):
    """`lire_zone_geo` ne doit être appelée qu'UNE fois par création — le résultat est
    réutilisé pour l'avertissement de cohérence type/zone (pas de 2e appel réseau)."""
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    appels = {"n": 0}
    def _compte(zone_id):
        appels["n"] += 1
        return {"id": zone_id, "nom": "Logements Castres", "type": "logement"}
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", _compte)
    r = client.post("/campagnes", headers=_entetes("main-jules"),
                    json={"zone_id": "zone-logements", "type": "b2b"})
    assert r.status_code == 201
    assert appels["n"] == 1
    assert "avertissement" in r.json()  # b2b sur zone logement → incohérence signalée


def test_executer_campagne_id_404_si_autre_tenant(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-karim"),
                    json={"zone_id": "zone-karim"})
    campagne_id = r.json()["id"]
    r = client.post(f"/campagnes/{campagne_id}/executer", headers=_entetes("main-laura"))
    assert r.status_code == 404


def test_executer_campagne_id_404_si_inactive(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-mona"),
                    json={"zone_id": "zone-mona"})
    campagne_id = r.json()["id"]
    client.delete(f"/campagnes/{campagne_id}", headers=_entetes("main-mona"))
    r = client.post(f"/campagnes/{campagne_id}/executer", headers=_entetes("main-mona"))
    assert r.status_code == 404


def test_executer_campagne_id_retourne_le_resultat_et_persiste(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-nadia"),
                    json={"zone_id": "zone-nadia"})
    campagne_id = r.json()["id"]

    appele_avec = {}
    def _faux_executer(campagne):
        appele_avec["id"] = campagne["id"]
        return {"trouves": 5, "deja_connus": 2, "nouveaux_crm": 3, "erreur": None}
    monkeypatch.setattr(main.orchestration, "executer_campagne_unique", _faux_executer)

    r = client.post(f"/campagnes/{campagne_id}/executer", headers=_entetes("main-nadia"))
    assert r.status_code == 200
    assert r.json() == {"trouves": 5, "deja_connus": 2, "nouveaux_crm": 3, "erreur": None}
    assert appele_avec["id"] == campagne_id

    r = client.get(f"/campagnes/{campagne_id}/executions", headers=_entetes("main-nadia"))
    assert len(r.json()) == 1
    assert r.json()[0]["trouves"] == 5

    r = client.get("/campagnes", headers=_entetes("main-nadia"))
    assert r.json()[0]["derniere_execution"] is not None


def test_lister_executions_404_si_autre_tenant(monkeypatch):
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "cle-coeur")
    monkeypatch.setattr(main.orchestration, "lire_zone_geo", lambda z: None)
    r = client.post("/campagnes", headers=_entetes("main-oscar"),
                    json={"zone_id": "zone-oscar"})
    campagne_id = r.json()["id"]
    r = client.get(f"/campagnes/{campagne_id}/executions", headers=_entetes("main-paula"))
    assert r.status_code == 404
