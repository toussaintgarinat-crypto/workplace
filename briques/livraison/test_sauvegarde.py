import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import inventaire
import main
import preuve
import sauvegarde
from client_executeur import Executeur
from dokploy import Dokploy
from faux_dokploy import fabrique_transport
from test_api import _etat

c = TestClient(main.app)
CLE = "cle-test"
H = {"X-API-Key": CLE}
BASE = {"base": "temoin", "service": "postgres-abc-def", "utilisateur": "temoin",
        "sauvegarde_id": "B1", "prefixe_s3": "postgres-abc-def/s247-pg"}
ANCIEN = {"Name": "vieux.sql.gz", "Size": 10, "ModTime": "2020-01-01T00:00:00.000000000Z",
          "IsDir": False}


def _executeur(reponse, appels):
    def h(req):
        appels.append(json.loads(req.content))
        return httpx.Response(200, json=reponse)
    return Executeur("http://exec.test", "k", transport=httpx.MockTransport(h))


@pytest.fixture
def e(monkeypatch, tmp_path):
    etat = _etat()
    etat["fichiers"] = {"B1": [dict(ANCIEN)]}
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=fabrique_transport(etat)))
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({"calendrier": {"bases": [BASE], "volumes": [
        {"volume_backup_id": "V1"}]}}))
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(inv))
    monkeypatch.setenv("LIVRAISON_API_KEYS", CLE)   # les actions sont fermées sans clé (403)
    return etat


def _entree():
    return inventaire.lire("calendrier")


def _dok(etat):
    return Dokploy("http://d.test", "k", transport=fabrique_transport(etat))


def run(co):
    return asyncio.run(co)


OK = {"ok": True, "verdict": "valide", "raison": None,
      "comptages_origine": {"evenements": 42}, "comptages_restaures": {"evenements": 42}}


def test_sauvegarder_lance_base_et_volumes(e):
    r = run(sauvegarde.sauvegarder(_dok(e), _entree()))
    assert r == {"bases": ["temoin"], "volumes": 1} and e["volumes_lances"] == ["V1"]
    assert len(e["fichiers"]["B1"]) == 2


def test_verifier_valide_ecrit_la_preuve_et_envoie_l_objet_le_plus_recent(e):
    appels = []
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, appels), _entree(), "A1"))
    assert r["verdict"] == "valide" and r["raisons"] == [] and r["ok"] is True
    assert r["comptages"] == {"temoin": {"evenements": 42}} and r["volumes_non_verifies"] == 1
    assert appels[0]["objet"].startswith("postgres-abc-def/s247-pg/20") \
        and appels[0]["objet"].endswith(".sql.gz") and "vieux" not in appels[0]["objet"]
    assert preuve.valide("A1")["preuve_id"] == r["preuve_id"]


def test_verifier_comptages_differents_invalide_et_annule_la_preuve_precedente(e):
    preuve.noter("A1", "ANCIENNE", "valide", {})
    bad = {**OK, "verdict": "invalide", "raison": "comptages différents"}
    r = run(sauvegarde.verifier(_dok(e), _executeur(bad, []), _entree(), "A1"))
    assert r["verdict"] == "invalide" and "comptages différents" in r["raisons"][0]
    assert preuve.valide("A1") is None


def test_verifier_sauvegarde_non_recente_invalide_sans_appeler_l_executeur(e):
    e["sauvegarde_sans_fichier"] = True
    appels = []
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, appels), _entree(), "A1"))
    assert r["verdict"] == "invalide" and "récente" in r["raisons"][0] and appels == []


def test_verifier_echec_de_la_sauvegarde_dokploy_invalide(e):
    e["echec_sauvegarde"] = True
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, []), _entree(), "A1"))
    assert r["verdict"] == "invalide" and r["raisons"]


def test_verifier_sans_base_invalide(e):
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, []), {"bases": [], "volumes": [
        {"volume_backup_id": "V1"}]}, "A1"))
    assert r["verdict"] == "invalide" and "aucune base" in r["raisons"][0]


def test_route_verifier_renvoie_les_cles_que_le_coeur_enregistre(e, monkeypatch):
    monkeypatch.setattr(main, "executeur", lambda: _executeur(OK, []))
    r = c.post("/apps/Calendrier/sauvegardes/verifier", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["verdict"] == "valide" and d["app"] == "calendrier" and d["app_id"] == "A1"
    assert d["preuve_id"] and isinstance(d["expire_a"], float)


def test_route_executeur_injoignable_donne_verdict_invalide_pas_une_erreur(e, monkeypatch):
    def boom(req):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(main, "executeur", lambda: Executeur(
        "http://x.test", "k", transport=httpx.MockTransport(boom)))
    d = c.post("/apps/calendrier/sauvegardes/verifier", headers=H).json()
    assert d["ok"] is True and d["verdict"] == "invalide" and "injoignable" in d["raisons"][0]


def test_route_sans_inventaire_404(e, monkeypatch, tmp_path):
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(tmp_path / "absent.json"))
    assert c.post("/apps/calendrier/sauvegarder", headers=H).status_code == 404
    assert c.post("/apps/calendrier/sauvegardes/verifier", headers=H).status_code == 404


def test_route_sauvegarder(e):
    r = c.post("/apps/calendrier/sauvegarder", headers=H)
    assert r.status_code == 200 and r.json() == {"ok": True, "app": "calendrier",
                                                 "bases": ["temoin"], "volumes": 1}


@pytest.mark.parametrize("chemin", ["/apps/calendrier/sauvegarder",
                                    "/apps/calendrier/sauvegardes/verifier"])
@pytest.mark.parametrize("valeur", ["", None])
def test_actions_sans_cle_configuree_403_sans_appel_dokploy(e, monkeypatch, chemin, valeur):
    if valeur is None:
        monkeypatch.delenv("LIVRAISON_API_KEYS", raising=False)
    else:
        monkeypatch.setenv("LIVRAISON_API_KEYS", valeur)
    assert c.post(chemin).status_code == 403
    assert e["appels"] == []


def test_actions_mauvaise_cle_401(e):
    assert c.post("/apps/calendrier/sauvegarder", headers={"X-API-Key": "mauvaise"}).status_code == 401


def test_verifier_nettoyage_en_echec_alerte_sans_changer_le_verdict(e):
    r = run(sauvegarde.verifier(_dok(e), _executeur({**OK, "nettoyage": "echec"}, []), _entree(), "A1"))
    assert r["verdict"] == "valide" and r["raisons"] == []
    assert len(r["alertes"]) == 1 and "temoin" in r["alertes"][0] and "restore_*" in r["alertes"][0]


def test_verifier_alertes_vide_par_defaut(e):
    r = run(sauvegarde.verifier(_dok(e), _executeur({**OK, "nettoyage": "ok"}, []), _entree(), "A1"))
    assert r["alertes"] == []
