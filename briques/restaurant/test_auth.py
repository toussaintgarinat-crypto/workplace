"""Auth restaurateur : inscription, connexion, sessions signées."""
import uuid

from fastapi.testclient import TestClient

import auth
import main

client = TestClient(main.app)


def _email() -> str:
    return f"resto-{uuid.uuid4().hex[:8]}@exemple.fr"


def test_inscription_cree_compte_et_session():
    r = client.post("/auth/inscription", json={
        "email": _email(), "mot_de_passe": "motdepasse1", "nom": "Chef", "nom_restaurant": "Chez Test"})
    assert r.status_code == 200
    data = r.json()
    assert data["session"]
    assert data["restaurant"]["nom"] == "Chez Test"
    # La session ouvre /auth/moi.
    moi = client.get("/auth/moi", headers={"Authorization": f"Bearer {data['session']}"})
    assert moi.status_code == 200
    assert moi.json()["nom"] == "Chef"


def test_inscription_mot_de_passe_trop_court_refuse():
    r = client.post("/auth/inscription", json={"email": _email(), "mot_de_passe": "court"})
    assert r.status_code == 400


def test_inscription_email_unique():
    email = _email()
    assert client.post("/auth/inscription", json={"email": email, "mot_de_passe": "motdepasse1"}).status_code == 200
    r = client.post("/auth/inscription", json={"email": email, "mot_de_passe": "motdepasse1"})
    assert r.status_code == 409


def test_connexion_bon_et_mauvais_mot_de_passe():
    email = _email()
    client.post("/auth/inscription", json={"email": email, "mot_de_passe": "motdepasse1"})
    assert client.post("/auth/connexion", json={"email": email, "mot_de_passe": "motdepasse1"}).status_code == 200
    assert client.post("/auth/connexion", json={"email": email, "mot_de_passe": "faux-faux-faux"}).status_code == 401


def test_sans_session_401():
    assert client.get("/auth/moi").status_code == 401
    assert client.get("/restaurants").status_code == 401


def test_jeton_falsifie_rejete():
    # Une signature bricolée ne doit jamais ouvrir une session (fail-closed).
    faux = "un-compte.9999999999.signature-bidon"
    assert auth.lire_session(faux) is None
    assert client.get("/auth/moi", headers={"Authorization": f"Bearer {faux}"}).status_code == 401
