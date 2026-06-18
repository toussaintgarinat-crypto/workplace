"""Tests — API de la brique vision (repli honnête, upload, surface JSON /lire)."""
import base64

from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante_annonce_le_backend():
    r = c.get("/sante")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["backend"] == "placeholder"        # aucun moteur configuré en test
    assert d["actif"] is None
    assert d["configures"] == []
    assert "markitdown" in d["fournisseurs"]     # le catalogue reste exposé
    assert "mistral" in d["fournisseurs"]


def test_fournisseurs_liste_le_catalogue():
    r = c.get("/fournisseurs")
    assert r.status_code == 200
    noms = {f["nom"] for f in r.json()["fournisseurs"]}
    assert {"markitdown", "tesseract", "mistral", "google"} <= noms
    assert all(f["configure"] is False for f in r.json()["fournisseurs"])


def test_extraire_fichier_vide_422():
    r = c.post("/extraire", files={"fichier": ("vide.pdf", b"", "application/pdf")})
    assert r.status_code == 422


def test_extraire_rend_un_repli_honnete():
    r = c.post("/extraire", files={"fichier": ("scan.png", b"\x89PNG\r\n", "image/png")})
    assert r.status_code == 200
    d = r.json()
    assert d["place_holder"] is True            # aucun moteur OCR en test
    assert d["texte"] == ""
    assert "note" in d


def test_lire_sans_source_422():
    assert c.post("/lire", json={}).status_code == 422


def test_lire_base64_invalide_422():
    assert c.post("/lire", json={"contenu_base64": "%%pas du base64%%",
                                 "nom_fichier": "x.pdf"}).status_code == 422


def test_lire_base64_valide_donne_repli_honnete():
    contenu = base64.b64encode(b"%PDF-1.4 contenu").decode()
    r = c.post("/lire", json={"contenu_base64": contenu, "nom_fichier": "facture.pdf"})
    assert r.status_code == 200
    d = r.json()
    assert d["place_holder"] is True            # repli honnête, jamais de faux texte
    assert d["texte"] == ""


def test_lire_tolere_un_prefixe_data_uri():
    contenu = "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
    r = c.post("/lire", json={"contenu_base64": contenu, "nom_fichier": "img.png"})
    assert r.status_code == 200
    assert r.json()["place_holder"] is True


def test_mime_devine_depuis_extension():
    assert main._mime_devine("facture.pdf") == "application/pdf"
    assert main._mime_devine("photo.JPG") == "image/jpeg"
    assert main._mime_devine("inconnu.zzz") == "application/octet-stream"
    assert main._mime_devine("x", "image/webp") == "image/webp"   # MIME fourni prime
