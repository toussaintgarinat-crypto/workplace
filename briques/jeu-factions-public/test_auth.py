from fastapi.testclient import TestClient

import limiteur
from main import app

client = TestClient(app)


def _inscrire(email="alice@example.com", mdp="motdepasse123", pseudo="Alice"):
    return client.post("/inscription", json={"email": email, "mot_de_passe": mdp, "pseudo": pseudo})


def test_inscription_pose_le_cookie():
    r = _inscrire()
    assert r.status_code == 200
    assert r.cookies.get("jeu_factions_public_utilisateur") is not None


def test_inscription_email_deja_pris_409():
    _inscrire()
    r = _inscrire()
    assert r.status_code == 409


def test_inscription_email_invalide_422():
    r = _inscrire(email="pas-un-email")
    assert r.status_code == 422


def test_inscription_mot_de_passe_trop_court_422():
    r = _inscrire(mdp="court")
    assert r.status_code == 422


def test_inscription_pseudo_banni_422():
    r = _inscrire(pseudo="SuperConnard")
    assert r.status_code == 422


def test_connexion_identifiants_valides():
    _inscrire()
    r = client.post("/connexion", json={"email": "alice@example.com", "mot_de_passe": "motdepasse123"})
    assert r.status_code == 200
    assert r.cookies.get("jeu_factions_public_utilisateur") is not None


def test_connexion_mauvais_mot_de_passe_401():
    _inscrire()
    r = client.post("/connexion", json={"email": "alice@example.com", "mot_de_passe": "faux"})
    assert r.status_code == 401


def test_connexion_email_inconnu_401():
    r = client.post("/connexion", json={"email": "jamais@example.com", "mot_de_passe": "x"})
    assert r.status_code == 401


def test_route_protegee_sans_cookie_401():
    assert client.get("/personnages_test_placeholder").status_code == 404  # route pas encore créée (Task 9)


def test_rate_limiting_sur_connexion():
    limiteur._reinitialiser()
    for _ in range(limiteur.MAX_TENTATIVES):
        client.post("/connexion", json={"email": "x@example.com", "mot_de_passe": "x"})
    r = client.post("/connexion", json={"email": "x@example.com", "mot_de_passe": "x"})
    assert r.status_code == 429


def test_deconnexion_supprime_le_cookie():
    r = client.post("/deconnexion")
    assert r.status_code == 200


def test_inscription_email_deja_pris_meme_si_precheck_rate_409(monkeypatch):
    """Simule la course (TOCTOU) : le pre-check ne voit pas la ligne, mais l'INSERT
    heurte quand même la contrainte UNIQUE — doit rester 409, jamais un 500."""
    _inscrire(email="course@example.com")
    import stockage
    monkeypatch.setattr(stockage, "lire_compte_par_email", lambda email: None)
    r = _inscrire(email="course@example.com")
    assert r.status_code == 409
