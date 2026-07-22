"""Tests de l'orchestration des campagnes (S193). Aucun réseau réel : geo/forge/memoire
mockés via monkeypatch sur `orchestration.httpx.post`. Chaque test utilise ses propres
identifiants (`orch-<prenom>`) pour ne jamais dépendre des campagnes laissées par d'autres
fichiers de test dans la DB SQLite partagée."""
import httpx

import orchestration
import stockage


class _Rep:
    def __init__(self, status_code, corps):
        self.status_code, self._corps = status_code, corps

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=None)


def test_campagne_sans_prospects_pas_de_crm_ni_memoire(monkeypatch):
    c = stockage.creer_campagne("orch-alice", "zone-vide")
    appels = {"forge": 0, "memoire": 0}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            appels["forge"] += 1
            return _Rep(200, {"crees": 0})
        if url.endswith("/retenir"):
            appels["memoire"] += 1
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-alice"])
    assert resultat == {"campagnes_executees": 1}
    assert appels == {"forge": 0, "memoire": 0}
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 0
    assert executions[0]["nouveaux_crm"] == 0
    assert executions[0]["erreur"] is None


def test_campagne_avec_prospects_pousse_crm_et_memoire(monkeypatch):
    c = stockage.creer_campagne("orch-bob", "zone-pleine")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            assert json == {"zone_id": "zone-pleine"}
            return _Rep(200, {"prospects": [{"nom": "Prospect 1"}],
                              "compte": {"deja_enrichi": 2}})
        if url.endswith("/crm/import-lot"):
            captes["forge_json"] = json
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            captes["memoire_json"] = json
            captes["memoire_headers"] = headers
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-bob"])
    assert resultat == {"campagnes_executees": 1}
    assert captes["forge_json"] == {"prospects": [{"nom": "Prospect 1"}]}
    assert captes["memoire_json"]["espace"] == "veille"
    assert captes["memoire_json"]["wing"] == "veille-prospection"
    assert captes["memoire_headers"]["X-User-Id"] == "orch-bob"
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 1
    assert executions[0]["deja_connus"] == 2
    assert executions[0]["nouveaux_crm"] == 1
    assert executions[0]["erreur"] is None


def test_geo_injoignable_erreur_journalisee_pas_de_crash(monkeypatch):
    c = stockage.creer_campagne("orch-carol", "zone-panne")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            raise httpx.ConnectError("refus de connexion")
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-carol"])
    assert resultat == {"campagnes_executees": 1}
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 0
    assert executions[0]["erreur"] is not None


def test_forge_injoignable_apres_geo_ok_prospects_pas_perdus(monkeypatch):
    c = stockage.creer_campagne("orch-dave", "zone-forge-panne")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            raise httpx.ConnectError("forge down")
        if url.endswith("/retenir"):
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration.executer_campagnes(user_ids=["orch-dave"])
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 1     # le prospect n'est pas « perdu » au décompte
    assert executions[0]["nouveaux_crm"] == 0
    assert executions[0]["erreur"] is not None


def test_memoire_injoignable_najamais_bloquant(monkeypatch):
    c = stockage.creer_campagne("orch-erin", "zone-memoire-panne")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            raise httpx.ConnectError("memoire down")
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-erin"])
    assert resultat == {"campagnes_executees": 1}
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["nouveaux_crm"] == 1   # le CRM n'est pas affecté par la panne mémoire
    assert executions[0]["erreur"] is None      # best-effort : jamais remonté


def test_executer_campagnes_ignore_campagnes_inactives(monkeypatch):
    stockage.creer_campagne("orch-frank", "zone-active")
    inactive = stockage.creer_campagne("orch-frank-seul-inactif", "zone-off")
    with stockage._conn() as conn:
        conn.execute("UPDATE campagnes SET actif = 0 WHERE id = ?", (inactive["id"],))

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [], "compte": {"deja_enrichi": 0}})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(
        user_ids=["orch-frank", "orch-frank-seul-inactif"])
    assert resultat == {"campagnes_executees": 1}


def test_executer_campagnes_user_ids_none_decouvre_via_stockage(monkeypatch):
    monkeypatch.setattr(stockage, "lister_user_ids_actifs", lambda: [])
    resultat = orchestration.executer_campagnes()
    assert resultat == {"campagnes_executees": 0}
