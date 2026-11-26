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
