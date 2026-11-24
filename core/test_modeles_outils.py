"""Choix de modèle par l'assistant (S244b) : routage par tâche + outils modeles_*.

$ cd core && python3 -m pytest test_modeles_outils.py -v
"""
import asyncio
import json
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import pytest  # noqa: E402

import config_assistant  # noqa: E402
import droits  # noqa: E402
import modeles_gateway as mg  # noqa: E402
import routage  # noqa: E402
from outils_domaines import modeles as om  # noqa: E402


@pytest.fixture(autouse=True)
def _conf(tmp_path, monkeypatch):
    monkeypatch.setattr(config_assistant, "CONFIG_PATH", tmp_path / "c.json")


def msg(t):
    return [{"role": "user", "content": t}]


@pytest.mark.parametrize("texte,att", [
    ("Corrige ce bug dans ma fonction python", "code"),
    ("Démontre que racine de 2 est irrationnelle", "raisonnement"),
    ("Écris un poème sur la mer", "redaction"),
    ("x " * 4000, "long"),
    ("Bonjour", None)])
def test_tache(texte, att):
    assert routage.tache(msg(texte)) == att


def test_routage_tache_en_tete_filet_conserve():
    conf = {"modeles_taches": {"code": "perso/zai/glm-5.3"}}
    m, routed, _ = routage.router(msg("Corrige ce bug python"), ["a", "b"], conf, tools=[{"x": 1}])
    assert m == ["perso/zai/glm-5.3", "a", "b"] and routed == "perso/zai/glm-5.3"


def test_sans_association_rien_ne_change():
    m, routed, _ = routage.router(msg("Corrige ce bug python"), ["a", "b"], {}, None)
    assert m == ["a", "b"] and routed is None


def test_definir_modele_tache_et_retrait():
    config_assistant.definir_modele_tache("code", "perso/x/y")
    assert config_assistant.charger()["modeles_taches"] == {"code": "perso/x/y"}
    config_assistant.definir_modele_tache("code", "")
    assert config_assistant.charger()["modeles_taches"] == {}
    with pytest.raises(ValueError):
        config_assistant.definir_modele_tache("nimporte", "x")


def test_modele_choisir_est_reserve_admin():
    assert droits.est_reserve_admin("modele_choisir")
    assert not droits.est_reserve_admin("modeles_disponibles")


def _run(nom, args):
    return json.loads(asyncio.run(om.dispatch(nom, args, None, None)))


def test_choisir_ajoute_teste_puis_selectionne(monkeypatch):
    appels = []

    async def lister():
        return []

    async def ajouter(f, m):
        appels.append((f, m))
        return {"ok": True, "nom": mg.nom_perso(f, m), "detail": "ok"}
    monkeypatch.setattr(mg, "lister", lister)
    monkeypatch.setattr(mg, "ajouter", ajouter)
    r = _run("modele_choisir", {"fournisseur": "mistral", "modele": "zai-glm-5-3", "pour": "code"})
    assert r["ok"] and appels == [("mistral", "zai-glm-5-3")]
    assert config_assistant.charger()["modeles_taches"] == {"code": "perso/mistral/zai-glm-5-3"}


def test_choisir_test_echoue_ne_selectionne_pas(monkeypatch):
    async def lister():
        return []

    async def ajouter(f, m):
        return {"ok": False, "nom": "n", "detail": "HTTP 401"}
    monkeypatch.setattr(mg, "lister", lister)
    monkeypatch.setattr(mg, "ajouter", ajouter)
    r = _run("modele_choisir", {"fournisseur": "zai", "modele": "glm-5.3"})
    assert not r["ok"] and "401" in r["erreur"]
    assert config_assistant.charger()["model"] == config_assistant.DEFAUT_MODEL


def test_choisir_refuse_fournisseur_et_tache_invalides():
    assert not _run("modele_choisir", {"fournisseur": "evil", "modele": "x"})["ok"]
    assert not _run("modele_choisir", {"fournisseur": "zai", "modele": "x", "pour": "nimp"})["ok"]


def test_retrait_association():
    config_assistant.definir_modele_tache("code", "perso/x/y")
    assert _run("modele_choisir", {"pour": "code"})["ok"]
    assert config_assistant.charger()["modeles_taches"] == {}
