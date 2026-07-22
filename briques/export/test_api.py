"""Tests — API de la brique export."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_sante_annonce_les_themes():
    r = c.get("/sante")
    d = r.json()
    assert sorted(d["themes_pdf"]) == ["livre", "rapport"]
    assert d["themes_pptx"] == ["sobre"]


def test_pdf_refuse_un_titre_vide():
    assert c.post("/pdf", json={"titre": "", "markdown": "contenu"}).status_code == 422


def test_pdf_refuse_un_theme_inconnu():
    r = c.post("/pdf", json={"titre": "T", "markdown": "c", "theme": "neon"})
    assert r.status_code == 422


def test_pdf_produit_un_fichier_servable(monkeypatch):
    monkeypatch.setattr(main.rendu_pdf, "_rendu_html_vers_pdf", lambda html, css: b"%PDF-FAKE")
    r = c.post("/pdf", json={"titre": "Mon Tome", "markdown": "# Chap 1\n\nTexte."})
    assert r.status_code == 200
    url = r.json()["url"]
    fichier = c.get(url)
    assert fichier.status_code == 200
    assert fichier.headers["content-type"] == "application/pdf"
    assert fichier.content == b"%PDF-FAKE"


def test_pptx_refuse_des_diapositives_vides():
    r = c.post("/pptx", json={"titre": "Deck", "diapositives": []})
    assert r.status_code == 422


def test_pptx_produit_un_fichier_servable():
    r = c.post("/pptx", json={"titre": "Deck",
                              "diapositives": [{"titre": "Un", "points": ["a"]}]})
    assert r.status_code == 200
    url = r.json()["url"]
    fichier = c.get(url)
    assert fichier.status_code == 200
    assert fichier.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml")


def test_fichier_inconnu_404():
    assert c.get("/fichiers/inexistant.pdf").status_code == 404


def test_fichier_anti_traversee():
    # pas d'évasion hors du dossier de fichiers produits (même garde que briques/video)
    assert c.get("/fichiers/..%2f..%2fetc%2fpasswd").status_code == 404
