from masque import masquer


def test_jeton_long_masque():
    assert "abcdef0123456789abcdef0123456789abcd" not in masquer("tok abcdef0123456789abcdef0123456789abcd")


def test_jeton_hexa_40_masque():
    h = "a" * 20 + "0123456789" + "b" * 10
    assert len(h) == 40 and h not in masquer(f"sha {h}")


def test_email_masque():
    assert "a@b.fr" not in masquer("contact a@b.fr ok")


def test_bearer_masque():
    assert "XYZ" not in masquer("Authorization: Bearer XYZ.abc")


def test_mdp_dans_url_masque():
    assert "s3cr3t" not in masquer("git clone http://u:s3cr3t@h/x.git")


def test_query_secret_masque():
    assert "abc123" not in masquer("GET /x?token=abc123&y=1")


def test_texte_normal_intact():
    assert masquer("build ok en 12s") == "build ok en 12s"
