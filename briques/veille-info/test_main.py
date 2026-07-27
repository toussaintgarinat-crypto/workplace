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
                        lambda thematique=None: {"utilisateurs_traites": 0, "digests_crees": 0})
    r = client.post("/digest/executer")
    assert r.status_code == 200
    assert "utilisateurs_traites" in r.json()


def test_digest_executer_gate_si_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda thematique=None: {"utilisateurs_traites": 0, "digests_crees": 0})
    monkeypatch.setenv("VEILLE_INFO_KEY", "secret-horloge")
    r = client.post("/digest/executer")
    assert r.status_code == 401
    r = client.post("/digest/executer", headers={"Authorization": "Bearer secret-horloge"})
    assert r.status_code == 200


def test_digest_executer_relaie_la_thematique_au_pipeline(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    captes = {}
    def _executer(thematique=None):
        captes["thematique"] = thematique
        return {"utilisateurs_traites": 1, "digests_crees": 1}
    monkeypatch.setattr(main.digest, "executer_digest_quotidien", _executer)

    r = client.post("/digest/executer", headers={"Authorization": "Bearer cle-coeur"},
                    json={"thematique": "Tech"})
    assert r.status_code == 200
    assert captes["thematique"] == "Tech"


def test_digest_executer_sans_corps_passe_thematique_none(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    captes = {}
    def _executer(thematique=None):
        captes["thematique"] = thematique
        return {"utilisateurs_traites": 0, "digests_crees": 0}
    monkeypatch.setattr(main.digest, "executer_digest_quotidien", _executer)

    r = client.post("/digest/executer", headers={"Authorization": "Bearer cle-coeur"})
    assert r.status_code == 200
    assert captes["thematique"] is None


def test_digest_expose_audio_url_via_lapi(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    d = stockage.inserer_digest("perso:main-iris", "Résumé.", 1)
    stockage.inserer_audio_digest(d["id"], "https://voix.example/episodes/y.mp3", 12.0)

    r = client.get(f"/digests/{d['id']}", headers=_entetes("main-iris"))
    assert r.json()["audio_url"] == "https://voix.example/episodes/y.mp3"
    assert r.json()["audio_duree"] == 12.0


def test_creer_source_avec_thematique(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-thematique"),
                    json={"nom": "Flux Tech", "url": "https://mt.example/rss", "thematique": "Tech"})
    assert r.status_code == 201
    assert r.json()["thematique"] == "Tech"


def test_retagger_source(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-retag"),
                    json={"nom": "Flux", "url": "https://mr.example/rss"})
    source_id = r.json()["id"]

    r = client.patch(f"/sources/{source_id}/thematique", headers=_entetes("main-retag"),
                     json={"thematique": "Cosmétique"})
    assert r.status_code == 200

    r = client.get("/sources", headers=_entetes("main-retag"))
    assert r.json()[0]["thematique"] == "Cosmétique"


def test_retagger_source_dune_autre_personne_echoue(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-retag-a"),
                    json={"nom": "Flux privé", "url": "https://mra.example/rss"})
    source_id = r.json()["id"]
    r = client.patch(f"/sources/{source_id}/thematique", headers=_entetes("main-retag-b"),
                     json={"thematique": "Piraté"})
    assert r.status_code == 404


def test_generer_audio_global_digest_sans_audio_422(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    d = stockage.inserer_digest("perso:main-audioglobal-1", "Résumé.", 1, thematique="Tech")
    r = client.post("/audio-global/generer", headers=_entetes("main-audioglobal-1"),
                    json={"ordre_thematiques": [d["id"]]})
    assert r.status_code == 422


def test_generer_audio_global_appelle_le_module(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    appele = {}
    def _faux_generer(user_id, ordre):
        appele["user_id"] = user_id
        appele["ordre"] = ordre
        return {"id": 1, "user_id": user_id, "jeton": "jeton-test", "ordre_thematiques": ordre,
                "fichier_path": "/data/audio-global/jeton-test.mp3", "duree_secondes": 12.0,
                "expire_le": "2099-01-01T00:00:00+00:00", "cree_le": "2026-07-26T00:00:00"}
    monkeypatch.setattr(main.audio_global, "generer", _faux_generer)

    r = client.post("/audio-global/generer", headers=_entetes("main-audioglobal-2"),
                    json={"ordre_thematiques": [1, 2]})
    assert r.status_code == 200
    assert r.json()["jeton"] == "jeton-test"
    assert appele["user_id"] == "perso:main-audioglobal-2"
    assert appele["ordre"] == [1, 2]


def test_telecharger_audio_global_expire_404(monkeypatch, tmp_path):
    fichier = tmp_path / "expire.mp3"
    fichier.write_bytes(b"faux-mp3")
    stockage.inserer_audio_global("perso:main-audioglobal-3", "jeton-expire", [1],
                                  str(fichier), 5.0, "2020-01-01T00:00:00+00:00")
    r = client.get("/audio-global/jeton-expire.mp3")
    assert r.status_code == 404


def test_telecharger_audio_global_valide_sert_le_fichier(tmp_path):
    fichier = tmp_path / "valide.mp3"
    fichier.write_bytes(b"faux-contenu-mp3")
    stockage.inserer_audio_global("perso:main-audioglobal-4", "jeton-valide", [1],
                                  str(fichier), 5.0, "2099-01-01T00:00:00+00:00")
    r = client.get("/audio-global/jeton-valide.mp3")
    assert r.status_code == 200
    assert r.content == b"faux-contenu-mp3"


def test_envoyer_audio_global_journalise_resultat_par_destinataire(monkeypatch, tmp_path):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    fichier = tmp_path / "envoi.mp3"
    fichier.write_bytes(b"x")
    a = stockage.inserer_audio_global("perso:main-audioglobal-5", "jeton-envoi", [1],
                                      str(fichier), 5.0, "2099-01-01T00:00:00+00:00")

    def _faux_envoyer(user_id, dest, lien, sujet, message):
        if dest == "echoue@example.com":
            raise main.envoi_mail.EnvoiAudioGlobalError("boom")
    monkeypatch.setattr(main.envoi_mail, "envoyer", _faux_envoyer)

    r = client.post(f"/audio-global/{a['id']}/envoyer", headers=_entetes("main-audioglobal-5"),
                    json={"destinataires": ["ok@example.com", "echoue@example.com"]})
    assert r.status_code == 200
    j = r.json()
    par_dest = {x["destinataire"]: x["ok"] for x in j["resultats"]}
    assert par_dest["ok@example.com"] is True
    assert par_dest["echoue@example.com"] is False


def test_envoyer_audio_global_introuvable_404(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/audio-global/999999/envoyer", headers=_entetes("main-audioglobal-6"),
                    json={"destinataires": ["x@example.com"]})
    assert r.status_code == 404


def test_get_thematiques(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    client.post("/sources", headers=_entetes("main-pause-alice"),
               json={"nom": "Flux A", "url": "https://a4.example/rss", "thematique": "Tech"})
    r = client.get("/thematiques", headers=_entetes("main-pause-alice"))
    assert r.status_code == 200
    corps = r.json()
    assert any(t["thematique"] == "Tech" and t["nb_sources"] == 1 for t in corps)


def test_patch_pause_thematique(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    client.post("/sources", headers=_entetes("main-pause-bob"),
               json={"nom": "Flux B", "url": "https://b4.example/rss", "thematique": "Tech"})
    r = client.patch("/thematiques/pause", json={"thematique": "Tech", "en_pause": True},
                     headers=_entetes("main-pause-bob"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "nb_sources": 1}

    corps = client.get("/thematiques", headers=_entetes("main-pause-bob")).json()
    assert next(t for t in corps if t["thematique"] == "Tech")["en_pause"] is True


def test_patch_pause_thematique_inexistante_404(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.patch("/thematiques/pause", json={"thematique": "Inexistante", "en_pause": True},
                     headers=_entetes("main-pause-carla"))
    assert r.status_code == 404


def test_patch_pause_thematique_par_defaut_vide(monkeypatch):
    """Régression : la thématique par défaut (chaîne vide) doit pouvoir être mise en pause.

    Avant le fix, la route était /thematiques/{thematique}/pause : Starlette exige au
    moins 1 caractère dans {thematique}, donc /thematiques//pause (thematique='')
    faisait 404 et le bouton pause de la thématique "Général" était mort.
    """
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    client.post("/sources", headers=_entetes("main-pause-defaut"),
               json={"nom": "Flux sans thématique", "url": "https://sansthematique.example/rss"})
    r = client.patch("/thematiques/pause", json={"thematique": "", "en_pause": True},
                     headers=_entetes("main-pause-defaut"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "nb_sources": 1}

    corps = client.get("/thematiques", headers=_entetes("main-pause-defaut")).json()
    assert next(t for t in corps if t["thematique"] == "")["en_pause"] is True
