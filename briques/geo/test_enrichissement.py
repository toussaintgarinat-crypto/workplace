"""Enrichissement opt-in : heuristiques pures, parcours API (recherche mockée), journal."""
import httpx
import pytest
from fastapi.testclient import TestClient

import enrichissement
import main

client = TestClient(main.app)

CLE = {"X-API-Key": "prospecteur"}


# ── Heuristiques pures ───────────────────────────────────────────
def test_extraire_contacts_emails_dedupliques_et_filtres():
    texte = ("Écrivez à Contact@Boulangerie-Test.fr ou contact@boulangerie-test.fr. "
             "Logo : sprite@2x.png — support : noreply@wix.com")
    c = enrichissement.extraire_contacts(texte)
    assert c["emails"] == ["contact@boulangerie-test.fr"]


def test_extraire_contacts_telephones_fr():
    texte = "Tél : 05 63 12 34 56 / mobile +33 6 07 08 09 10 / fixe 05.63.12.34.56"
    tels = enrichissement.extraire_contacts(texte)["telephones"]
    assert "05 63 12 34 56" in tels
    assert any(t.startswith("+33") for t in tels)


def test_choisir_site_ecarte_les_annuaires():
    resultats = [
        {"titre": "Boulangerie Test — PagesJaunes", "url": "https://www.pagesjaunes.fr/pros/1"},
        {"titre": "BOULANGERIE TEST (Castres) — societe.com", "url": "https://www.societe.com/x"},
        {"titre": "Boulangerie Test, pain au levain à Castres", "url": "https://boulangerie-test.fr/"},
    ]
    assert enrichissement.choisir_site(resultats, "Boulangerie Test") == "https://boulangerie-test.fr/"


def test_choisir_site_exige_la_commune_quand_connue():
    # Cas RÉEL (preuve LIVE HP) : le resto « ORIGINE » matchait un article persee.fr
    # contenant le mot « origine ». Avec la commune connue, ce faux positif tombe.
    resultats = [{"titre": "Origine et diffusion — revue", "extrait": "…l'origine des…",
                  "url": "https://www.persee.fr/doc/rio_1971"}]
    assert enrichissement.choisir_site(resultats, "ORIGINE", commune="CASTRES") is None
    corrobore = [{"titre": "ORIGINE — restaurant à Castres", "extrait": "bistrot",
                  "url": "https://restaurant-origine.fr/"}]
    assert enrichissement.choisir_site(corrobore, "ORIGINE", commune="CASTRES") == \
        "https://restaurant-origine.fr/"


def test_choisir_site_nom_generique_exige_le_domaine():
    # 2e cas RÉEL : la page Wikipédia de Castres contient « origine » + « castres ».
    # Un nom à UN jeton n'est retenu que si le DOMAINE le porte ; et les sous-domaines
    # des exclus (fr.wikipedia.org) tombent aussi.
    pieges = [
        {"titre": "Castres — Wikipédia", "extrait": "…l'origine de la ville…",
         "url": "https://fr.wikipedia.org/wiki/Castres"},
        {"titre": "Castres : l'origine du festival", "extrait": "actualité locale",
         "url": "https://www.journal-local.fr/article-123"},
    ]
    assert enrichissement.choisir_site(pieges, "ORIGINE", commune="CASTRES") is None


def test_choisir_site_rend_none_sans_correspondance():
    resultats = [{"titre": "Tout autre chose", "url": "https://autre-domaine.fr/"}]
    assert enrichissement.choisir_site(resultats, "Boulangerie Test") is None
    assert enrichissement.choisir_site([], "Boulangerie Test") is None
    assert enrichissement.choisir_site(resultats, "") is None


def test_trouver_lien_contact_dicts_et_chaines():
    liens = [{"url": "https://x.fr/menu", "texte": "La carte"},
             {"url": "https://x.fr/nous-contacter", "texte": "Contact"}]
    assert enrichissement.trouver_lien_contact(liens) == "https://x.fr/nous-contacter"
    assert enrichissement.trouver_lien_contact(["https://x.fr/contact"]) == "https://x.fr/contact"
    assert enrichissement.trouver_lien_contact([]) is None


# ── Faux client HTTP (brique recherche simulée, zéro réseau) ─────
class _Rep:
    def __init__(self, status_code, corps):
        self.status_code = status_code
        self._corps = corps

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=None)


class _FauxHTTP:
    def __init__(self, rechercher, pages):
        self.rechercher, self.pages = rechercher, pages

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        if url.endswith("/rechercher"):
            return _Rep(200, {"resultats": self.rechercher})
        page = self.pages.get((json or {}).get("url"))
        return _Rep(200, page) if page else _Rep(404, {})


RESULTATS = [{"titre": "Boulangerie Test — le fournil de Castres",
              "url": "https://boulangerie-test.fr/"}]


def _objet(nom="Boulangerie Test", cle=CLE):
    r = client.post("/objets", headers=cle,
                    json={"latitude": 43.606, "longitude": 2.24,
                          "metadata": {"nom": nom, "commune": "CASTRES"}})
    return r.json()["id"]


# ── Parcours API ─────────────────────────────────────────────────
def test_enrichir_trouve_site_et_email(monkeypatch):
    pages = {"https://boulangerie-test.fr/":
             {"texte": "Bienvenue ! Écrivez-nous : bonjour@boulangerie-test.fr "
                       "ou 05 63 12 34 56", "liens": []}}
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxHTTP(RESULTATS, pages))
    oid = _objet()
    r = client.post(f"/objets/{oid}/enrichir", headers=CLE)
    assert r.status_code == 200 and r.json()["statut"] == "ok"
    meta = r.json()["objet"]["metadata"]
    assert meta["site"] == "https://boulangerie-test.fr/"
    assert meta["email"] == "bonjour@boulangerie-test.fr"
    assert meta["telephone"] == "05 63 12 34 56"
    assert meta["enrichi_source"] and meta["enrichi_le"]


def test_enrichir_email_sur_la_page_contact(monkeypatch):
    pages = {
        "https://boulangerie-test.fr/":
            {"texte": "Bienvenue, pain au levain.", "liens":
             [{"url": "https://boulangerie-test.fr/contact", "texte": "Contact"}]},
        "https://boulangerie-test.fr/contact":
            {"texte": "Écrivez à fournil@boulangerie-test.fr", "liens": []},
    }
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxHTTP(RESULTATS, pages))
    r = client.post(f"/objets/{_objet()}/enrichir", headers=CLE)
    rapport = r.json()["rapport"]
    assert rapport["emails"] == ["fournil@boulangerie-test.fr"]
    assert rapport["source_url"] == "https://boulangerie-test.fr/contact"


def test_enrichir_introuvable_honnete_et_journalise(monkeypatch):
    annuaires = [{"titre": "Boulangerie Test", "url": "https://www.pagesjaunes.fr/1"}]
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxHTTP(annuaires, {}))
    oid = _objet()
    r = client.post(f"/objets/{oid}/enrichir", headers=CLE)
    assert r.json()["statut"] == "introuvable"
    assert "email" not in r.json()["objet"]["metadata"]
    journal = client.get("/enrichissements", headers=CLE).json()["enrichissements"]
    assert journal[0]["objet_id"] == oid and journal[0]["statut"] == "introuvable"


def test_enrichir_idempotent_sauf_force(monkeypatch):
    pages = {"https://boulangerie-test.fr/":
             {"texte": "bonjour@boulangerie-test.fr", "liens": []}}
    faux = _FauxHTTP(RESULTATS, pages)
    monkeypatch.setattr(enrichissement.httpx, "Client", faux)
    oid = _objet()
    assert client.post(f"/objets/{oid}/enrichir", headers=CLE).json()["statut"] == "ok"
    # Sans force : renvoyé tel quel, aucune nouvelle recherche.
    assert client.post(f"/objets/{oid}/enrichir",
                       headers=CLE).json()["statut"] == "deja_enrichi"
    # Avec force : on re-tente.
    assert client.post(f"/objets/{oid}/enrichir?force=true",
                       headers=CLE).json()["statut"] == "ok"


def test_enrichir_recherche_injoignable_502_et_journalise(monkeypatch):
    class _Casse:
        def __call__(self, *a, **k):
            raise httpx.ConnectError("refus de connexion")
    monkeypatch.setattr(enrichissement.httpx, "Client", _Casse())
    oid = _objet()
    r = client.post(f"/objets/{oid}/enrichir", headers=CLE)
    assert r.status_code == 502
    journal = client.get("/enrichissements", headers=CLE).json()["enrichissements"]
    assert journal[0]["statut"] == "erreur"


def test_enrichir_objet_d_un_autre_tenant_404(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxHTTP(RESULTATS, {}))
    oid = _objet()
    r = client.post(f"/objets/{oid}/enrichir", headers={"X-API-Key": "un-autre"})
    assert r.status_code == 404
