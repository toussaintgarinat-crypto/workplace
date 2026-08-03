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
    assert client.get("/personnages").status_code == 401


def test_rate_limiting_sur_connexion():
    limiteur._reinitialiser()
    for _ in range(limiteur.MAX_TENTATIVES):
        client.post("/connexion", json={"email": "x@example.com", "mot_de_passe": "x"})
    r = client.post("/connexion", json={"email": "x@example.com", "mot_de_passe": "x"})
    assert r.status_code == 429


def test_deconnexion_supprime_le_cookie():
    r = client.post("/deconnexion")
    assert r.status_code == 200


def test_inscription_email_normalise_pour_la_deduplication_409():
    """Fix S220 revue finale : Bob@x.com et bob@x.com doivent désigner le même compte."""
    r1 = _inscrire(email="Test@Example.com")
    assert r1.status_code == 200
    r2 = _inscrire(email="test@example.com")
    assert r2.status_code == 409


def test_connexion_avec_email_de_casse_differente_reussit():
    """Fix S220 revue finale : une capitale ou une casse différente à la connexion ne doit
    pas empêcher de matcher un compte existant."""
    r = _inscrire(email="test@example.com")
    assert r.status_code == 200
    r2 = client.post("/connexion", json={"email": "TEST@EXAMPLE.COM", "mot_de_passe": "motdepasse123"})
    assert r2.status_code == 200


def test_inscription_email_deja_pris_meme_si_precheck_rate_409(monkeypatch):
    """Simule la course (TOCTOU) : le pre-check ne voit pas la ligne, mais l'INSERT
    heurte quand même la contrainte UNIQUE — doit rester 409, jamais un 500."""
    _inscrire(email="course@example.com")
    import stockage
    monkeypatch.setattr(stockage, "lire_compte_par_email", lambda email: None)
    r = _inscrire(email="course@example.com")
    assert r.status_code == 409


def test_mot_de_passe_oublie_email_inexistant_renvoie_200():
    """Pas d'énumération de comptes : retour 200 que l'email existe ou non."""
    limiteur._reinitialiser()
    r = client.post("/mot-de-passe-oublie", json={"email": "jamais@example.com"})
    assert r.status_code == 200


def test_mot_de_passe_oublie_email_existant_appelle_envoyer(monkeypatch):
    """Avec un email existant, on appelle email_envoi.envoyer et on retourne 200."""
    limiteur._reinitialiser()
    _inscrire(email="exist@example.com")

    # Mock email_envoi.envoyer pour capturer l'appel
    appels = []
    import email_envoi
    original_envoyer = email_envoi.envoyer

    def mock_envoyer(dest, sujet, corps):
        appels.append({"dest": dest, "sujet": sujet, "corps": corps})
        return "simule"

    monkeypatch.setattr(email_envoi, "envoyer", mock_envoyer)

    r = client.post("/mot-de-passe-oublie", json={"email": "exist@example.com"})
    assert r.status_code == 200
    assert len(appels) == 1
    assert appels[0]["dest"] == "exist@example.com"
    assert "Réinitialisation de mot de passe" in appels[0]["sujet"]


def test_reinitialiser_mot_de_passe_avec_jeton_valide():
    """Avec un jeton valide, on peut définir un nouveau mot de passe."""
    limiteur._reinitialiser()
    _inscrire(email="change@example.com", mdp="ancienmdp12345")

    # Générer un jeton de reset valide
    import stockage
    compte = stockage.lire_compte_par_email("change@example.com")
    import jeton
    jeton_reset = jeton.emettre_reinitialisation(compte["id"], ttl=60)

    # Utiliser le jeton pour changer le mot de passe
    r = client.post("/reinitialiser-mot-de-passe",
                    json={"jeton": jeton_reset, "nouveau_mot_de_passe": "nouveaumdp456"})
    assert r.status_code == 200

    # Vérifier que l'ancien mot de passe ne fonctionne plus
    r2 = client.post("/connexion",
                     json={"email": "change@example.com", "mot_de_passe": "ancienmdp12345"})
    assert r2.status_code == 401

    # Vérifier que le nouveau mot de passe fonctionne
    r3 = client.post("/connexion",
                     json={"email": "change@example.com", "mot_de_passe": "nouveaumdp456"})
    assert r3.status_code == 200


def test_reinitialiser_mot_de_passe_jeton_invalide_renvoie_400():
    limiteur._reinitialiser()
    r = client.post("/reinitialiser-mot-de-passe",
                    json={"jeton": "jeton-invalide", "nouveau_mot_de_passe": "nouveaumdp456"})
    assert r.status_code == 400
    assert "invalide ou expiré" in r.json()["detail"]


def test_reinitialiser_mot_de_passe_jeton_expire_renvoie_400():
    limiteur._reinitialiser()
    _inscrire(email="expire@example.com", mdp="motdepasse123")
    import stockage
    compte = stockage.lire_compte_par_email("expire@example.com")
    import jeton
    jeton_expire = jeton.emettre_reinitialisation(compte["id"], ttl=-1)

    r = client.post("/reinitialiser-mot-de-passe",
                    json={"jeton": jeton_expire, "nouveau_mot_de_passe": "nouveaumdp456"})
    assert r.status_code == 400
    assert "invalide ou expiré" in r.json()["detail"]


def test_reinitialiser_mot_de_passe_jeton_rejeu_renvoie_400():
    """Rejouer le même jeton deux fois doit échouer la deuxième fois."""
    limiteur._reinitialiser()
    _inscrire(email="rejeu@example.com", mdp="motdepasse123")
    import stockage
    compte = stockage.lire_compte_par_email("rejeu@example.com")
    import jeton
    jeton_reset = jeton.emettre_reinitialisation(compte["id"], ttl=60)

    # Première utilisation : succès
    r1 = client.post("/reinitialiser-mot-de-passe",
                     json={"jeton": jeton_reset, "nouveau_mot_de_passe": "nouveaumdp456"})
    assert r1.status_code == 200

    # Deuxième utilisation du même jeton : échec
    r2 = client.post("/reinitialiser-mot-de-passe",
                     json={"jeton": jeton_reset, "nouveau_mot_de_passe": "autremdp789"})
    assert r2.status_code == 400
    assert "déjà été utilisé" in r2.json()["detail"]


def test_rate_limiting_sur_mot_de_passe_oublie():
    """Rate limiting sur /mot-de-passe-oublie (même motif que sur /connexion)."""
    limiteur._reinitialiser()
    for _ in range(limiteur.MAX_TENTATIVES):
        client.post("/mot-de-passe-oublie", json={"email": "x@example.com"})
    r = client.post("/mot-de-passe-oublie", json={"email": "x@example.com"})
    assert r.status_code == 429
