import pytest

from envreecriture import reecrire_env

MDP = "S3cr&t/p@ss:w0rd"
URL = f"postgresql://temoin:{MDP}@db:5432/temoin"


def _env(valeur, avant="", apres=""):
    return f"# commentaire\n{avant}DATABASE_URL={valeur}\n{apres}"


def test_url_simple():
    assert reecrire_env(_env("postgresql://u:p@h:5432/temoin"), "DATABASE_URL", "temoin", "temoin_b") \
        == _env("postgresql://u:p@h:5432/temoin_b")


def test_parametres_conserves():
    r = reecrire_env(_env("postgresql://u:p@h/temoin?sslmode=disable"), "DATABASE_URL", "temoin", "n")
    assert r == _env("postgresql://u:p@h/n?sslmode=disable")


def test_guillemets_conserves():
    for q in ('"', "'"):
        r = reecrire_env(_env(f"{q}postgresql://u:p@h/temoin{q}"), "DATABASE_URL", "temoin", "n")
        assert r == _env(f"{q}postgresql://u:p@h/n{q}")


def test_mot_de_passe_avec_caracteres_speciaux_intact():
    r = reecrire_env(_env(URL), "DATABASE_URL", "temoin", "autre")
    assert r == _env(f"postgresql://temoin:{MDP}@db:5432/autre")


def test_schema_avec_plus():
    r = reecrire_env(_env("postgresql+psycopg://u:p@h/temoin"), "DATABASE_URL", "temoin", "n")
    assert r == _env("postgresql+psycopg://u:p@h/n")


def test_reste_identique_octet_pour_octet():
    env = ("# c\n\nA=1=2\n  # indente\nDATABASE_URL_X=postgresql://u:p@h/temoin\n"
           "B=\"x y\"\n\nDATABASE_URL=postgresql://u:p@h/temoin\nC=a=b=c\n")
    attendu = env.replace("\nDATABASE_URL=postgresql://u:p@h/temoin", "\nDATABASE_URL=postgresql://u:p@h/n")
    assert reecrire_env(env, "DATABASE_URL", "temoin", "n") == attendu


def test_fins_de_ligne_crlf_preservees():
    env = "A=1\r\nDATABASE_URL=postgresql://u:p@h/temoin\r\nB=2\r\n"
    assert reecrire_env(env, "DATABASE_URL", "temoin", "n") \
        == "A=1\r\nDATABASE_URL=postgresql://u:p@h/n\r\nB=2\r\n"
    env = 'DATABASE_URL="postgresql://u:p@h/temoin"\r\n'
    assert reecrire_env(env, "DATABASE_URL", "temoin", "n") == 'DATABASE_URL="postgresql://u:p@h/n"\r\n'


def test_sans_retour_final():
    assert reecrire_env("DATABASE_URL=postgresql://u:p@h/temoin", "DATABASE_URL", "temoin", "n") \
        == "DATABASE_URL=postgresql://u:p@h/n"


def test_variable_absente():
    with pytest.raises(ValueError):
        reecrire_env("A=1\n", "DATABASE_URL", "temoin", "n")
    with pytest.raises(ValueError):
        reecrire_env("", "DATABASE_URL", "temoin", "n")


def test_prefixe_export_non_supporte():
    with pytest.raises(ValueError):
        reecrire_env("export DATABASE_URL=postgresql://u:p@h/temoin\n", "DATABASE_URL", "temoin", "n")


def test_variable_ambigue():
    ligne = "DATABASE_URL=postgresql://u:p@h/temoin\n"
    with pytest.raises(ValueError):
        reecrire_env(ligne + ligne, "DATABASE_URL", "temoin", "n")


def test_base_differente():
    with pytest.raises(ValueError):
        reecrire_env(_env("postgresql://u:p@h/autre"), "DATABASE_URL", "temoin", "n")


def test_prefixe_de_base_non_modifie():
    for v in ("postgresql://u:p@h/temoin2", "postgresql://u:p@h/temoin2?x=1"):
        with pytest.raises(ValueError):
            reecrire_env(_env(v), "DATABASE_URL", "temoin", "n")


def test_variable_au_nom_proche_non_touchee():
    with pytest.raises(ValueError):
        reecrire_env("MY_DATABASE_URL=postgresql://u:p@h/temoin\n", "DATABASE_URL", "temoin", "n")


def test_erreurs_ne_citent_jamais_la_valeur():
    cas = [
        (_env(f"postgresql://temoin:{MDP}@db/autre"), "DATABASE_URL"),
        (_env(URL) + _env(URL), "DATABASE_URL"),
        (_env(URL), "ABSENTE"),
        (f"DATABASE_URL=postgresql://temoin:{MDP}@db/autre\r\n", "DATABASE_URL"),
    ]
    for env, var in cas:
        with pytest.raises(ValueError) as e:
            reecrire_env(env, var, "temoin", "n")
        for s in (str(e.value), repr(e.value)):
            assert MDP not in s and "postgresql://" not in s and "S3cr" not in s


@pytest.mark.parametrize("url", [
    "postgresql://u:a/temoin?@h/temoin",      # « ? » dans le mot de passe : segment ambigu
    "postgresql://u:a/temoin#@h/temoin",
    "postgresql://h//temoin",                 # chemin vide avant la base
])
def test_urls_douteuses_refusees_sans_citer_la_valeur(url):
    with pytest.raises(ValueError) as e:
        reecrire_env("DATABASE_URL=" + url, "DATABASE_URL", "temoin", "temoin_v0a1b2c3d")
    assert "temoin" not in str(e.value) and "u:a" not in repr(e.value)
