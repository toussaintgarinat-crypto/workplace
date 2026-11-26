import json

import inventaire

BASE = {"base": "temoin", "service": "postgres-abc-def", "utilisateur": "temoin",
        "sauvegarde_id": "B1", "prefixe_s3": "postgres-abc-def/s247-pg"}


def _ecrire(tmp_path, monkeypatch, contenu):
    p = tmp_path / "inv.json"
    p.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu))
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(p))


def test_entree_valide_insensible_a_la_casse(tmp_path, monkeypatch):
    _ecrire(tmp_path, monkeypatch, {"calendrier-familial": {"bases": [BASE], "volumes": []}})
    assert inventaire.lire("  Calendrier-Familial ")["bases"][0]["base"] == "temoin"


def test_defaut_dans_livraison_data(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVRAISON_INVENTAIRE", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "inventaire.json").write_text(json.dumps({"a": {"bases": [BASE]}}))
    assert inventaire.lire("a")["volumes"] == []


def test_app_inconnue_fichier_absent_ou_corrompu_donnent_none(tmp_path, monkeypatch):
    _ecrire(tmp_path, monkeypatch, {"a": {"bases": [BASE]}})
    assert inventaire.lire("b") is None
    _ecrire(tmp_path, monkeypatch, "{pas du json")
    assert inventaire.lire("a") is None
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(tmp_path / "absent.json"))
    assert inventaire.lire("a") is None


def test_entree_invalide_fail_closed(tmp_path, monkeypatch):
    for mauvais in ({"bases": [{"base": "x"}]}, {"bases": "x"}, {"bases": [BASE], "volumes": [{}]},
                    {"bases": [{**BASE, "prefixe_s3": "../x"}]}, {"bases": []}, [], "x"):
        _ecrire(tmp_path, monkeypatch, {"a": mauvais})
        assert inventaire.lire("a") is None, mauvais


REEL = {"base": "temoin", "service": "postgres-bypass-virtual-circuit-nmmcyt", "utilisateur": "temoin",
        "sauvegarde_id": "B1", "prefixe_s3": "postgres-bypass-virtual-circuit-nmmcyt/s247-pg"}


def test_valeurs_reelles_du_spike_acceptees(tmp_path, monkeypatch):
    _ecrire(tmp_path, monkeypatch, {"a": {"bases": [REEL]}})
    assert inventaire.lire("a")["bases"][0]["service"] == "postgres-bypass-virtual-circuit-nmmcyt"


def test_memes_regles_que_l_executeur(tmp_path, monkeypatch):
    mauvais = [{"base": "temoin\n"}, {"base": "Temoin"}, {"service": "abc-def-ghi"},
               {"service": "postgres-abc\n"}, {"utilisateur": "mon-user"},
               {"prefixe_s3": "a//b"}, {"prefixe_s3": "a/./b"}, {"prefixe_s3": "a/"},
               {"prefixe_s3": "a/b\n"}, {"prefixe_s3": "./a"}, {"prefixe_s3": "a/."}]
    for m in mauvais:
        _ecrire(tmp_path, monkeypatch, {"a": {"bases": [{**BASE, **m}]}})
        assert inventaire.lire("a") is None, m


RESET = {"variable_env": "DATABASE_URL", "domaine_public": "app.example.com",
         "domaine_test": "test.example.com", "port_app": 3000, "sante_chemin": "/api/health"}


def _lire_reset(tmp_path, monkeypatch, reset, bases=None):
    entree = {"bases": [BASE] if bases is None else bases, "volumes": []}
    if reset is not ABSENT:
        entree["reset"] = reset
    _ecrire(tmp_path, monkeypatch, {"a": entree})
    return inventaire.lire("a")


ABSENT = object()


def test_reset_valide_renvoye(tmp_path, monkeypatch):
    r = _lire_reset(tmp_path, monkeypatch, RESET)
    assert r["reset"] == RESET and r["bases"][0]["base"] == "temoin"


def test_reset_absent_entree_valide_sans_reset(tmp_path, monkeypatch):
    r = _lire_reset(tmp_path, monkeypatch, ABSENT)
    assert r is not None and r["reset"] is None


def test_reset_champ_invalide_invalide_toute_l_entree(tmp_path, monkeypatch):
    mauvais = [{"variable_env": "database_url"}, {"variable_env": "1A"}, {"variable_env": "A\n"},
               {"variable_env": "A" * 62}, {"variable_env": ""},
               {"domaine_public": "App.example.com"}, {"domaine_public": "-a.com"},
               {"domaine_public": "a.com\n"}, {"domaine_public": "a.com-"}, {"domaine_public": ""},
               {"domaine_test": "a b.com"}, {"domaine_test": "x" * 254},
               {"domaine_test": "app.example.com"},  # identique au public
               {"port_app": 0}, {"port_app": 65536}, {"port_app": True}, {"port_app": "3000"},
               {"port_app": 3000.0}, {"port_app": None},
               {"sante_chemin": "api"}, {"sante_chemin": "/a b"}, {"sante_chemin": "/a/../b"},
               {"sante_chemin": "/a\n"}, {"sante_chemin": "/" + "a" * 101}, {"sante_chemin": 5}]
    for m in mauvais:
        assert _lire_reset(tmp_path, monkeypatch, {**RESET, **m}) is None, m


def test_reset_champ_manquant_ou_en_trop_ou_mal_type(tmp_path, monkeypatch):
    for c in RESET:
        assert _lire_reset(tmp_path, monkeypatch, {k: v for k, v in RESET.items() if k != c}) is None, c
    for mauvais in ({**RESET, "extra": 1}, [], "x", None, {}):
        assert _lire_reset(tmp_path, monkeypatch, mauvais) is None, mauvais


def test_reset_limites_acceptees(tmp_path, monkeypatch):
    for m in ({"port_app": 1}, {"port_app": 65535}, {"sante_chemin": "/"}, {"domaine_test": "t"},
              {"sante_chemin": "/a.b_c~d/e-f"}):
        assert _lire_reset(tmp_path, monkeypatch, {**RESET, **m}) is not None, m


def test_reset_exige_exactement_une_base(tmp_path, monkeypatch):
    autre = {**BASE, "base": "autre", "sauvegarde_id": "B2", "prefixe_s3": "postgres-abc-def/autre"}
    assert _lire_reset(tmp_path, monkeypatch, RESET, bases=[BASE, autre]) is None
    _ecrire(tmp_path, monkeypatch, {"a": {"volumes": [{"volume_backup_id": "V"}], "reset": RESET}})
    assert inventaire.lire("a") is None
    # sans reset, plusieurs bases restent valides
    assert _lire_reset(tmp_path, monkeypatch, ABSENT, bases=[BASE, autre]) is not None
