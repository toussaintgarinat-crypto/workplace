"""Tests API (TestClient) : santé, garde-fous, flux complet /notes, auth."""
import importlib

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante_mode_placeholder():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "local" in data["fournisseurs"]
    assert data["configures"] == []           # conftest : rien de configuré
    assert data["backend"] == "placeholder"
    assert data["souverain"] is False


def test_liste_fournisseurs():
    r = client.get("/fournisseurs")
    assert r.status_code == 200
    noms = [f["nom"] for f in r.json()["fournisseurs"]]
    assert noms[0] == "local"                  # souverain en tête
    assert all(f["configure"] is False for f in r.json()["fournisseurs"])


def test_transcrire_fichier_vide_422():
    r = client.post("/transcrire", files={"fichier": ("vide.wav", b"")})
    assert r.status_code == 422


def test_transcrire_repli_honnete():
    # Aucun moteur configuré → placeholder honnête, texte vide, JAMAIS inventé.
    r = client.post("/transcrire", files={"fichier": ("a.wav", b"\x00\x01des octets")})
    assert r.status_code == 200
    data = r.json()
    assert data["place_holder"] is True
    assert data["texte"] == ""


def test_resumer_texte_vide_422():
    r = client.post("/resumer", json={"texte": "  "})
    assert r.status_code == 422


def test_resumer_repli_heuristique():
    r = client.post("/resumer", json={"texte": "On a parlé du budget. Puis du planning."})
    assert r.status_code == 200
    assert r.json()["source"] == "heuristique"   # pas de Gateway en test


def test_notes_flux_complet():
    # /notes = transcription + notes en un appel (le flux « Notta »).
    r = client.post("/notes", files={"fichier": ("reunion.wav", b"\x00audio")})
    assert r.status_code == 200
    data = r.json()
    assert "transcription" in data and "notes" in data
    assert data["transcription"]["place_holder"] is True   # pas de moteur en test


def test_destinations_catalogue():
    r = client.get("/destinations")
    assert r.status_code == 200
    data = r.json()
    noms = [d["nom"] for d in data["destinations"]]
    assert set(noms) == {"memoire", "dossier"}
    assert data["defaut"] == "memoire"                 # souverain par défaut


def test_archiver_dossier(tmp_path):
    body = {"notes": {"resume": "synthèse", "decisions": ["valider Y"]},
            "transcription": {"texte": "txt", "langue": "fr"},
            "titre": "Réunion test", "destination": "dossier", "dossier": str(tmp_path)}
    r = client.post("/archiver", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True and out["destination"] == "dossier"
    assert list(tmp_path.glob("*.md"))                 # fichier réellement écrit


def test_archiver_destination_inconnue():
    r = client.post("/archiver", json={"notes": {"resume": "x"}, "destination": "gdrive"})
    assert r.status_code == 200                         # pont consenti : 200 mais ok=false
    assert r.json()["ok"] is False


def test_notes_avec_archivage_dossier(tmp_path):
    r = client.post("/notes", files={"fichier": ("a.wav", b"\x00audio")},
                    data={"destination": "dossier", "dossier": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert "archivage" in data and data["archivage"]["ok"] is True
    assert list(tmp_path.glob("*.md"))


def test_auth_exigee_si_cle_configuree(monkeypatch):
    # Recharge le module avec API_KEYS posé → la clé devient obligatoire.
    monkeypatch.setenv("API_KEYS", "secret-1")
    m = importlib.reload(main)
    c = TestClient(m.app)
    assert c.get("/fournisseurs").status_code == 200          # lecture système ouverte
    assert c.post("/resumer", json={"texte": "x"}).status_code == 401
    ok = c.post("/resumer", json={"texte": "du texte"}, headers={"X-API-Key": "secret-1"})
    assert ok.status_code == 200
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)                                    # restaure pour les autres tests
