import jeton as J


def test_roundtrip_emettre_puis_verifier():
    j = J.emettre("compte-alice", ttl=60)
    assert J.verifier(j) == "compte-alice"


def test_verifier_signature_invalide():
    j = J.emettre("compte-alice", ttl=60)
    trafique = j[:-1] + ("0" if j[-1] != "0" else "1")
    assert J.verifier(trafique) is None


def test_verifier_expire():
    j = J.emettre("compte-alice", ttl=-1)
    assert J.verifier(j) is None


def test_verifier_malforme():
    assert J.verifier("pas-un-jeton-valide") is None
    assert J.verifier(None) is None


def test_verifier_sans_secret_configure(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_PUBLIC_SECRET", raising=False)
    assert J.verifier("nimporte:quoi:x") is None


def test_hacher_puis_verifier_mot_de_passe():
    h = J.hacher_mot_de_passe("motdepasse123")
    assert J.verifier_mot_de_passe("motdepasse123", h) is True


def test_verifier_mauvais_mot_de_passe():
    h = J.hacher_mot_de_passe("motdepasse123")
    assert J.verifier_mot_de_passe("autrechose", h) is False


def test_hachage_nest_jamais_le_mot_de_passe_en_clair():
    h = J.hacher_mot_de_passe("motdepasse123")
    assert h != "motdepasse123"


def test_verifier_mot_de_passe_avec_hash_none_renvoie_false():
    assert J.verifier_mot_de_passe("motdepasse123", None) is False


def test_roundtrip_emettre_reinitialisation_puis_verifier():
    j = J.emettre_reinitialisation("compte-alice", ttl=60)
    assert J.verifier_reinitialisation(j) == "compte-alice"


def test_verifier_reinitialisation_expire():
    j = J.emettre_reinitialisation("compte-alice", ttl=-1)
    assert J.verifier_reinitialisation(j) is None


def test_verifier_reinitialisation_signature_invalide():
    j = J.emettre_reinitialisation("compte-alice", ttl=60)
    trafique = j[:-1] + ("0" if j[-1] != "0" else "1")
    assert J.verifier_reinitialisation(trafique) is None


def test_verifier_reinitialisation_malforme():
    assert J.verifier_reinitialisation("pas-un-jeton-valide") is None
    assert J.verifier_reinitialisation(None) is None


def test_verifier_reinitialisation_sans_secret_configure(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_PUBLIC_SECRET", raising=False)
    assert J.verifier_reinitialisation("nimporte:quoi:x") is None


def test_session_token_rejeté_par_verifier_reinitialisation():
    """Un jeton de session soumis à verifier_reinitialisation doit retourner None."""
    session_token = J.emettre("compte-alice", ttl=60)
    assert J.verifier_reinitialisation(session_token) is None


def test_reset_token_accepté_par_verifier_session_contient_colon():
    """Un jeton de reset soumis à verifier (session) ne lève pas, mais retourne
    une chaîne contenant ':' (le préfixe 'reset:' reste visible). Cela documente
    le comportement de défense en profondeur sans dépendre d'une vraie table."""
    reset_token = J.emettre_reinitialisation("compte-alice", ttl=60)
    resultat = J.verifier(reset_token)
    # Le résultat doit être la chaîne "reset:compte-alice", laquelle contient ':'
    assert resultat is not None
    assert ":" in resultat
