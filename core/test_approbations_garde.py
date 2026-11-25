"""La garde des capacités sensibles, DANS outils.executer (S245) — là où le trou vivait.

Même méthode que test_gate_action_bout_en_bout : on prouve le câblage, puis on vérifie que
neutraliser la garde fait échouer les tests de sécurité (et pas ceux de non-régression)."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "dokploy": {"nom": "dokploy", "port": 6300, "capacites": [
        {"nom": "app_redemarrer", "chemin": "/redemarrer", "methode": "POST", "action": True,
         "sensibilite": "reversible", "description": "Redémarre une app.",
         "params": {"app": {"type": "string", "requis": True}}},
        {"nom": "app_reset", "chemin": "/reset", "methode": "POST", "action": True,
         "sensibilite": "destructif", "description": "Remise à zéro.",
         "params": {"app": {"type": "string", "requis": True}}},
        {"nom": "app_logs", "chemin": "/logs", "sensibilite": "lecture",
         "description": "Lit les logs.", "params": {"app": {"type": "string"}}},
        {"nom": "app_ancienne", "chemin": "/x", "methode": "POST", "action": True,
         "description": "Action SANS sensibilite (comportement historique).",
         "params": {"app": {"type": "string"}}},
    ]},
})


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    notifs = []

    async def faux_notifier(registre, demande):
        notifs.append(demande["id"])

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    atteints = []

    async def faux_executer(nom, args, registre):
        atteints.append((nom, dict(args)))
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_executer", faux_executer)
    return {"notifs": notifs, "atteints": atteints}


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def test_est_sensible_lit_le_manifeste():
    assert outils.est_sensible("app_redemarrer", REGISTRE) == "reversible"
    assert outils.est_sensible("app_reset", REGISTRE) == "destructif"
    assert outils.est_sensible("app_logs", REGISTRE) is None       # lecture
    assert outils.est_sensible("app_ancienne", REGISTRE) is None   # pas de champ
    assert outils.est_sensible("inconnu", REGISTRE) is None


# ── Sécurité ─────────────────────────────────────────────────────────────────

def test_sans_approbation_rien_ne_s_execute_et_une_demande_est_creee(_env):
    res = _run("app_redemarrer", {"app": "crm", "confirme": True})   # même avec confirme=true
    assert _env["atteints"] == []
    assert "NON exécutée" in res and "Telegram" in res
    assert len(_env["notifs"]) == 1
    assert approbations.lire(_env["notifs"][0])["statut"] == "en_attente"


def test_le_llm_ne_peut_pas_se_confirmer_tout_seul(_env):
    for _ in range(3):
        _run("app_redemarrer", {"app": "crm", "confirme": True})
    assert _env["atteints"] == []
    assert len(_env["notifs"]) == 1          # une seule demande, pas de spam


def test_approuvee_puis_executee_une_fois(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram")
    res = _run("app_redemarrer", {"app": "crm"})
    assert _env["atteints"] == [("app_redemarrer", {"app": "crm", "confirme": True})]
    assert '"ok": true' in res
    _run("app_redemarrer", {"app": "crm"})                           # usage unique
    assert len(_env["atteints"]) == 1


def test_approbation_pour_crm_ne_vaut_pas_pour_autre(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram")
    _run("app_redemarrer", {"app": "autre"})
    assert _env["atteints"] == []


def test_refus_bloque_la_redemande_immediate(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.refuser(_env["notifs"][0], "tg:42", "telegram")
    res = _run("app_redemarrer", {"app": "crm"})
    assert "refusé" in res.lower()
    assert len(_env["notifs"]) == 1 and _env["atteints"] == []


def test_destructif_exige_le_code_pas_le_bouton(_env):
    _run("app_reset", {"app": "crm"})
    id_ = _env["notifs"][0]
    assert approbations.approuver(id_, "tg:42", "telegram") == (False, "code_requis")
    _run("app_reset", {"app": "crm"})
    assert _env["atteints"] == []
    approbations.armer_saisie_code(id_, "tg:42")
    approbations.valider_code_saisi("tg:42", approbations.lire(id_)["code"])
    _run("app_reset", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_reset"]


def test_un_echec_d_execution_est_journalise(_env, monkeypatch):
    async def casse(nom, args, registre):
        return "Erreur (dokploy) : boom"

    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram")
    monkeypatch.setattr(outils, "_executer", casse)
    _run("app_redemarrer", {"app": "crm"})
    assert approbations.lire(_env["notifs"][0])["statut"] == "echec"


# ── Non-régression (doivent passer AVANT et APRÈS la garde) ──────────────────

def test_lecture_passe_sans_approbation(_env):
    _run("app_logs", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_logs"] and _env["notifs"] == []


def test_capacite_sans_sensibilite_garde_le_comportement_historique(_env):
    _run("app_ancienne", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_ancienne"] and _env["notifs"] == []


# ── La garde ne doit pas dépendre du LLM ─────────────────────────────────────

def test_exiger_direct():
    id_, msg, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "résumé")
    assert id_ is None and msg and nouvelle["statut"] == "en_attente"
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "reversible", "résumé")
    assert id2 is None and msg2 and nouvelle2 is None          # déjà en attente : pas de doublon


def test_approbation_reversible_ne_debloque_pas_destructif():
    id_, _, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "r")
    approbations.approuver(nouvelle["id"], "tg:42", "telegram")
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "destructif", "r")
    assert id2 is None and msg2 and nouvelle2["statut"] == "en_attente"
    assert nouvelle2["sensibilite"] == "destructif"


def test_refus_reversible_ne_bloque_pas_destructif():
    _, _, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "r")
    approbations.refuser(nouvelle["id"], "tg:42", "telegram")
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "destructif", "r")
    assert id2 is None and nouvelle2 is not None and "REFUSÉ" not in msg2
