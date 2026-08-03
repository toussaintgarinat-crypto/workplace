import jeton as J


def test_roundtrip_emettre_puis_verifier():
    j = J.emettre("compte-alice", ttl=60)
    assert J.verifier(j) == ("compte-alice", 0)


def test_roundtrip_conserve_une_epoque_non_nulle():
    """L'époque de session voyage dans le jeton signé — c'est elle que main.py compare à
    l'époque en base pour invalider les sessions antérieures à un reset (S220, revue Task 14)."""
    j = J.emettre("compte-alice", epoque=5, ttl=60)
    assert J.verifier(j) == ("compte-alice", 5)


def test_epoque_nest_pas_falsifiable_sans_le_secret():
    """Rejouer le même compte avec une autre époque exige une signature valide."""
    j = J.emettre("compte-alice", epoque=5, ttl=60)
    compte_id, epoque, expire, signature = j.rsplit(":", 3)
    forge = f"{compte_id}:0:{expire}:{signature}"
    assert J.verifier(forge) is None


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
    """Un jeton de session (format 4 segments) soumis à verifier_reinitialisation doit
    retourner None : son premier segment est le compte_id, jamais le préfixe "reset"."""
    session_token = J.emettre("compte-alice", ttl=60)
    assert J.verifier_reinitialisation(session_token) is None
    assert J.verifier_reinitialisation(J.emettre("compte-alice", epoque=3, ttl=60)) is None


def test_reset_token_rejeté_par_verifier_session():
    """Un jeton de reset soumis à verifier (session) doit retourner None SANS lever — avec le
    format 4 segments (S220, revue Task 14), rsplit(":", 3) place le compte_id à l'emplacement
    de l'époque, dont la conversion int() échoue : ValueError attrapée, None renvoyé. Le jeton
    de reset ne peut donc plus du tout être glissé comme cookie de session."""
    assert J.verifier(J.emettre_reinitialisation("compte-alice", ttl=60)) is None
    # Même avec un compte_id réaliste (hex uuid), non convertible en entier.
    assert J.verifier(J.emettre_reinitialisation("9f1c2ab34de5", ttl=60)) is None
