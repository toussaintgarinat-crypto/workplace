"""Tests — API de la brique transferts."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True


import os


def test_configuration_expose_la_taille_de_partie():
    r = c.get("/configuration")
    assert r.status_code == 200
    d = r.json()
    assert d["taille_partie_octets"] == int(os.environ["TAILLE_PARTIE_OCTETS"])


def test_creer_transfert_sans_cle_api_ouvert_en_dev():
    r = c.post("/transferts", json={"expiration_heures": 1})
    assert r.status_code == 200
    assert "jeton_upload" in r.json()


def test_creer_transfert_cle_api_invalide_refuse(monkeypatch):
    """cle_api doit refuser (401) si API_KEYS est non vide et la clé fournie est
    absente ou fausse. API_KEYS est un set construit au moment de l'import de
    main.py (os.getenv figé) : on ne peut pas le changer via une variable
    d'environnement après coup, il faut patcher directement main.API_KEYS."""
    monkeypatch.setattr(main, "API_KEYS", {"une-cle-valide"})
    r_sans_cle = c.post("/transferts", json={"expiration_heures": 1})
    assert r_sans_cle.status_code == 401
    r_mauvaise_cle = c.post("/transferts", json={"expiration_heures": 1},
                             headers={"X-API-Key": "mauvaise-cle"})
    assert r_mauvaise_cle.status_code == 401


def test_creer_transfert_cle_api_valide_autorise(monkeypatch):
    """Avec la bonne clé API, la création doit réussir malgré API_KEYS non vide
    (preuve que le test précédent ne renvoie pas 401 « en dur »)."""
    monkeypatch.setattr(main, "API_KEYS", {"une-cle-valide"})
    r = c.post("/transferts", json={"expiration_heures": 1},
               headers={"X-API-Key": "une-cle-valide"})
    assert r.status_code == 200
    assert "jeton_upload" in r.json()


def test_parcours_complet_upload_finalisation_telechargement():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid, jeton_upload = creation["id"], creation["jeton_upload"]

    fichier = c.post(f"/transferts/{tid}/fichiers",
                      json={"nom": "x.bin", "type_mime": "application/octet-stream",
                            "taille_clair": 20, "taille_partie": 16},
                      headers={"X-Upload-Token": jeton_upload}).json()
    fid = fichier["id"]
    assert fichier["nb_parties"] == 2

    r0 = c.put(f"/transferts/{tid}/fichiers/{fid}/parties/0",
               content=b"A" * 44, headers={"X-Upload-Token": jeton_upload})
    assert r0.status_code == 200 and r0.json()["complet"] is False
    r1 = c.put(f"/transferts/{tid}/fichiers/{fid}/parties/1",
               content=b"B" * 32, headers={"X-Upload-Token": jeton_upload})
    assert r1.json()["complet"] is True

    fin = c.post(f"/transferts/{tid}/finaliser", headers={"X-Upload-Token": jeton_upload}).json()
    jeton_public = fin["jeton_public"]

    meta = c.get(f"/t/{jeton_public}/meta").json()
    assert meta["statut"] == "actif"
    assert meta["fichiers"][0]["nom"] == "x.bin"

    brut = c.get(f"/t/{jeton_public}/fichiers/{fid}/chiffre")
    assert brut.status_code == 200
    assert brut.content == b"A" * 44 + b"B" * 32
    assert brut.headers["content-type"] == "application/octet-stream"


def test_upload_partie_mauvais_jeton_refuse():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid = creation["id"]
    fichier = c.post(f"/transferts/{tid}/fichiers",
                      json={"nom": "x.bin", "type_mime": "application/octet-stream",
                            "taille_clair": 10, "taille_partie": 16},
                      headers={"X-Upload-Token": creation["jeton_upload"]}).json()
    r = c.put(f"/transferts/{tid}/fichiers/{fichier['id']}/parties/0",
              content=b"z" * 38, headers={"X-Upload-Token": "faux-jeton"})
    assert r.status_code == 403


def test_meta_transfert_inconnu_404():
    assert c.get("/t/nimporte-quoi/meta").status_code == 404


def test_lister_et_revoquer():
    creation = c.post("/transferts", json={"expiration_heures": 1}).json()
    tid = creation["id"]
    assert any(t["id"] == tid for t in c.get("/transferts").json())
    r = c.post(f"/transferts/{tid}/revoquer")
    assert r.status_code == 200
    assert not any(t["id"] == tid for t in c.get("/transferts").json())


def test_revoquer_transfert_inconnu_404():
    assert c.post("/transferts/nimporte-quoi/revoquer").status_code == 404


def test_lister_cle_api_invalide_refuse(monkeypatch):
    """lister (GET /transferts) doit refuser (401) sans clé API valide quand
    API_KEYS est non vide."""
    monkeypatch.setattr(main, "API_KEYS", {"une-cle-valide"})
    assert c.get("/transferts").status_code == 401
    assert c.get("/transferts", headers={"X-API-Key": "mauvaise-cle"}).status_code == 401


def test_lister_cle_api_valide_autorise(monkeypatch):
    """Avec la bonne clé API, lister doit répondre 200."""
    monkeypatch.setattr(main, "API_KEYS", {"une-cle-valide"})
    assert c.get("/transferts", headers={"X-API-Key": "une-cle-valide"}).status_code == 200


def test_revoquer_cle_api_invalide_refuse(monkeypatch):
    """revoquer_route doit refuser (401) sans clé API valide quand API_KEYS est
    non vide (même sur un identifiant de transfert inexistant : l'auth est
    vérifiée avant la logique métier)."""
    monkeypatch.setattr(main, "API_KEYS", {"une-cle-valide"})
    r = c.post("/transferts/nimporte-quoi/revoquer")
    assert r.status_code == 401
    r2 = c.post("/transferts/nimporte-quoi/revoquer", headers={"X-API-Key": "mauvaise-cle"})
    assert r2.status_code == 401


def test_revoquer_cle_api_valide_autorise(monkeypatch):
    """Avec la bonne clé API, révoquer un transfert existant (créé avec la même
    clé, donc même propriétaire) doit réussir (200)."""
    monkeypatch.setattr(main, "API_KEYS", {"une-cle-valide"})
    entetes = {"X-API-Key": "une-cle-valide"}
    creation = c.post("/transferts", json={"expiration_heures": 1}, headers=entetes).json()
    r = c.post(f"/transferts/{creation['id']}/revoquer", headers=entetes)
    assert r.status_code == 200
    assert r.json()["revoque"] is True


def test_purge_executer_sans_cle_horloge_ouvert_en_dev():
    r = c.post("/purge/executer")
    assert r.status_code == 200
    assert "purges" in r.json()


def test_purge_executer_mauvais_jeton_refuse(monkeypatch):
    """verifier_cle_horloge doit refuser (401) si TRANSFERTS_KEY est défini et le
    jeton Bearer fourni est absent ou ne correspond pas. Contrairement à
    API_KEYS, TRANSFERTS_KEY est relu en direct via os.environ.get(...) dans le
    corps de la fonction : monkeypatch.setenv suffit, pas besoin de setattr."""
    monkeypatch.setenv("TRANSFERTS_KEY", "un-jeton-horloge")
    r_sans_jeton = c.post("/purge/executer")
    assert r_sans_jeton.status_code == 401
    r_mauvais_jeton = c.post("/purge/executer", headers={"Authorization": "Bearer faux-jeton"})
    assert r_mauvais_jeton.status_code == 401


def test_purge_executer_bon_jeton_autorise(monkeypatch):
    """Avec le bon jeton Bearer, /purge/executer doit répondre 200 malgré
    TRANSFERTS_KEY non vide."""
    monkeypatch.setenv("TRANSFERTS_KEY", "un-jeton-horloge")
    r = c.post("/purge/executer", headers={"Authorization": "Bearer un-jeton-horloge"})
    assert r.status_code == 200
    assert "purges" in r.json()


def test_page_upload_servie():
    r = c.get("/")
    assert r.status_code == 200 and "chiffré" in r.text.lower()


def test_page_telechargement_servie_pour_nimporte_quel_jeton():
    # La page se charge toujours (c'est le JS ensuite qui valide le jeton côté /meta) —
    # une route HTML statique ne doit pas dépendre de la validité du jeton en amont.
    r = c.get("/t/nimporte-quoi")
    assert r.status_code == 200 and "déchiffrement" in r.text.lower()


def test_sw_js_servi_avec_cache_control_no_cache():
    r = c.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
