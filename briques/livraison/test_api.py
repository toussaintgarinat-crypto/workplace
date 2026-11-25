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
