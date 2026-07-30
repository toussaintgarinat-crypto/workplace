import jeton as J


def test_roundtrip_emettre_puis_verifier():
    j = J.emettre("sub-alice", ttl=60)
    assert J.verifier(j) == "sub-alice"


def test_verifier_signature_invalide():
    j = J.emettre("sub-alice", ttl=60)
    trafique = j[:-1] + ("0" if j[-1] != "0" else "1")
    assert J.verifier(trafique) is None


def test_verifier_expire():
    j = J.emettre("sub-alice", ttl=-1)
    assert J.verifier(j) is None


def test_verifier_malforme():
    assert J.verifier("pas-un-jeton-valide") is None
    assert J.verifier(None) is None


def test_verifier_sans_secret_configure(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_KEY", raising=False)
    assert J.verifier("nimporte:quoi:x") is None
