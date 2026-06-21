"""Filtres personnalisés (ex. un filtre par entreprise) : logique pure + CRUD + matching via /mail."""
from fastapi.testclient import TestClient

import domaine
import main

client = TestClient(main.app)
T = {"X-API-Key": "tenant-filtres"}


# ── Logique pure ─────────────────────────────────────────────────────────────
def _m(**kw):
    base = {"de": "x@y.fr", "de_nom": "X", "sujet": "", "extrait": ""}
    base.update(kw)
    return base


def test_correspond_filtre_vide_matche_tout():
    assert domaine.correspond_filtre(_m(sujet="rien")) is True


def test_correspond_filtre_mots_ou():
    msg = _m(sujet="Votre facture de juin")
    assert domaine.correspond_filtre(msg, mots=["devis", "facture"]) is True   # au moins un
    assert domaine.correspond_filtre(msg, mots=["devis"]) is False


def test_correspond_filtre_expediteur_sous_chaine():
    msg = _m(de="compta@acme.com")
    assert domaine.correspond_filtre(msg, expediteur="@acme.com") is True
    assert domaine.correspond_filtre(msg, expediteur="@autre.com") is False


def test_correspond_filtre_mots_ET_expediteur():
    msg = _m(de="compta@acme.com", sujet="facture")
    assert domaine.correspond_filtre(msg, mots=["facture"], expediteur="@acme.com") is True
    assert domaine.correspond_filtre(msg, mots=["facture"], expediteur="@autre.com") is False


# ── CRUD + application via /mail (boîte mock) ────────────────────────────────
def _reset():
    for f in client.get("/filtres", headers=T).json()["filtres"]:
        client.delete(f"/filtres/{f['id']}", headers=T)


def test_creer_lister_supprimer():
    _reset()
    r = client.post("/filtres", json={"nom": "Acme", "expediteur": "@example.com"}, headers=T)
    assert r.status_code == 201
    fid = r.json()["id"]
    assert any(f["id"] == fid for f in client.get("/filtres", headers=T).json()["filtres"])
    assert client.delete(f"/filtres/{fid}", headers=T).status_code == 200
    assert client.delete(f"/filtres/{fid}", headers=T).status_code == 404


def test_filtre_sans_critere_refuse():
    assert client.post("/filtres", json={"nom": "Vide"}, headers=T).status_code == 400


def test_mail_par_entreprise_via_expediteur():
    _reset()
    # Boîte mock : marina@example.com et papa@example.com partagent le domaine.
    fid = client.post("/filtres", json={"nom": "Famille", "expediteur": "@example.com"},
                      headers=T).json()["id"]
    j = client.get("/mail", params={"filtre": fid}, headers=T).json()
    assert j["filtre"] == "Famille"
    assert j["messages"] and all("@example.com" in m["de"] for m in j["messages"])


def test_mail_filtre_par_mot():
    _reset()
    fid = client.post("/filtres", json={"nom": "Factures perso", "mots": ["facture"]},
                      headers=T).json()["id"]
    j = client.get("/mail", params={"filtre": fid}, headers=T).json()
    assert j["messages"] and all(
        "facture" in (m["sujet"] + m["extrait"]).lower() for m in j["messages"])


def test_mail_filtre_inexistant_404():
    assert client.get("/mail", params={"filtre": "nope"}, headers=T).status_code == 404
