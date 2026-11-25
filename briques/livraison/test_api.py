from fastapi.testclient import TestClient
import main

c = TestClient(main.app)

def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["brique"] == "livraison"

def test_sante_ne_fuit_aucun_secret():
    assert "key" not in c.get("/sante").text.lower()


# ── Capacités de lecture (tâche 9) ──
import json
import pathlib
import pytest
from dokploy import Dokploy
from faux_dokploy import fabrique_transport


def _etat():
    return {"cle": "k", "appels": [], "limite": False,
            "logs": {"D2": "ok\ntok abcdef0123456789abcdef0123456789abcd mail a@b.fr\n"},
            "apps": {
                "A1": {"applicationId": "A1", "name": "calendrier", "appName": "cal-x",
                       "applicationStatus": "done", "rollbackActive": True,
                       "deployments": [
                           {"deploymentId": "D1", "title": "v1", "status": "done",
                            "createdAt": "t1", "finishedAt": "t1b", "rollbackId": "R1"},
                           {"deploymentId": "D2", "title": "v2", "status": "done",
                            "createdAt": "t2", "finishedAt": "t2b", "rollbackId": "R2"}]},
                "A2": {"applicationId": "A2", "name": "vide", "appName": "vide-x",
                       "applicationStatus": "idle", "rollbackActive": True,
                       "deployments": [
                           {"deploymentId": "D9", "title": "seul", "status": "done",
                            "createdAt": "t", "finishedAt": "t", "rollbackId": "R9"}]},
                "A3": {"applicationId": "A3", "name": "neuve", "appName": "n-x",
                       "applicationStatus": "idle", "rollbackActive": False, "deployments": []}}}


@pytest.fixture
def e(monkeypatch):
    etat = _etat()
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=fabrique_transport(etat)))
    return etat


def test_apps_liste_blanche(e):
    r = c.get("/apps")
    assert r.status_code == 200
    assert {a["nom"] for a in r.json()["apps"]} == {"calendrier", "vide", "neuve"}
    assert "refreshToken" not in r.text


def test_etat_par_nom_insensible_casse(e):
    r = c.get("/apps/Calendrier/etat")
    assert r.status_code == 200
    d = r.json()
    assert d["nom"] == "calendrier" and d["statut"] == "done"
    assert d["rollback_disponible"] is True
    assert d["dernier_deploiement"] == {"titre": "v2", "statut": "done", "debut": "t2", "fin": "t2b"}
    assert "refreshToken" not in r.text and "SECRET" not in r.text


def test_etat_par_id(e):
    assert c.get("/apps/A1/etat").json()["nom"] == "calendrier"


def test_rollback_indisponible_si_un_seul_deploiement(e):
    assert c.get("/apps/vide/etat").json()["rollback_disponible"] is False


def test_etat_sans_deploiement(e):
    d = c.get("/apps/neuve/etat").json()
    assert d["rollback_disponible"] is False and d["dernier_deploiement"] is None


def test_logs_masques(e):
    r = c.get("/apps/A1/logs")
    assert r.status_code == 200
    t = r.text
    assert "abcdef0123456789abcdef0123456789abcd" not in t and "a@b.fr" not in t
    assert "ok" in r.json()["logs"]


def test_logs_tail_borne_a_500(e):
    c.get("/apps/A1/logs?tail=99999")
    appel = [a for a in e["appels"] if a["chemin"] == "/api/deployment.readLogs"][-1]
    assert appel["params"]["tail"] == "500"


def test_logs_sans_deploiement_404(e):
    assert c.get("/apps/neuve/logs").status_code == 404


def test_app_inconnue_404_avec_liste(e):
    r = c.get("/apps/zzz/etat")
    assert r.status_code == 404
    assert "calendrier" in r.json()["detail"] and "A1" not in r.json()["detail"]


def test_app_ambigue_404(e):
    e["apps"]["A4"] = {**e["apps"]["A1"], "applicationId": "A4"}
    r = c.get("/apps/calendrier/etat")
    assert r.status_code == 404


def test_dokploy_injoignable_502(monkeypatch):
    import httpx

    def boom(req):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=httpx.MockTransport(boom)))
    r = c.get("/apps")
    assert r.status_code == 502 and "injoignable" in r.json()["detail"]


def test_dokploy_non_configure_503(monkeypatch):
    monkeypatch.delenv("DOKPLOY_URL")
    r = c.get("/apps")
    assert r.status_code == 503 and "non configuré" in r.json()["detail"]


def test_routes_protegees(monkeypatch, e):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "secret")
    for chemin in ("/apps", "/apps/A1/etat", "/apps/A1/logs"):
        assert c.get(chemin).status_code == 401
        assert c.get(chemin, headers={"X-API-Key": "secret"}).status_code == 200


def test_manifeste_capacites_lecture():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    assert caps["livraison_apps"]["chemin"] == "/apps"
    assert caps["livraison_etat"]["chemin"] == "/apps/{app}/etat"
    assert caps["livraison_logs"]["chemin"] == "/apps/{app}/logs"
    for n in ("livraison_apps", "livraison_etat", "livraison_logs"):
        assert caps[n]["methode"] == "GET" and caps[n]["action"] is False
        assert "sensibilite" not in caps[n]
    for n in ("livraison_etat", "livraison_logs"):
        assert caps[n]["params"]["app"]["type"] == "string" and caps[n]["params"]["app"]["requis"] is True
        assert "{app}" in caps[n]["chemin"]
    assert caps["livraison_logs"]["params"]["tail"]["type"] == "integer"


# ── Actions réversibles (tâche 10) ──
def _appels_mut(e):
    return [a for a in e["appels"] if a["methode"] == "POST"]


def test_redemarrer_appelle_reload(e):
    r = c.post("/apps/calendrier/redemarrer")
    assert r.status_code == 200 and r.json()["ok"] is True
    (a,) = _appels_mut(e)
    assert a["chemin"] == "/api/application.reload"
    assert a["corps"] == {"applicationId": "A1", "appName": "cal-x"}


def test_redemarrer_corps_vide_et_query_du_coeur(e):
    r = c.post("/apps/A1/redemarrer?app=A1", json={"app": "A1"})
    assert r.status_code == 200
    r = c.post("/apps/A1/redemarrer", content=b"", headers={"content-type": "application/json"})
    assert r.status_code == 200


def test_deployer_titre_defaut_et_fourni(e):
    assert c.post("/apps/A1/deployer").status_code == 200
    assert c.post("/apps/A1/deployer", json={"titre": "mon titre"}).status_code == 200
    assert c.post("/apps/A1/deployer?titre=zz", json={}).status_code == 200
    titres = [a["corps"]["title"] for a in _appels_mut(e)]
    assert titres == ["Déploiement demandé via l'assistant", "mon titre",
                      "Déploiement demandé via l'assistant"]
    assert all(a["chemin"] == "/api/application.redeploy" for a in _appels_mut(e))


def test_rollback_defaut_cible_precedent(e):
    r = c.post("/apps/A1/rollback")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app": "calendrier", "version_visee": "v1",
                        "rollback_id": "R1"}
    (a,) = _appels_mut(e)
    assert a["chemin"] == "/api/rollback.rollback" and a["corps"] == {"rollbackId": "R1"}


def test_rollback_saute_les_deploiements_sans_rollback_id(e):
    deps = e["apps"]["A1"]["deployments"]
    deps.append({"deploymentId": "D3", "title": "v3", "status": "done",
                 "createdAt": "t3", "finishedAt": "t3b", "rollbackId": None})
    deps.append({"deploymentId": "D0", "title": "v0", "status": "done",
                 "createdAt": "t0", "finishedAt": "t0b", "rollbackId": None})
    # ordre récent->ancien : v3(None), v2(R2), v1(R1), v0(None) ; courant = v3
    assert c.post("/apps/A1/rollback").json()["rollback_id"] == "R2"


def test_rollback_impossible_409(e):
    for nom in ("vide", "neuve"):
        r = c.post(f"/apps/{nom}/rollback")
        assert r.status_code == 409 and "retour arrière impossible" in r.json()["detail"]
    assert _appels_mut(e) == []


def test_rollback_version_par_titre_et_par_id(e):
    assert c.post("/apps/A1/rollback", json={"version": "v2"}).json()["rollback_id"] == "R2"
    assert c.post("/apps/A1/rollback", json={"version": "D1"}).json()["version_visee"] == "v1"


def test_rollback_version_inconnue_ou_sans_rollback_id_409(e):
    e["apps"]["A1"]["deployments"].append(
        {"deploymentId": "D0", "title": "ancien", "status": "done",
         "createdAt": "t0", "finishedAt": "t0b", "rollbackId": None})
    for v in ("zzz", "ancien"):
        r = c.post("/apps/A1/rollback", json={"version": v})
        assert r.status_code == 409 and "retour arrière impossible" in r.json()["detail"]
    assert _appels_mut(e) == []


@pytest.mark.parametrize("chemin,corps", [("/apps/A1/redemarrer", None), ("/apps/A1/deployer", None),
                                          ("/apps/A1/rollback", None)])
def test_actions_ne_fuient_aucun_secret(e, chemin, corps):
    r = c.post(chemin)
    assert r.status_code == 200
    assert "refreshToken" not in r.text and "SECRET" not in r.text


def test_actions_app_ambigue_404_et_limite_429_en_502(e):
    assert c.post("/apps/zzz/redemarrer").status_code == 404
    e["limite"] = True
    r = c.post("/apps/A1/redemarrer")
    assert r.status_code == 502 and "Limite" in r.json()["detail"]


def test_actions_injoignable_502(monkeypatch):
    import httpx

    def boom(req):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=httpx.MockTransport(boom)))
    for ch in ("redemarrer", "deployer", "rollback"):
        assert c.post(f"/apps/A1/{ch}").status_code == 502


def test_actions_protegees(monkeypatch, e):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "secret")
    for ch in ("redemarrer", "deployer", "rollback"):
        assert c.post(f"/apps/A1/{ch}").status_code == 401
    assert _appels_mut(e) == []


def test_manifeste_actions_reversibles():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    for n, ch in (("livraison_redemarrer", "redemarrer"), ("livraison_deployer", "deployer"),
                  ("livraison_rollback", "rollback")):
        x = caps[n]
        assert x["methode"] == "POST" and x["chemin"] == f"/apps/{{app}}/{ch}"
        assert x["action"] is True and x["sensibilite"] == "reversible"
        assert "approbation" in x["description"] and "Telegram" in x["description"]
        assert x["params"]["app"]["requis"] is True
    assert caps["livraison_deployer"]["params"]["titre"]["type"] == "string"
    assert caps["livraison_rollback"]["params"]["version"]["type"] == "string"
