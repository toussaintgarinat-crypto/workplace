"""S246 — les 3 actions de la brique `livraison` sont réellement gardées par le Cœur.

On charge le VRAI `briques/livraison/manifest.json` dans un registre de test (même forme que
`test_approbations_garde.REGISTRE`) : si quelqu'un retire `sensibilite` du manifeste, ce test casse."""
import asyncio
import json
import os
import pathlib
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import approbations_canal  # noqa: E402
import approbations_reprise  # noqa: E402
import catalogue  # noqa: E402
import contexte_tenant  # noqa: E402
import outils  # noqa: E402
from test_approbations_garde import _FauxRegistre  # noqa: E402

MANIFESTE = json.loads((pathlib.Path(__file__).resolve().parent.parent
                        / "briques" / "livraison" / "manifest.json").read_text())
REGISTRE = _FauxRegistre({"livraison": MANIFESTE})
ACTIONS = ("livraison_redemarrer", "livraison_deployer", "livraison_rollback")
LECTURES = ("livraison_apps", "livraison_etat", "livraison_logs")


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    vu = {"exec": [], "notifs": []}

    async def _exe(nom, args, registre):
        vu["exec"].append((nom, dict(args), contexte_tenant.contexte_actuel().utilisateur))
        return '{"ok": true}'

    async def _notif(registre, demande):
        vu["notifs"].append(demande["utilisateur"])

    async def _maj(registre, demande):
        pass

    monkeypatch.setattr(outils, "_executer", _exe)
    monkeypatch.setattr(outils, "_notifier_approbation", _notif)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", _maj)
    return vu


def _en_tant_que(utilisateur, coro_fn):
    jetons = contexte_tenant.definir_contexte(utilisateur=utilisateur)
    try:
        return asyncio.run(coro_fn())
    finally:
        contexte_tenant.reinitialiser(jetons)


def test_le_manifeste_reel_est_decouvert_par_le_catalogue():
    noms = {c["nom"] for c in catalogue.collecter_capacites(REGISTRE)}
    assert set(ACTIONS) | set(LECTURES) <= noms


def test_sensibilite_des_actions_et_des_lectures():
    for n in ACTIONS:
        assert outils.est_sensible(n, REGISTRE) == "reversible", n
    for n in LECTURES:
        assert outils.est_sensible(n, REGISTRE) is None, n


@pytest.mark.parametrize("nom", ACTIONS)
def test_sans_approbation_refus_et_aucun_appel(_env, nom):
    refus = _en_tant_que("alice", lambda: outils.executer(nom, {"app": "x"}, REGISTRE))
    assert "NON exécutée" in refus
    assert _env["exec"] == [] and _env["notifs"] == ["alice"]
    assert len(approbations.en_attente(utilisateur="alice")) == 1


def test_lecture_non_gardee(_env):
    _en_tant_que("alice", lambda: outils.executer("livraison_apps", {}, REGISTRE))
    assert [e[0] for e in _env["exec"]] == ["livraison_apps"] and _env["notifs"] == []


def test_approbation_puis_reprise_une_seule_execution(_env):
    refus = _en_tant_que("alice",
                         lambda: outils.executer("livraison_redemarrer", {"app": "x"}, REGISTRE))
    assert "NON exécutée" in refus and _env["exec"] == []
    (demande,) = approbations.en_attente(utilisateur="alice")
    assert approbations.en_attente(utilisateur="bob") == []

    # Un autre utilisateur ne peut pas approuver.
    assert approbations.approuver(demande["id"], "tg:2", "telegram",
                                  utilisateur="bob") == (False, "introuvable")
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, demande["id"])) == "ignoree"
    assert _env["exec"] == []

    assert approbations.approuver(demande["id"], "tg:1", "telegram",
                                  utilisateur="alice") == (True, "ok")
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, demande["id"])) == "executee"
    assert [(n, a["app"], u) for n, a, u in _env["exec"]] == [("livraison_redemarrer", "x", "alice")]

    # Rejouer la reprise ou rappeler l'outil ne relance rien.
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, demande["id"])) == "ignoree"
    refus2 = _en_tant_que("alice",
                          lambda: outils.executer("livraison_redemarrer", {"app": "x"}, REGISTRE))
    assert "déjà" in refus2 and len(_env["exec"]) == 1


def test_approbation_liee_aux_arguments(_env):
    _en_tant_que("alice", lambda: outils.executer("livraison_rollback", {"app": "x"}, REGISTRE))
    (demande,) = approbations.en_attente(utilisateur="alice")
    approbations.approuver(demande["id"], "tg:1", "telegram", utilisateur="alice")
    # Autre cible que celle approuvée : refusée, rien ne part.
    res = _en_tant_que("alice",
                       lambda: outils.executer("livraison_rollback", {"app": "autre"}, REGISTRE))
    assert "NON exécutée" in res and _env["exec"] == []
