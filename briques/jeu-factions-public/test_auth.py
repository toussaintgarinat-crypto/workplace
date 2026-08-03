import re

from fastapi.testclient import TestClient

import jeton as jeton_mod
import limiteur
import stockage
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

    # Le lien réellement reçu dans la boîte mail doit être utilisable tel quel : on extrait le
    # jeton du corps de l'email et on s'en sert vraiment, au lieu d'en fabriquer un à côté
    # (S220, revue Task 14 — le test se contentait d'un mock appelé).
    m = re.search(r"jeton=([^\s&]+)", appels[0]["corps"])
    assert m, f"aucun lien avec jeton dans le corps : {appels[0]['corps']!r}"
    r2 = client.post("/reinitialiser-mot-de-passe",
                     json={"jeton": m.group(1), "nouveau_mot_de_passe": "issudulien789"})
    assert r2.status_code == 200
    assert client.post("/connexion", json={"email": "exist@example.com",
                                           "mot_de_passe": "issudulien789"}).status_code == 200


def test_mot_de_passe_oublie_renvoie_200_meme_si_lenvoi_smtp_echoue(monkeypatch):
    """Anti-énumération : un email inconnu répond 200, donc un email CONNU dont l'envoi SMTP
    échoue doit répondre 200 lui aussi — sinon la différence 500/200 rend les comptes
    énumérables, et précisément en production (SMTP configuré) (S220, revue Task 14)."""
    limiteur._reinitialiser()
    _inscrire(email="smtp-casse@example.com")

    import email_envoi

    def envoyer_qui_casse(dest, sujet, corps):
        raise OSError("SMTP injoignable")

    monkeypatch.setattr(email_envoi, "envoyer", envoyer_qui_casse)

    r = client.post("/mot-de-passe-oublie", json={"email": "smtp-casse@example.com"})
    assert r.status_code == 200
    # ... et strictement le même corps de réponse que pour un email inconnu.
    inconnu = client.post("/mot-de-passe-oublie", json={"email": "jamais-vu@example.com"})
    assert (r.status_code, r.json()) == (inconnu.status_code, inconnu.json())


def test_reinitialisation_invalide_les_sessions_deja_ouvertes():
    """Cœur du fix S220 (revue Task 14) : si on réinitialise son mot de passe parce que
    quelqu'un d'autre a accès au compte, le cookie déjà émis à cet autre ne doit PAS survivre
    au reset — sans époque de session il restait valide jusqu'à 30 jours."""
    limiteur._reinitialiser()
    _inscrire(email="vole@example.com", mdp="ancienmdp12345")

    # Vrai cookie de session, obtenu par une vraie connexion (pas forgé).
    r_co = client.post("/connexion", json={"email": "vole@example.com",
                                           "mot_de_passe": "ancienmdp12345"})
    assert r_co.status_code == 200
    ancien_cookie = {jeton_mod.COOKIE_NOM: r_co.cookies.get(jeton_mod.COOKIE_NOM)}
    client.cookies.clear()
    assert client.get("/personnages", cookies=ancien_cookie).status_code == 200

    compte = stockage.lire_compte_par_email("vole@example.com")
    jeton_reset = jeton_mod.emettre_reinitialisation(compte["id"], ttl=60)
    assert client.post("/reinitialiser-mot-de-passe",
                       json={"jeton": jeton_reset,
                             "nouveau_mot_de_passe": "nouveaumdp456"}).status_code == 200

    # L'ancienne session est morte...
    assert client.get("/personnages", cookies=ancien_cookie).status_code == 401

    # ... et une nouvelle connexion redonne bien un accès qui fonctionne.
    r_neuf = client.post("/connexion", json={"email": "vole@example.com",
                                             "mot_de_passe": "nouveaumdp456"})
    assert r_neuf.status_code == 200
    nouveau_cookie = {jeton_mod.COOKIE_NOM: r_neuf.cookies.get(jeton_mod.COOKIE_NOM)}
    client.cookies.clear()
    assert client.get("/personnages", cookies=nouveau_cookie).status_code == 200
    assert nouveau_cookie != ancien_cookie


def test_deux_reinitialisations_successives_invalident_chacune_leur_session():
    """L'époque avance à chaque reset : la session ouverte entre les deux resets meurt aussi."""
    limiteur._reinitialiser()
    _inscrire(email="deuxresets@example.com", mdp="ancienmdp12345")
    compte = stockage.lire_compte_par_email("deuxresets@example.com")

    # ttl différents à dessein : emettre_reinitialisation n'a pas de nonce et n'a qu'une
    # seconde de résolution, deux jetons émis dans la même seconde seraient identiques donc
    # le second serait refusé comme rejeu (et le test passerait pour de mauvaises raisons).
    assert client.post("/reinitialiser-mot-de-passe",
                       json={"jeton": jeton_mod.emettre_reinitialisation(compte["id"], ttl=60),
                             "nouveau_mot_de_passe": "intermediaire123"}).status_code == 200
    r_co = client.post("/connexion", json={"email": "deuxresets@example.com",
                                           "mot_de_passe": "intermediaire123"})
    assert r_co.status_code == 200
    cookie_intermediaire = {jeton_mod.COOKIE_NOM: r_co.cookies.get(jeton_mod.COOKIE_NOM)}
    client.cookies.clear()
    assert client.get("/personnages", cookies=cookie_intermediaire).status_code == 200

    assert client.post("/reinitialiser-mot-de-passe",
                       json={"jeton": jeton_mod.emettre_reinitialisation(compte["id"], ttl=61),
                             "nouveau_mot_de_passe": "final456789"}).status_code == 200
    assert client.get("/personnages", cookies=cookie_intermediaire).status_code == 401
    assert stockage.lire_epoch_session(compte["id"]) == 2


def test_identite_fabriquee_sans_compte_reel_reste_acceptee():
    """Le contrôle d'époque est volontairement lenient : une identité sans ligne dans `comptes`
    (motif de longue date des tests de logique de jeu) passe comme avant. N'ajoute aucun risque
    — cle_api ne vérifiait déjà pas l'existence du compte (S220, revue Task 14)."""
    client.cookies.clear()
    forge = {jeton_mod.COOKIE_NOM: jeton_mod.emettre("identite-sans-compte", ttl=3600)}
    assert client.get("/personnages", cookies=forge).status_code == 200


def test_jeton_de_reinitialisation_glisse_comme_cookie_de_session_401():
    """Défense en profondeur : le jeton de reset ne doit jamais servir de session."""
    limiteur._reinitialiser()
    _inscrire(email="glisse@example.com")
    compte = stockage.lire_compte_par_email("glisse@example.com")
    client.cookies.clear()
    reset = {jeton_mod.COOKIE_NOM: jeton_mod.emettre_reinitialisation(compte["id"], ttl=60)}
    assert client.get("/personnages", cookies=reset).status_code == 401


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
