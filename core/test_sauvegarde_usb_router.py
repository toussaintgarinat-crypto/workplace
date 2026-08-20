import os
from unittest.mock import AsyncMock

os.environ.setdefault("NOYAU_KEY", "cle-test-noyau")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
import sauvegarde_usb
from routers import sauvegarde_usb as routeur_sauvegarde_usb


def _app():
    app = FastAPI()
    app.include_router(routeur_sauvegarde_usb.router)
    return app


def test_lancer_refuse_sans_auth(monkeypatch):
    # AUTH_ENABLED est un CONSTANTE de module lue à l'import (core/auth.py:54) : la forcer
    # avec monkeypatch.setattr (pas setenv, qui n'aurait aucun effet après l'import).
    # AUTH_ENABLED=false (défaut dev/tests) laisserait passer en identité anonyme — ce n'est
    # PAS ce qu'on teste ici (on teste le refus quand l'auth est vraiment exigée).
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    client = TestClient(_app(), follow_redirects=False)
    r = client.post("/sauvegarde-usb/lancer")
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login"


def test_lancer_accepte_cle_service(monkeypatch):
    monkeypatch.setattr(sauvegarde_usb, "sauvegarder", AsyncMock(
        return_value={"horodatage": "2026-08-20T18:00:00+00:00", "sources": []}))
    client = TestClient(_app())
    r = client.post("/sauvegarde-usb/lancer", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 200
    assert r.json()["sources"] == []


def test_lancer_refuse_mauvaise_cle_service(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    client = TestClient(_app(), follow_redirects=False)
    r = client.post("/sauvegarde-usb/lancer", headers={"X-API-Key": "mauvaise-cle"})
    assert r.status_code == 303


def test_lancer_echec_devient_400(monkeypatch):
    monkeypatch.setattr(sauvegarde_usb, "sauvegarder",
                         AsyncMock(side_effect=RuntimeError("Clé de sauvegarde absente")))
    client = TestClient(_app())
    r = client.post("/sauvegarde-usb/lancer", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 400
    assert "absente" in r.json()["detail"]


def test_env_accepte_cle_service(monkeypatch):
    monkeypatch.setattr(sauvegarde_usb, "lire_env", lambda: "GATEWAY_KEY=abc\n")
    client = TestClient(_app())
    r = client.get("/sauvegarde-usb/env", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 200
    assert r.text == "GATEWAY_KEY=abc\n"
