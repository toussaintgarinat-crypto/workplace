"""S241 — recherche plein texte de la brique ingestion (SQLite FTS5)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    stockage.initialiser()
    from main import app
    with TestClient(app) as c:
        yield c


def _importer(client, nom, texte):
    return client.post("/documents/import", json={"nom": nom, "texte_extrait": texte}).json()["id"]


def _ids(client, q):
    r = client.get("/recherche", params={"q": q})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "plein_texte"
    return [x["id"] for x in r.json()["resultats"]]


def test_tokeniseur_trigram_disponible():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")


def test_sans_accents_ni_casse(client):
    d = _importer(client, "Évaluation", "Rapport ÉNERGÉTIQUE de la maison.")
    assert _ids(client, "energetique") == [d]
    assert _ids(client, "EVALUATION") == [d]


def test_faute_de_frappe(client):
    d = _importer(client, "Devis", "Réfection de la toiture.")
    _importer(client, "Autre", "Plomberie de la cuisine.")
    assert _ids(client, "toiturre") == [d]


def test_reference_exacte_en_tete(client):
    cible = _importer(client, "Relance", "La facture FAC-2026-0042 reste impayée.")
    _importer(client, "Factures", "Facture facture facture de mars, FAC-2026-00421.")
    r = client.get("/recherche", params={"q": "facture FAC-2026-0042"}).json()["resultats"]
    assert r[0]["id"] == cible and r[0]["exact"] is True
    assert all(x["exact"] is False for x in r[1:])


def test_expression_entre_guillemets_typographiques(client):
    import recherche
    # Les points de code 8220/8221 doivent être présents (piège de copie du sprint).
    assert {8220, 8221} <= {ord(c) for c in recherche._BORDS}
    assert "“" in recherche._GUILLEMETS.pattern and "”" in recherche._GUILLEMETS.pattern
    cible = _importer(client, "Devis", "Prévoir la toiture complète avant l'hiver.")
    _importer(client, "Autre", "Toiture à refaire, la charpente est complète.")
    r = client.get("/recherche", params={"q": "“toiture complète”"}).json()["resultats"]
    assert r[0]["id"] == cible and r[0]["exact"] is True
    assert all(x["exact"] is False for x in r[1:])


def test_classement_indexe_et_suppression_propagee(client):
    import stockage
    d = _importer(client, "Doc", "Texte neutre sans mot-clé.")
    client.patch(f"/documents/{d}/classement", json={"projet": "Chantier Martin", "tags": ["urgent"]})
    assert _ids(client, "martin") == [d]
    assert stockage.supprimer(d) is True
    assert _ids(client, "martin") == []


def test_reconstruction_de_l_index(client):
    import stockage
    d = _importer(client, "Contrat", "Contrat de maintenance annuelle.")
    with stockage._conn() as con:
        con.execute("DELETE FROM documents_recherche")
        con.execute("DELETE FROM documents_trigrammes")
    assert _ids(client, "maintenance") == []
    stockage.initialiser()  # détecte la désynchronisation et reconstruit
    assert _ids(client, "maintenance") == [d]


def test_requete_vide_refusee(client):
    assert client.get("/recherche", params={"q": " "}).status_code == 422


def test_mots_vides_de_la_requete_ne_remontent_pas_de_hors_sujet(client):
    hors_sujet = _importer(client, "Recrutement d'un conducteur de travaux",
                           "Le poste est ouvert, le candidat dirigera les équipes de chantier.")
    cible = _importer(client, "Devis toiture", "Il faut refaire le toit avant l'hiver.")
    assert _ids(client, "refaire le toit") == [cible]
    assert hors_sujet not in _ids(client, "refaire le toit")


def test_requete_composee_de_mots_vides_ne_renvoie_rien(client):
    _importer(client, "Recrutement d'un conducteur", "Le poste de la société, des équipes.")
    assert _ids(client, "le de des") == []
