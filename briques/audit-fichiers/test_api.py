"""Tests — API de la brique audit-fichiers."""
from fastapi.testclient import TestClient

import main
import moteur_clamav as moteur

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["brique"] == "audit-fichiers"


def test_sante_annonce_clamav_joignable(monkeypatch):
    monkeypatch.setattr(moteur, "ping", lambda: True)
    r = c.get("/sante")
    assert r.json()["clamav_joignable"] is True


def test_sante_annonce_clamav_injoignable(monkeypatch):
    monkeypatch.setattr(moteur, "ping", lambda: False)
    r = c.get("/sante")
    assert r.json()["clamav_joignable"] is False


def test_scanner_refuse_fichier_vide():
    r = c.post("/scanner", files={"fichier": ("vide.txt", b"", "text/plain")})
    assert r.status_code == 422


def test_scanner_refuse_fichier_trop_gros(monkeypatch):
    monkeypatch.setattr(main, "MAX_OCTETS", 10)
    r = c.post("/scanner", files={"fichier": ("gros.bin", b"x" * 100, "application/octet-stream")})
    assert r.status_code == 413


def test_scanner_fichier_propre(monkeypatch):
    monkeypatch.setattr(moteur, "scanner", lambda fileobj: moteur.Verdict(propre=True))
    r = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu inoffensif", "application/pdf")})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "propre": True, "raison": None, "scanner": "clamav"}


def test_scanner_detecte_malware(monkeypatch):
    monkeypatch.setattr(moteur, "scanner",
                         lambda fileobj: moteur.Verdict(propre=False, raison="Eicar-Test-Signature"))
    r = c.post("/scanner", files={"fichier": ("virus.exe", b"faux virus", "application/octet-stream")})
    assert r.status_code == 200
    d = r.json()
    assert d["propre"] is False
    assert d["raison"] == "Eicar-Test-Signature"


def test_scanner_clamav_indisponible_refuse_par_precaution(monkeypatch):
    def _leve(fileobj):
        raise moteur.MoteurIndisponible("ClamAV injoignable : connexion refusée")
    monkeypatch.setattr(moteur, "scanner", _leve)
    r = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")})
    assert r.status_code == 503


def test_scanner_exige_cle_api_si_definie(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"secret123"})
    monkeypatch.setattr(moteur, "scanner", lambda fileobj: moteur.Verdict(propre=True))
    r = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")})
    assert r.status_code == 401
    r2 = c.post("/scanner", files={"fichier": ("doc.pdf", b"contenu", "application/pdf")},
                headers={"X-API-Key": "secret123"})
    assert r2.status_code == 200
