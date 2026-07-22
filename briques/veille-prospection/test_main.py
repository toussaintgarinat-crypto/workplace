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


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_creer_lister_supprimer_campagne():
    r = client.post("/campagnes", headers={"X-User-Id": "main-alice"},
                    json={"zone_id": "zone-a"})
    assert r.status_code == 201
    campagne_id = r.json()["id"]

    r = client.get("/campagnes", headers={"X-User-Id": "main-alice"})
    assert len(r.json()) == 1

    r = client.delete(f"/campagnes/{campagne_id}", headers={"X-User-Id": "main-alice"})
    assert r.status_code == 200
    assert client.get("/campagnes", headers={"X-User-Id": "main-alice"}).json() == []


def test_campagnes_isolees_par_x_user_id():
    client.post("/campagnes", headers={"X-User-Id": "main-bob"},
               json={"zone_id": "zone-de-bob"})
    r = client.get("/campagnes", headers={"X-User-Id": "main-carol"})
    assert all(c["zone_id"] != "zone-de-bob" for c in r.json())


def test_supprimer_campagne_dune_autre_personne_echoue():
    r = client.post("/campagnes", headers={"X-User-Id": "main-dave"},
                    json={"zone_id": "zone-privee"})
    campagne_id = r.json()["id"]
    r = client.delete(f"/campagnes/{campagne_id}", headers={"X-User-Id": "main-mallory"})
    assert r.status_code == 404


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
