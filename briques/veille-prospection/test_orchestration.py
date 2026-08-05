"""Tests de l'orchestration des campagnes (S193). Aucun réseau réel : geo/forge/memoire
mockés via monkeypatch sur `orchestration.httpx.post`. Chaque test utilise ses propres
identifiants (`orch-<prenom>`) pour ne jamais dépendre des campagnes laissées par d'autres
fichiers de test dans la DB SQLite partagée."""
import httpx

import orchestration
import stockage


class _FauxReponseZones:
    def __init__(self, zones):
        self._zones = zones

    def raise_for_status(self):
        pass

    def json(self):
        return {"zones": self._zones}


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


def test_memoire_recoit_x_user_id_sans_prefixe_perso(monkeypatch):
    """Le seam trouvé en revue finale : `campagne["user_id"]` est le tenant INTERNE tel que
    produit par `tenant_actuel` (forme réelle `perso:claire`, jamais une simple chaîne comme
    `orch-bob`), mais `memoire` isole par personne sur le X-User-Id BRUT (sans préfixe) que
    lui envoie le Cœur. Sans le retrait du préfixe, le souvenir atterrit dans un espace
    (`veille-perso:claire`) que le chemin de rappel du Cœur ne lit jamais (il envoie
    `X-User-Id: claire`, cf. core/contexte_tenant.py)."""
    c = stockage.creer_campagne("perso:claire", "zone-claire")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            captes["memoire_headers"] = headers
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration.executer_campagnes(user_ids=["perso:claire"])
    assert captes["memoire_headers"]["X-User-Id"] == "claire"
    # Le tenant interne complet ("perso:claire") reste, lui, utilisé tel quel côté stockage :
    assert stockage.lister_campagnes("perso:claire")[0]["id"] == c["id"]


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
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            raise httpx.ConnectError("forge down")
        if url.endswith("/retenir"):
            captes["memoire_called"] = True
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration.executer_campagnes(user_ids=["orch-dave"])
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 1     # le prospect n'est pas « perdu » au décompte
    assert executions[0]["nouveaux_crm"] == 0
    assert executions[0]["erreur"] is not None
    assert captes.get("memoire_called") is True  # mémoire est poussée malgré l'échec forge


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


def test_panne_inattendue_campagne1_isolation_campagne2(monkeypatch):
    """Vérifie qu'une panne inattendue (non HTTPError) dans une campagne n'empêche pas
    les campagnes suivantes d'être traitées. Par ex., si stockage.inserer_execution
    lève RuntimeError pour campagne1, campagne2 doit quand même être exécutée."""
    c1 = stockage.creer_campagne("orch-greg", "zone-panne-stockage")
    c2 = stockage.creer_campagne("orch-greg", "zone-ok")
    appels_geo = set()

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            zone = json.get("zone_id")
            appels_geo.add(zone)
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    # Monkeypatch stockage.inserer_execution : lève RuntimeError pour campagne1 seulement
    original_inserer = stockage.inserer_execution
    def inserer_avec_crash(campaign_id, **kwargs):
        if campaign_id == c1["id"]:
            raise RuntimeError("Crash stockage simulé")
        return original_inserer(campaign_id, **kwargs)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    monkeypatch.setattr(stockage, "inserer_execution", inserer_avec_crash)

    resultat = orchestration.executer_campagnes(user_ids=["orch-greg"])
    # Bien que campagne1 ait crashé en stockage, campagne2 a quand même été exécutée
    # (geo appelée pour les 2 zones) et enregistrée avec succès
    assert appels_geo == {"zone-panne-stockage", "zone-ok"}
    # campagnes_executees compte seulement les SUCCÈS (sans crash inattendu)
    assert resultat == {"campagnes_executees": 1}
    # Vérifie que c2 a bien une exécution enregistrée (succès)
    executions_c2 = stockage.lister_executions(c2["id"])
    assert executions_c2[0]["trouves"] == 1
    assert executions_c2[0]["erreur"] is None


def test_lire_zone_geo_trouve_par_id(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get", lambda *a, **k: _FauxReponseZones(
        [{"id": "z1", "nom": "Zone 1", "type": "logement"},
         {"id": "z2", "nom": "Zone 2", "type": "entreprise"}]))
    zone = orchestration.lire_zone_geo("z2")
    assert zone == {"id": "z2", "nom": "Zone 2", "type": "entreprise"}


def test_lire_zone_geo_absente_rend_none(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get",
                        lambda *a, **k: _FauxReponseZones([]))
    assert orchestration.lire_zone_geo("introuvable") is None


def test_avertissement_type_zone_signale_incoherence_b2c(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get", lambda *a, **k: _FauxReponseZones(
        [{"id": "z1", "nom": "Entreprises Castres", "type": "entreprise"}]))
    a = orchestration.avertissement_type_zone("z1", "b2c")
    assert a and "logement" in a


def test_avertissement_type_zone_silencieux_si_coherent(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get", lambda *a, **k: _FauxReponseZones(
        [{"id": "z1", "nom": "Passoires", "type": "logement"}]))
    assert orchestration.avertissement_type_zone("z1", "b2c") is None


def test_avertissement_type_zone_silencieux_si_geo_injoignable(monkeypatch):
    def _casse(*a, **k):
        raise httpx.ConnectError("refus de connexion")
    monkeypatch.setattr(orchestration.httpx, "get", _casse)
    assert orchestration.avertissement_type_zone("z1", "b2c") is None


def test_avertissement_type_zone_silencieux_si_zone_introuvable(monkeypatch):
    monkeypatch.setattr(orchestration.httpx, "get",
                        lambda *a, **k: _FauxReponseZones([]))
    assert orchestration.avertissement_type_zone("introuvable", "b2c") is None
