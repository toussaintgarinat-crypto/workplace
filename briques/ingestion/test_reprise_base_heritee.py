"""S215 — la base d'avant le renommage est reprise, pas abandonnée à côté d'une base vide.

Le renommage `etl` → `ingestion` déplace la base de `/data/etl.db` à `/data/ingestion.db`.
Sans reprise, `initialiser()` créerait sagement une base VIDE à côté de l'ancienne et la
brique répondrait `documents_ingeres: 0` sans la moindre erreur : le pire genre de perte,
celle qui ne se signale pas. D'où `stockage.reprendre_base_heritee()`, appelée au démarrage.

Ce filet ne couvre PAS le volume Docker (`etl_data` → `ingestion_data`), qui est un cran
au-dessus : un volume neuf ne contient même pas l'ancien fichier. C'est le rôle de
`scripts/migration_etl_vers_ingestion.sh`, qui recopie l'un dans l'autre avant le premier
`up`. Les deux sont nécessaires, aucun ne remplace l'autre.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient


def _base_heritee_avec_un_document(dossier):
    """Écrit une base au FORMAT et au NOM d'avant S215, avec un document dedans."""
    chemin = dossier / "etl.db"
    con = sqlite3.connect(chemin)
    con.execute("""
        CREATE TABLE documents (
            id            TEXT PRIMARY KEY,
            nom           TEXT NOT NULL,
            source        TEXT NOT NULL,
            type_mime     TEXT,
            taille        INTEGER,
            texte_extrait TEXT,
            metadonnees   TEXT DEFAULT '{}',
            date_ingestion TEXT NOT NULL
        )
    """)
    con.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-avant-s215", "contrat.pdf", "upload", "application/pdf", 42,
         "Texte extrait avant le renommage.", "{}", "2026-07-01T10:00:00"),
    )
    con.commit()
    con.close()
    return chemin


@pytest.fixture
def stockage_dans(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    return stockage


def test_la_base_etl_est_reprise_sous_le_nouveau_nom(tmp_path, stockage_dans):
    heritee = _base_heritee_avec_un_document(tmp_path)

    assert stockage_dans.reprendre_base_heritee() is True

    assert not heritee.exists(), "l'ancienne base doit être RENOMMÉE, pas recopiée"
    assert stockage_dans.DB_CHEMIN.exists()
    assert stockage_dans.compter() == 1
    assert stockage_dans.lire("doc-avant-s215")["nom"] == "contrat.pdf"


def test_le_document_survit_a_un_demarrage_complet(tmp_path, monkeypatch):
    """Le vrai chemin : la reprise est câblée dans le lifespan, pas seulement appelable."""
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    _base_heritee_avec_un_document(tmp_path)

    from main import app
    with TestClient(app) as c:
        assert c.get("/sante").json()["documents_ingeres"] == 1
        assert c.get("/documents/doc-avant-s215").json()["nom"] == "contrat.pdf"


def test_une_base_en_service_n_est_jamais_ecrasee(tmp_path, stockage_dans):
    """Si les deux fichiers coexistent, la NOUVELLE gagne : un vieux fichier oublié ne
    doit pas faire reculer la brique d'un état complet."""
    stockage_dans.initialiser()
    stockage_dans.importer({"id": "doc-apres-s215", "nom": "recent.pdf"})
    heritee = _base_heritee_avec_un_document(tmp_path)

    assert stockage_dans.reprendre_base_heritee() is False

    assert heritee.exists(), "l'ancienne base est laissée intacte, pas supprimée"
    assert stockage_dans.compter() == 1
    assert stockage_dans.lire("doc-apres-s215") is not None
    assert stockage_dans.lire("doc-avant-s215") is None


def test_sans_base_heritee_le_demarrage_est_inchange(stockage_dans):
    """Installation neuve : rien à reprendre, et surtout aucune erreur."""
    assert stockage_dans.reprendre_base_heritee() is False
    stockage_dans.initialiser()
    assert stockage_dans.compter() == 0
