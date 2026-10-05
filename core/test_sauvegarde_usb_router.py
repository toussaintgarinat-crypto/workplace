import os
from unittest.mock import AsyncMock

os.environ.setdefault("NOYAU_KEY", "cle-test-noyau")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

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


def test_env_refuse_la_cle_de_service(monkeypatch):
    """Revue S240 C1 : le .env (clé maîtresse LiteLLM, clés fournisseurs, secret de session)
    ne sort plus JAMAIS avec NOYAU_KEY — c'était la clé du dispatch de capacités, donc du chat
    sans session (« exporte le .env » puis « oui »)."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(sauvegarde_usb, "lire_env", lambda: "GATEWAY_KEY=abc\n")
    client = TestClient(_app(), follow_redirects=False)
    r = client.get("/sauvegarde-usb/env", headers={"X-API-Key": "cle-test-noyau"})
    assert r.status_code == 401
    assert "abc" not in r.text


def test_env_session_admin_cerveau(monkeypatch):
    import time
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    monkeypatch.setattr(sauvegarde_usb, "lire_env", lambda: "GATEWAY_KEY=abc\n")
    auth._cache_access_token["toussaint"] = ("at", time.time() + 60)
    auth._cache_access_token["marina"] = ("at", time.time() + 60)
    try:
        client = TestClient(_app(), follow_redirects=False)
        ok = client.get("/sauvegarde-usb/env", cookies={auth.COOKIE_SESSION: auth.chiffrer_cookie(
            {"sub": "toussaint", "refresh_token": "rt"})}, headers={"Sec-Fetch-Site": "same-origin"})
        assert ok.status_code == 200 and ok.text == "GATEWAY_KEY=abc\n"
        refuse = client.get("/sauvegarde-usb/env", cookies={auth.COOKIE_SESSION: auth.chiffrer_cookie(
            {"sub": "marina", "refresh_token": "rt"})})
        assert refuse.status_code == 403
    finally:
        auth._cache_access_token.clear()


def test_aucune_capacite_ne_renvoie_le_env():
    """Le registre de capacités (chat, MCP) ne doit jamais exposer une route à secrets."""
    import glob
    import json
    routes_a_secrets = {"/sauvegarde-usb/env"}
    for f in glob.glob(os.path.join(os.path.dirname(__file__), "..", "briques", "*", "manifest.json")):
        for c in json.load(open(f)).get("capacites") or []:
            assert c.get("chemin") not in routes_a_secrets, (f, c.get("nom"))
