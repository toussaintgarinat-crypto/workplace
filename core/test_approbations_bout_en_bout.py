"""S245b — parcours complet côté Cœur : demande → approbation → exécution par le Cœur."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import approbations_canal  # noqa: E402
import approbations_reprise  # noqa: E402
import contexte_tenant  # noqa: E402
import outils  # noqa: E402
from test_approbations_garde import REGISTRE  # noqa: E402


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    vu = {"exec": [], "notifs": []}

    async def _exe(nom, args, registre):
        vu["exec"].append((nom, contexte_tenant.contexte_actuel().utilisateur))
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


def test_parcours_complet_alice(_env):
    # 1. Alice (co-agent) demande : refus + demande créée pour ELLE.
    refus = _en_tant_que("alice", lambda: outils.executer("app_redemarrer", {"app": "crm"}, REGISTRE))
    assert "NON exécutée" in refus and _env["notifs"] == ["alice"] and _env["exec"] == []
    (demande,) = approbations.en_attente(utilisateur="alice")
    assert approbations.en_attente(utilisateur="bob") == []

    # 2. Bob tente d'approuver : refusé. Alice approuve.
    assert approbations.approuver(demande["id"], "tg:2", "telegram",
                                  utilisateur="bob") == (False, "introuvable")
    assert approbations.approuver(demande["id"], "tg:1", "telegram",
                                  utilisateur="alice") == (True, "ok")

    # 3. Le Cœur exécute, en tant qu'Alice, sans nouveau cycle d'approbation.
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, demande["id"])) == "executee"
    assert _env["exec"] == [("app_redemarrer", "alice")] and _env["notifs"] == ["alice"]

    # 4. Le LLM qui rappelle l'outil juste après ne relance rien.
    refus2 = _en_tant_que("alice", lambda: outils.executer("app_redemarrer", {"app": "crm"}, REGISTRE))
    assert "déjà" in refus2 and len(_env["exec"]) == 1 and _env["notifs"] == ["alice"]
    assert approbations.args_de(demande["id"]) is None            # args purgés
