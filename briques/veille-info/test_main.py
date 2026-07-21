"""Tests API de la brique veille-info : CRUD sources isolé par personne, digests, gate du
déclenchement horloge. TestClient direct (pas de Docker).

Identifiants préfixés `main-` (jamais utilisés dans test_stockage.py/test_digest.py) : la
DB SQLite est partagée sur toute la session de test (une seule, cf. conftest.py), donc tout
identifiant réutilisé entre fichiers fausserait les comptages exacts (`len(...) == 1`).

Les deux tests `/digest/executer` mockent `main.digest.executer_digest_quotidien` : ils ne
vérifient QUE le gate d'authentification (401 vs 200), pas le pipeline lui-même (déjà
exhaustivement couvert par test_digest.py) — sans ce mock, l'appel réel traiterait TOUTES
les sources de la DB partagée, y compris celles (URLs factices) laissées par d'autres
fichiers de test, déclenchant de vrais appels réseau."""
from fastapi.testclient import TestClient

import main
import stockage

client = TestClient(main.app)


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_creer_lister_supprimer_source(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-alice"),
                    json={"nom": "Flux A", "url": "https://a.example/rss"})
    assert r.status_code == 201
    source_id = r.json()["id"]

    r = client.get("/sources", headers=_entetes("main-alice"))
    assert len(r.json()) == 1

    r = client.delete(f"/sources/{source_id}", headers=_entetes("main-alice"))
    assert r.status_code == 200
    assert client.get("/sources", headers=_entetes("main-alice")).json() == []


def test_sources_isolees_par_x_user_id(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    client.post("/sources", headers=_entetes("main-bob"),
               json={"nom": "Flux de Bob", "url": "https://bob.example/rss"})
    r = client.get("/sources", headers=_entetes("main-carol"))
    assert all(s["nom"] != "Flux de Bob" for s in r.json())


def test_supprimer_source_dune_autre_personne_echoue(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-dave"),
                    json={"nom": "Flux privé", "url": "https://dave.example/rss"})
    source_id = r.json()["id"]
    r = client.delete(f"/sources/{source_id}", headers=_entetes("main-mallory"))
    assert r.status_code == 404


def test_lister_et_lire_digest(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    stockage.inserer_digest("perso:main-erin", "Résumé du jour.", 3)
    r = client.get("/digests", headers=_entetes("main-erin"))
    assert len(r.json()) == 1
    digest_id = r.json()[0]["id"]
    r = client.get(f"/digests/{digest_id}", headers=_entetes("main-erin"))
    assert r.json()["texte_resume"] == "Résumé du jour."


def test_lire_digest_dune_autre_personne_404(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    d = stockage.inserer_digest("perso:main-frank", "Privé.", 1)
    r = client.get(f"/digests/{d['id']}", headers=_entetes("main-grace"))
    assert r.status_code == 404


def test_digest_executer_ouvert_si_pas_de_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda: {"utilisateurs_traites": 0, "digests_crees": 0})
    r = client.post("/digest/executer")
    assert r.status_code == 200
    assert "utilisateurs_traites" in r.json()


def test_digest_executer_gate_si_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda: {"utilisateurs_traites": 0, "digests_crees": 0})
    monkeypatch.setenv("VEILLE_INFO_KEY", "secret-horloge")
    r = client.post("/digest/executer")
    assert r.status_code == 401
    r = client.post("/digest/executer", headers={"Authorization": "Bearer secret-horloge"})
    assert r.status_code == 200


def test_digest_expose_audio_url_via_lapi(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    d = stockage.inserer_digest("perso:main-iris", "Résumé.", 1)
    stockage.inserer_audio_digest(d["id"], "https://voix.example/episodes/y.mp3", 12.0)

    r = client.get(f"/digests/{d['id']}", headers=_entetes("main-iris"))
    assert r.json()["audio_url"] == "https://voix.example/episodes/y.mp3"
    assert r.json()["audio_duree"] == 12.0
