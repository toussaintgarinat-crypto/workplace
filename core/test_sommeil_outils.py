"""S243 — l'assistant pilote le sommeil des briques (outils), et le Cœur réveille tout seul
une brique endormie avant d'appeler l'un de ses outils.

$ cd core && python3 -m pytest test_sommeil_outils.py -v
"""
import asyncio
import json
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402

import droits  # noqa: E402
import outils  # noqa: E402
import sommeil  # noqa: E402
from test_sommeil import FauxDocker, Registre  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _registre():
    return Registre({
        "geo": {
            "port": 6110, "url_sante": "http://h:6110/sante",
            "sommeil": {"conteneurs": ["workplace_geo"], "inactivite_min": 30},
            "capacites": [
                {"nom": "geo_chercher", "description": "Cherche.", "methode": "GET",
                 "chemin": "/objets", "action": False},
                {"nom": "geo_purger", "description": "Purge.", "methode": "POST",
                 "chemin": "/purge", "action": True},
            ],
        },
        "calcul": {"port": 5990, "capacites": [
            {"nom": "calcul_ok", "description": "x", "methode": "GET", "chemin": "/ok"}]},
    })


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    sommeil._ACTIVITE.clear()
    monkeypatch.setattr(sommeil, "PAS_ATTENTE_S", 0.0)
    monkeypatch.setattr(sommeil, "ACTIF", True)
    d = FauxDocker({"workplace_geo": {"running": False, "sante": None}})
    sommeil.definir_backend(d)
    yield d
    sommeil.definir_backend(None)
    sommeil._ACTIVITE.clear()


# ── les trois outils ─────────────────────────────────────────────────────────

def test_les_outils_sommeil_sont_proposes_a_l_assistant():
    noms = {o["function"]["name"] for o in outils.OUTILS}
    assert {"brique_etat", "brique_reveiller", "brique_endormir"} <= noms


def test_brique_etat_sans_argument_liste_les_briques_qui_peuvent_dormir(_isoler):
    out = json.loads(run(outils.executer("brique_etat", {}, _registre())))
    assert out["briques"] == [{"brique": "geo", "etat": "endormie"}]


def test_brique_etat_d_une_brique_precise(_isoler):
    out = json.loads(run(outils.executer("brique_etat", {"brique": "geo"}, _registre())))
    assert out["etat"] == "endormie"
    out = json.loads(run(outils.executer("brique_etat", {"brique": "calcul"}, _registre())))
    assert out["etat"] == "inconnue" and "sommeil" in out["message"].lower()


def test_brique_reveiller_demarre_la_brique(_isoler):
    out = json.loads(run(outils.executer("brique_reveiller", {"brique": "geo"}, _registre())))
    assert out["ok"] and _isoler.demarres == ["workplace_geo"]


def test_brique_reveiller_sans_nom_est_une_erreur_claire():
    out = run(outils.executer("brique_reveiller", {}, _registre()))
    assert "brique" in out.lower()


def test_endormir_est_reserve_a_l_admin_du_cerveau(_isoler):
    assert droits.est_reserve_admin("brique_endormir")
    assert not droits.est_reserve_admin("brique_reveiller")   # réveiller est inoffensif
    _isoler.c["workplace_geo"]["running"] = True
    _isoler.c["workplace_geo"]["sante"] = "healthy"
    refus = run(outils.executer("brique_endormir", {"brique": "geo"}, _registre()))
    assert "admin" in refus.lower() and _isoler.arretes == []


def test_endormir_marche_pour_un_tour_admin(_isoler):
    _isoler.c["workplace_geo"].update(running=True, sante="healthy")
    jeton = droits.ADMIN_CERVEAU.set(True)
    try:
        out = json.loads(run(outils.executer("brique_endormir", {"brique": "geo"}, _registre())))
    finally:
        droits.ADMIN_CERVEAU.reset(jeton)
    assert out["ok"] and _isoler.arretes == ["workplace_geo"]


# ── auto-réveil avant un appel d'outil ───────────────────────────────────────

class _Reponse:
    status_code = 200
    def json(self): return {"ok": True}
    text = '{"ok": true}'


def _client_factice(monkeypatch, appels):
    async def faux_appel(client, cap, args):
        appels.append(cap["nom"])
        return json.dumps({"ok": True})
    monkeypatch.setattr(outils, "_appel_dynamique", faux_appel)


def test_appeler_un_outil_d_une_brique_endormie_la_reveille_d_abord(_isoler, monkeypatch):
    appels = []
    _client_factice(monkeypatch, appels)
    res = run(outils.executer("geo_chercher", {"bbox": "1,2,3,4"}, _registre()))
    assert json.loads(res) == {"ok": True}
    assert _isoler.demarres == ["workplace_geo"] and appels == ["geo_chercher"]


def test_un_outil_d_une_brique_sans_option_sommeil_n_est_pas_touche(_isoler, monkeypatch):
    appels = []
    _client_factice(monkeypatch, appels)
    run(outils.executer("calcul_ok", {}, _registre()))
    assert _isoler.demarres == [] and appels == ["calcul_ok"]


def test_si_le_reveil_echoue_l_appel_n_a_pas_lieu_et_le_llm_recoit_une_explication(_isoler, monkeypatch):
    appels = []
    _client_factice(monkeypatch, appels)
    _isoler.demarrage_lent = 10_000
    monkeypatch.setattr(sommeil, "ATTENTE_DEFAUT_S", 0.05)
    res = run(outils.executer("geo_chercher", {"bbox": "1,2,3,4"}, _registre()))
    assert appels == [] and "geo" in res and "réveill" in res.lower()


def test_une_action_non_confirmee_ne_reveille_pas_la_brique_pour_rien(_isoler, monkeypatch):
    # L'action demande d'abord l'accord de l'utilisateur : inutile d'allumer la brique avant.
    appels = []
    _client_factice(monkeypatch, appels)
    run(outils.executer("geo_purger", {}, _registre()))
    assert _isoler.demarres == []


def test_une_action_confirmee_reveille_la_brique(_isoler, monkeypatch):
    appels = []
    _client_factice(monkeypatch, appels)
    run(outils.executer("geo_purger", {"confirme": True}, _registre()))
    assert _isoler.demarres == ["workplace_geo"] and appels == ["geo_purger"]
