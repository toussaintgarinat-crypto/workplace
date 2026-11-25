"""Câblage S247 : la preuve vient du RÉSULTAT de la brique, jamais du LLM."""
import asyncio
import json
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import outils  # noqa: E402


class _Reg:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _Reg({"livraison": {"nom": "livraison", "port": 6240, "capacites": [
    {"nom": "livraison_verifier_sauvegarde", "chemin": "/v", "methode": "POST", "action": False,
     "fournit_preuve": "preuve_sauvegarde", "description": "Vérifie.",
     "params": {"app": {"type": "string", "requis": True}}},
    {"nom": "livraison_reset_app", "chemin": "/r", "methode": "POST", "action": True,
     "sensibilite": "donnees", "prerequis": ["preuve_sauvegarde"], "description": "Reset.",
     "params": {"app": {"type": "string", "requis": True}}},
]}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    etat = {"notifs": [], "resultat_verif": None, "executes": []}

    async def faux_notifier(registre, demande):
        etat["notifs"].append((demande["id"], dict(demande["prerequis"])))

    async def faux_executer(nom, args, registre):
        if nom == "livraison_verifier_sauvegarde":
            return etat["resultat_verif"]
        etat["executes"].append(nom)
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    monkeypatch.setattr(outils, "_executer", faux_executer)
    return etat


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def _verdict(**kw):
    d = {"ok": True, "verdict": "valide", "preuve_id": "P1", "app": "calendrier",
         "app_id": "A1", "expire_a": 4_000_000_000.0}
    d.update(kw)
    return json.dumps(d)


def test_est_prerequis_lit_le_manifeste():
    assert outils.est_prerequis("livraison_reset_app", REGISTRE) == ("preuve_sauvegarde",)
    assert outils.est_prerequis("livraison_verifier_sauvegarde", REGISTRE) == ()
    assert outils.est_prerequis("inconnu", REGISTRE) == ()


def test_demande_sans_preuve_notifie_sans_prerequis_ok(env):
    _run("livraison_reset_app", {"app": "calendrier"})
    assert env["notifs"] == [(env["notifs"][0][0], {"preuve_sauvegarde": False})]
    assert env["executes"] == []


def test_verdict_valide_libere_et_renotifie_avec_prerequis_ok(env):
    _run("livraison_reset_app", {"app": "calendrier"})
    env["resultat_verif"] = _verdict()
    _run("livraison_verifier_sauvegarde", {"app": "calendrier"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": True}
    assert len(env["notifs"]) == 2


def test_preuve_connue_a_la_creation_notifie_deja_satisfait(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_verifier_sauvegarde", {"app": "calendrier"})
    _run("livraison_reset_app", {"app": "Calendrier"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": True}


@pytest.mark.parametrize("resultat", [
    _verdict(verdict="invalide"),
    _verdict(ok=False),
    _verdict(preuve_id=""),
    json.dumps({"ok": True, "verdict": "valide", "preuve_id": "P1"}),      # pas d'expire_a
    _verdict(expire_a="demain"),
    "Erreur : brique injoignable",
    "pas du json",
])
def test_resultat_non_probant_n_enregistre_aucune_preuve(env, resultat):
    env["resultat_verif"] = resultat
    _run("livraison_verifier_sauvegarde", {"app": "calendrier"})
    _run("livraison_reset_app", {"app": "calendrier"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": False}


def test_le_llm_ne_peut_pas_fabriquer_une_preuve_en_argument(env):
    _run("livraison_reset_app", {"app": "calendrier", "preuve_sauvegarde": True,
                                 "verdict": "valide"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": False}
