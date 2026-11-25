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


# ── I4 : contournements relevés par la revue ──
def test_json_mot_de_passe_court():
    t = masquer('{"password":"hunter2-Short","user":"bob"}')
    assert "hunter2" not in t and '"password"' in t and "bob" in t


def test_variable_env_password():
    t = masquer("DB_PASSWORD=Sup3rS3cret!")
    assert "Sup3rS3cret" not in t and t.startswith("DB_PASSWORD=")


def test_export_github_token():
    t = masquer("export GITHUB_TOKEN=ghp_abcdEFGH1234")
    assert "ghp_abcdEFGH1234" not in t and "GITHUB_TOKEN" in t


def test_entete_x_api_key():
    t = masquer("x-api-key: dk_abc123def456")
    assert "dk_abc123def456" not in t and "x-api-key" in t


def test_authorization_basic():
    t = masquer("Authorization: Basic dXNlcjpwYXNzd29yZA==")
    assert "dXNlcjpwYXNzd29yZA" not in t


def test_base64_avec_plus_slash_egal():
    b = "QWxhZGRpbjpvcGVu+c2VzYW1l/ZGVhZGJlZWY="
    t = masquer(f"payload {b} fin")
    assert "QWxhZGRpbjpvcGVu" not in t and "ZGVhZGJlZWY" not in t and "fin" in t


def test_jeton_de_20_caracteres_masque():
    assert "AbCdEfGhIj0123456789" not in masquer("id AbCdEfGhIj0123456789 ok")


def test_sha_courts_et_durees_lisibles():
    for ligne in ("commit 3f2a9c1 build ok", "HEAD is now at 0cea614abc12", "build ok en 12s",
                  "Step 4/9 : RUN pip install -r requirements.txt"):
        assert masquer(ligne) == ligne


def test_chemins_usuels_lisibles():
    for ligne in ("/usr/local/lib/python3.12/site-packages/fastapi/applications.py",
                  "COPY requirements.txt /app/requirements.txt",
                  "/home/debian/workplace/briques/livraison/main.py",
                  "node_modules/.bin/vite build"):
        assert masquer(ligne) == ligne
