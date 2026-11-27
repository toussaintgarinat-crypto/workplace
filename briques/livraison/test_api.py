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
    assert d["en_service"] == d["dernier_deploiement"]
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
CLE = "cle-livraison-test"
ca = TestClient(main.app, headers={"X-API-Key": CLE})


@pytest.fixture
def ea(e, monkeypatch):
    """Actions : fail-closed (C1) → une clé est configurée et présentée."""
    monkeypatch.setenv("LIVRAISON_API_KEYS", CLE)
    return e


def _appels_mut(etat):
    return [a for a in etat["appels"] if a["methode"] == "POST"]


def test_redemarrer_appelle_reload(ea):
    r = ca.post("/apps/calendrier/redemarrer")
    assert r.status_code == 200 and r.json()["ok"] is True
    (a,) = _appels_mut(ea)
    assert a["chemin"] == "/api/application.reload"
    assert a["corps"] == {"applicationId": "A1", "appName": "cal-x"}


def test_redemarrer_corps_vide_et_query_du_coeur(ea):
    r = ca.post("/apps/A1/redemarrer?app=A1", json={"app": "A1"})
    assert r.status_code == 200
    r = ca.post("/apps/A1/redemarrer", content=b"", headers={"content-type": "application/json"})
    assert r.status_code == 200


def test_deployer_titre_defaut_et_fourni(ea):
    assert ca.post("/apps/A1/deployer").status_code == 200
    assert ca.post("/apps/A1/deployer", json={"titre": "mon titre"}).status_code == 200
    assert ca.post("/apps/A1/deployer?titre=zz", json={}).status_code == 200
    titres = [a["corps"]["title"] for a in _appels_mut(ea)]
    assert titres == ["Déploiement demandé via l'assistant", "mon titre",
                      "Déploiement demandé via l'assistant"]
    assert all(a["chemin"] == "/api/application.redeploy" for a in _appels_mut(ea))


def test_rollback_defaut_cible_precedent(ea):
    r = ca.post("/apps/A1/rollback")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app": "calendrier", "version_visee": "v1",
                        "rollback_id": "R1"}
    (a,) = _appels_mut(ea)
    assert a["chemin"] == "/api/rollback.rollback" and a["corps"] == {"rollbackId": "R1"}


def test_rollback_saute_les_deploiements_sans_rollback_id(ea):
    deps = ea["apps"]["A1"]["deployments"]
    deps.append({"deploymentId": "D3", "title": "v3", "status": "done",
                 "createdAt": "t3", "finishedAt": "t3b", "rollbackId": None})
    deps.append({"deploymentId": "D0", "title": "v0", "status": "done",
                 "createdAt": "t0", "finishedAt": "t0b", "rollbackId": None})
    # ordre récent->ancien : v3(None), v2(R2), v1(R1), v0(None) ; courant = v3
    assert ca.post("/apps/A1/rollback").json()["rollback_id"] == "R2"


def test_rollback_impossible_409(ea):
    for nom in ("vide", "neuve"):
        r = ca.post(f"/apps/{nom}/rollback")
        assert r.status_code == 409 and "retour arrière impossible" in r.json()["detail"]
    assert _appels_mut(ea) == []


def test_rollback_version_par_titre_et_par_id(ea):
    assert ca.post("/apps/A1/rollback", json={"version": "v2"}).json()["rollback_id"] == "R2"
    assert ca.post("/apps/A1/rollback", json={"version": "D1"}).json()["version_visee"] == "v1"


def test_rollback_version_inconnue_ou_sans_rollback_id_409(ea):
    ea["apps"]["A1"]["deployments"].append(
        {"deploymentId": "D0", "title": "ancien", "status": "done",
         "createdAt": "t0", "finishedAt": "t0b", "rollbackId": None})
    for v in ("zzz", "ancien"):
        r = ca.post("/apps/A1/rollback", json={"version": v})
        assert r.status_code == 409 and "retour arrière impossible" in r.json()["detail"]
    assert _appels_mut(ea) == []


@pytest.mark.parametrize("chemin,corps", [("/apps/A1/redemarrer", None), ("/apps/A1/deployer", None),
                                          ("/apps/A1/rollback", None)])
def test_actions_ne_fuient_aucun_secret(ea, chemin, corps):
    r = ca.post(chemin)
    assert r.status_code == 200
    assert "refreshToken" not in r.text and "SECRET" not in r.text


def test_actions_app_ambigue_404_et_limite_429_en_502(ea):
    assert ca.post("/apps/zzz/redemarrer").status_code == 404
    ea["limite"] = True
    r = ca.post("/apps/A1/redemarrer")
    assert r.status_code == 502 and "Limite" in r.json()["detail"]


def test_actions_injoignable_502(monkeypatch):
    import httpx

    def boom(req):
        raise httpx.ConnectError("x")
    monkeypatch.setenv("LIVRAISON_API_KEYS", CLE)
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=httpx.MockTransport(boom)))
    for ch in ("redemarrer", "deployer", "rollback"):
        r = ca.post(f"/apps/A1/{ch}")
        assert r.status_code == 502 and "injoignable" in r.json()["detail"]


def test_actions_protegees_mauvaise_cle_401(monkeypatch, e):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "secret")
    for ch in ("redemarrer", "deployer", "rollback"):
        assert c.post(f"/apps/A1/{ch}").status_code == 401
        assert ca.post(f"/apps/A1/{ch}").status_code == 401          # mauvaise clé
    assert e["appels"] == []


# ── C1 : fail-closed des actions ──
@pytest.mark.parametrize("ch", ["redemarrer", "deployer", "rollback"])
@pytest.mark.parametrize("valeur", ["", " , "])
def test_actions_sans_cle_configuree_403_sans_appel_dokploy(monkeypatch, e, ch, valeur):
    monkeypatch.setenv("LIVRAISON_API_KEYS", valeur)
    for client in (c, ca):
        r = client.post(f"/apps/A1/{ch}")
        assert r.status_code == 403
        assert r.json()["detail"] == "Route désactivée : configure LIVRAISON_API_KEYS."
    assert e["appels"] == []                       # aucun appel à Dokploy, même en lecture


@pytest.mark.parametrize("ch", ["redemarrer", "deployer", "rollback"])
def test_actions_cle_absente_de_l_env_403(monkeypatch, e, ch):
    monkeypatch.delenv("LIVRAISON_API_KEYS", raising=False)
    assert ca.post(f"/apps/A1/{ch}").status_code == 403
    assert e["appels"] == []


def test_lectures_restent_ouvertes_sans_cle(monkeypatch, e):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "")
    for chemin in ("/apps", "/apps/A1/etat", "/apps/A1/logs"):
        assert c.get(chemin).status_code == 200


def test_actions_bonne_cle_ok_et_bearer(ea):
    assert ca.post("/apps/A1/redemarrer").status_code == 200
    r = c.post("/apps/A1/redemarrer", headers={"Authorization": f"Bearer {CLE}"})
    assert r.status_code == 200


# ── M4 ──
def test_action_sur_app_ambigue_aucun_post(ea):
    ea["apps"]["A4"] = {**ea["apps"]["A1"], "applicationId": "A4"}
    for ch in ("redemarrer", "deployer", "rollback"):
        r = ca.post(f"/apps/calendrier/{ch}")
        assert r.status_code == 404 and "ambiguë" in r.json()["detail"]
    assert _appels_mut(ea) == []


def test_sante_ne_fuit_aucun_secret_avec_vraies_valeurs(monkeypatch):
    secrets = {"DOKPLOY_API_KEY": "dkp_VraieValeur_Secrete_123",
               "LIVRAISON_API_KEYS": "cle-liv-AAA,cle-liv-BBB",
               "FORGEJO_TOKEN": "fgj_JetonForgejoSecret_456",
               "DOKPLOY_URL": "http://100.124.176.122:3000"}
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    t = c.get("/sante").text
    for v in ("dkp_VraieValeur_Secrete_123", "cle-liv-AAA", "cle-liv-BBB",
              "fgj_JetonForgejoSecret_456", "100.124.176.122"):
        assert v not in t
    assert "key" not in t.lower()


# ── M3 : messages ambiguïté/introuvable avec (projet/environnement) ──
def test_message_introuvable_liste_projet_environnement(e):
    d = c.get("/apps/zzz/etat").json()["detail"]
    assert "calendrier (temoin/production)" in d and "introuvable" in d


def test_message_ambigu_liste_les_candidats(e):
    e["apps"]["A4"] = {**e["apps"]["A1"], "applicationId": "A4"}
    d = c.get("/apps/calendrier/etat").json()["detail"]
    assert "ambiguë" in d and "calendrier (temoin/production)" in d
    assert "vide" not in d                         # seuls les candidats sont listés


# ── I2 : nombre d'appels Dokploy par action, délai ambigu ──
def test_redemarrer_trois_appels_max(ea):
    assert ca.post("/apps/calendrier/redemarrer").status_code == 200
    assert [a["chemin"] for a in ea["appels"]] == [
        "/api/project.all", "/api/application.one", "/api/application.reload"]


def test_deployer_et_rollback_trois_appels_max(ea):
    ca.post("/apps/A1/deployer")
    assert len(ea["appels"]) <= 3
    ea["appels"].clear()
    ca.post("/apps/A1/rollback")
    assert len(ea["appels"]) <= 3


@pytest.mark.parametrize("ch", ["redemarrer", "deployer", "rollback"])
def test_action_timeout_apres_envoi_504_message_prudent(monkeypatch, ch):
    import httpx
    etat = _etat()
    interne = fabrique_transport(etat)

    def lent(req):
        if req.method == "POST":
            raise httpx.ReadTimeout("x")
        return interne.handle_request(req)
    monkeypatch.setenv("LIVRAISON_API_KEYS", CLE)
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=httpx.MockTransport(lent)))
    r = ca.post(f"/apps/A1/{ch}")
    assert r.status_code == 504
    assert "peut-être été exécutée" in r.json()["detail"]
    assert "livraison_etat" in r.json()["detail"]


# ── I3 : courant = plus récent « done » ──
def _dep(did, titre, statut, t, rid):
    return {"deploymentId": did, "title": titre, "status": statut,
            "createdAt": t, "finishedAt": t + "b", "rollbackId": rid}


def test_dernier_deploiement_en_erreur(ea):
    ea["apps"]["A1"]["deployments"].append(_dep("D3", "v3", "error", "t3", "R3"))
    d = ca.get("/apps/A1/etat").json()
    assert d["dernier_deploiement"]["titre"] == "v3" and d["dernier_deploiement"]["statut"] == "error"
    assert d["en_service"] == {"titre": "v2", "statut": "done", "debut": "t2", "fin": "t2b"}
    assert d["rollback_disponible"] is True
    r = ca.post("/apps/A1/rollback")
    assert r.status_code == 200 and r.json()["rollback_id"] == "R1"   # pas R2 (= en service)


def test_aucun_done_anterieur_au_courant(ea):
    ea["apps"]["A1"]["deployments"] = [_dep("D1", "v1", "error", "t1", "R1"),
                                       _dep("D2", "v2", "done", "t2", "R2")]
    assert ca.get("/apps/A1/etat").json()["rollback_disponible"] is False
    r = ca.post("/apps/A1/rollback")
    assert r.status_code == 409 and "retour arrière impossible" in r.json()["detail"]
    assert _appels_mut(ea) == []


def test_aucun_done_du_tout(ea):
    ea["apps"]["A1"]["deployments"] = [_dep("D1", "v1", "error", "t1", "R1")]
    d = ca.get("/apps/A1/etat").json()
    assert d["en_service"] is None and d["rollback_disponible"] is False
    assert ca.post("/apps/A1/rollback").status_code == 409


def test_rollback_version_non_done_409(ea):
    ea["apps"]["A1"]["deployments"].append(_dep("D0", "v0", "error", "t0", "R0"))
    r = ca.post("/apps/A1/rollback", json={"version": "v0"})
    assert r.status_code == 409
    assert _appels_mut(ea) == []


def test_rollback_version_ambigue_409(ea):
    ea["apps"]["A1"]["deployments"].append(_dep("D0", "v1", "done", "t0", "R0"))
    r = ca.post("/apps/A1/rollback", json={"version": "v1"})
    assert r.status_code == 409
    assert r.json()["detail"] == "version ambiguë : précise l'id du déploiement"
    assert _appels_mut(ea) == []
    # l'id lève l'ambiguïté
    assert ca.post("/apps/A1/rollback", json={"version": "D0"}).json()["rollback_id"] == "R0"


def test_rollback_inactif_indisponible(ea):
    ea["apps"]["A1"]["rollbackActive"] = False
    assert ca.get("/apps/A1/etat").json()["rollback_disponible"] is False
    assert ca.post("/apps/A1/rollback").status_code == 409
    assert _appels_mut(ea) == []


# ── I4 : logs masqués AVANT troncature ──
def test_logs_jeton_a_cheval_sur_la_coupure_sans_fragment(e):
    jeton = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    assert len(jeton) == 40
    queue = "y" * 14 + "\n" + "ligne de log normale\n" * 950          # 19965 caractères
    avant = "debut\n" * 2000 + "cle " + jeton[:20]
    logs = avant + jeton[20:] + " fin\n" + queue
    # une coupure BRUTE à 20000 caractères depuis la fin tomberait au milieu du jeton
    assert len(logs) - 20000 == len(avant) - 10
    e["logs"]["D2"] = logs
    sortie = c.get("/apps/A1/logs").json()["logs"]
    assert len(sortie) <= 20000
    for i in range(len(jeton) - 5):
        assert jeton[i:i + 6] not in sortie
    assert sortie.endswith("ligne de log normale\n")


def test_logs_coupes_ne_commencent_pas_par_une_ligne_partielle(e):
    e["logs"]["D2"] = "premiere-ligne-longue-" + "x" * 30 + "\n" + "ligne courte\n" * 3000
    sortie = c.get("/apps/A1/logs").json()["logs"]
    assert sortie.startswith("ligne courte\n")


def test_logs_non_coupes_intacts(e):
    e["logs"]["D2"] = "un\ndeux\n"
    assert c.get("/apps/A1/logs").json()["logs"] == "un\ndeux\n"


def test_manifeste_relayer_erreurs_sur_les_15_capacites():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    assert len(m["capacites"]) == 15
    assert all(x.get("relayer_erreurs") is True for x in m["capacites"])


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


# ── Repère de rollback : « en service » juste après un retour arrière (preuve LIVE T12) ──
def _ajoute_deploiement(etat, did, titre, rollback_id):
    etat["apps"]["A1"]["deployments"].append(
        {"deploymentId": did, "title": titre, "status": "done", "createdAt": "t" + did,
         "finishedAt": "t" + did + "b", "rollbackId": rollback_id})


def test_etat_apres_rollback_annonce_la_version_visee(ea):
    assert ca.get("/apps/calendrier/etat").json()["en_service"]["titre"] == "v2"
    r = ca.post("/apps/calendrier/rollback")
    assert r.status_code == 200 and r.json()["version_visee"] == "v1"
    e_ = ca.get("/apps/calendrier/etat").json()
    assert e_["en_service"]["titre"] == "v1" and e_["via_rollback"] is True
    assert e_["dernier_deploiement"]["titre"] == "v2"


def test_apres_rollback_plus_de_version_plus_ancienne_donc_second_rollback_impossible(ea):
    ca.post("/apps/calendrier/rollback")
    assert ca.get("/apps/calendrier/etat").json()["rollback_disponible"] is False
    assert ca.post("/apps/calendrier/rollback").status_code == 409


def test_second_rollback_vise_la_version_anterieure_a_celle_en_service(ea):
    _ajoute_deploiement(ea, "D3", "v3", "R3")          # du plus récent : v3, v2, v1
    assert ca.post("/apps/calendrier/rollback").json()["version_visee"] == "v2"
    assert ca.post("/apps/calendrier/rollback").json()["version_visee"] == "v1"
    assert [a["corps"] for a in _appels_mut(ea)] == [{"rollbackId": "R2"}, {"rollbackId": "R1"}]


def test_nouveau_deploiement_perime_le_repere(ea):
    ca.post("/apps/calendrier/rollback")
    _ajoute_deploiement(ea, "D3", "v3", "R3")
    e_ = ca.get("/apps/calendrier/etat").json()
    assert e_["en_service"]["titre"] == "v3" and e_["via_rollback"] is False


def test_repere_non_ecrivable_ne_fait_pas_echouer_le_rollback(ea, monkeypatch):
    monkeypatch.setenv("LIVRAISON_DATA", "/proc/interdit/livraison")
    r = ca.post("/apps/calendrier/rollback")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_demarrage_marque_les_operations_interrompues(tmp_path, monkeypatch):
    import operations
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path))
    operations.demarrer("calendrier-familial", "reset")
    with TestClient(main.app):
        pass
    op = operations.lire("calendrier-familial")["op"]
    assert op["etat"] == "interrompue"


def test_demarrage_survit_a_un_etat_des_operations_illisible(monkeypatch):
    import operations
    from fastapi.testclient import TestClient

    def boom():
        raise PermissionError("disque")
    monkeypatch.setattr(operations, "marquer_interrompues", boom)
    with TestClient(main.app) as c:
        assert c.get("/sante").status_code == 200


# ── Reset bleu/vert : routes, manifeste (S247 2b, tâche 7) ──
import asyncio
import inventaire
import operations
import preuve

BASE_INV = {"base": "temoin", "service": "postgres-temoin", "utilisateur": "temoin",
            "sauvegarde_id": "S1", "prefixe_s3": "temoin/db"}
RESET_INV = {"variable_env": "DATABASE_URL", "domaine_public": "app.example.com",
             "domaine_test": "test.example.com", "port_app": 3000, "sante_chemin": "/api/health"}


def _inventaire(tmp_path, monkeypatch, avec_reset=True, nom="calendrier"):
    entree = {"bases": [dict(BASE_INV)], "volumes": []}
    if avec_reset:
        entree["reset"] = dict(RESET_INV)
    f = tmp_path / "inv.json"
    f.write_text(json.dumps({nom: entree}))
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(f))


@pytest.fixture
def er(ea, tmp_path, monkeypatch):
    """Reset : inventaire avec bloc reset, exécuteur configuré, preuve valide, reset factice."""
    _inventaire(tmp_path, monkeypatch)
    monkeypatch.setenv("EXECUTEUR_URL", "http://ex.test")
    monkeypatch.setenv("EXECUTEUR_KEY", "k")
    monkeypatch.setenv("LIVRAISON_TRAEFIK_URL", "http://traefik.test")
    ea["apps"]["A1"]["env"] = "DATABASE_URL=postgres://u:SECRETXYZ@h/temoin\nPASSWORD=SECRETXYZ"
    preuve.noter("A1", "P1", "valide", {})
    appels = []

    async def faux_reset(d, ex, entree, app_nom, app_id, operation_id, **kw):
        appels.append(("reset", entree, app_nom, app_id))
        operations.terminer(app_nom, operation_id, "reussie", "ok")

    async def faux_retour(d, entree, app_nom, operation_id, **kw):
        appels.append(("retour", entree, app_nom))
        operations.terminer(app_nom, operation_id, "reussie", "ok")

    monkeypatch.setattr(main.reset, "reset", faux_reset)
    monkeypatch.setattr(main.reset, "retour_arriere", faux_retour)
    ea["appels_reset"] = appels
    return ea


@pytest.fixture
def cr(er):
    """Client à boucle persistante : les tâches de fond (reset) survivent à la requête 202."""
    with TestClient(main.app, headers={"X-API-Key": CLE}) as client:
        yield client


def _fin(client, nom="calendrier"):
    import time
    for _ in range(300):
        o = client.get(f"/apps/{nom}/operation").json()
        if o["etat"] != "en_cours":
            return o
        time.sleep(0.01)
    raise AssertionError("l'opération ne se termine pas")


def _poser_deux_emplacements(nom="calendrier", base_active="temoin_v0123abcd", precedente="temoin"):
    operations.enregistrer_emplacements(nom, {"app_id": "A1"}, {"app_id": "B1"}, "A", "temoin")
    operations.basculer_etat(nom, "B", base_active, precedente)


def test_reset_sans_cle_refuse(er, monkeypatch):
    nue = TestClient(main.app)
    assert nue.post("/apps/calendrier/reset").status_code in (401, 403)
    assert nue.post("/apps/calendrier/retour-arriere").status_code in (401, 403)
    assert er["appels_reset"] == []


def test_reset_sans_preuve_409(er):
    preuve.noter("A1", "P2", "invalide", {})
    r = ca.post("/apps/calendrier/reset")
    assert r.status_code == 409 and "preuve" in r.json()["detail"]
    assert operations.lire("calendrier") is None


def test_reset_sans_bloc_reset_409(er, tmp_path, monkeypatch):
    _inventaire(tmp_path, monkeypatch, avec_reset=False)
    r = ca.post("/apps/calendrier/reset")
    assert r.status_code == 409 and "reset non configuré pour cette application" in r.json()["detail"]
    assert ca.post("/apps/calendrier/retour-arriere").status_code == 409


def test_reset_sans_executeur_503_et_404_inventaire_prime(er, monkeypatch):
    monkeypatch.delenv("EXECUTEUR_URL")
    assert ca.post("/apps/calendrier/reset").status_code == 503
    assert ca.post("/apps/vide/reset").status_code == 404      # app sans inventaire : 404 avant 503


def test_reset_app_inconnue_et_jumeau_404(er):
    assert ca.post("/apps/zzz/reset").status_code == 404
    er["apps"]["A5"] = {**er["apps"]["A1"], "applicationId": "A5", "name": "calendrier-jumeau"}
    assert ca.post("/apps/calendrier-jumeau/reset").status_code == 404


def test_reset_nominal_202_puis_reussie(er, cr):
    r = cr.post("/apps/calendrier/reset")
    assert r.status_code == 202
    d = r.json()
    assert d["ok"] is True and d["app"] == "calendrier" and d["etat"] == "en_cours" and d["operation"]
    o = _fin(cr)
    assert o["etat"] == "reussie" and o["operation"] == d["operation"]
    assert o["app"] == "calendrier" and o["message"] == "ok"
    (appel,) = er["appels_reset"]
    assert appel[2] == "calendrier" and appel[3] == "A1"


def test_second_post_pendant_en_cours_409(er):
    oid = operations.demarrer("calendrier", "reset")
    r = ca.post("/apps/calendrier/reset")
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]
    _poser_deux_emplacements()
    assert ca.post("/apps/calendrier/retour-arriere").status_code == 409
    assert ca.get("/apps/calendrier/operation").json()["operation"] == oid


def test_operation_aucune(er):
    d = ca.get("/apps/calendrier/operation").json()
    assert d["etat"] == "aucune" and d["app"] == "calendrier" and d["retour_possible"] is False


def test_operation_ne_fuit_ni_env_ni_mot_de_passe(er):
    _poser_deux_emplacements()
    oid = operations.demarrer("calendrier", "reset")
    operations.etape("calendrier", oid, "sante", domaine_id="DOM42")
    r = ca.get("/apps/calendrier/operation")
    d = r.json()
    assert d["etat"] == "en_cours" and d["etape"] == "sante" and d["base_active"] == "temoin_v0123abcd"
    assert set(d) == {"app", "etat", "etape", "operation", "message", "actif", "base_active",
                      "retour_possible"}
    low = r.text.lower()
    assert "secretxyz" not in low and "password" not in low and "env" not in low
    assert "DOM42" not in r.text and "postgres://" not in r.text


def test_operation_protegee_par_cle(er):
    assert TestClient(main.app).get("/apps/calendrier/operation").status_code == 401


def test_retour_arriere_sans_generation_precedente_409(er):
    r = ca.post("/apps/calendrier/retour-arriere")
    assert r.status_code == 409
    assert operations.lire("calendrier") is None      # refusé AVANT demarrer
    assert er["appels_reset"] == []


def test_retour_arriere_nominal_202_puis_reussie(er, cr):
    _poser_deux_emplacements()
    assert ca.get("/apps/calendrier/operation").json()["retour_possible"] is True
    r = cr.post("/apps/calendrier/retour-arriere")
    assert r.status_code == 202 and r.json()["etat"] == "en_cours"
    o = _fin(cr)
    assert o["etat"] == "reussie"
    (appel,) = er["appels_reset"]
    assert appel[0] == "retour" and appel[2] == "calendrier"


def test_reset_recoit_l_entree_brute_apres_un_premier_reset(er, cr):
    _poser_deux_emplacements(base_active="temoin_v0123abcd")
    assert cr.post("/apps/calendrier/reset").status_code == 202
    _fin(cr)
    (appel,) = er["appels_reset"]
    assert appel[1]["bases"][0]["base"] == "temoin"            # base racine, pas la base active
    assert appel[1]["reset"] == RESET_INV


def test_sauvegarder_garde_l_entree_effective(er):
    _poser_deux_emplacements(base_active="temoin_v0123abcd")
    assert main._entree_inventaire("calendrier")["bases"][0]["base"] == "temoin_v0123abcd"
    assert main._entree_brute("calendrier")["bases"][0]["base"] == "temoin"


def test_manifeste_capacites_reset():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    r, b, o = caps["livraison_reset_app"], caps["livraison_retour_arriere"], caps["livraison_operation"]
    assert r["methode"] == "POST" and r["chemin"] == "/apps/{app}/reset" and r["action"] is True
    assert r["sensibilite"] == "donnees" and r["prerequis"] == ["preuve_sauvegarde"]
    assert "fournit_preuve" not in r
    assert "livraison_verifier_sauvegarde" in r["description"] and "livraison_operation" in r["description"]
    assert b["methode"] == "POST" and b["chemin"] == "/apps/{app}/retour-arriere"
    assert b["sensibilite"] == "donnees" and "prerequis" not in b and "fournit_preuve" not in b
    assert o["methode"] == "GET" and o["chemin"] == "/apps/{app}/operation"
    assert o["action"] is False and "sensibilite" not in o
    for x in (r, b, o):
        assert x["params"]["app"]["requis"] is True and x["relayer_erreurs"] is True


def test_reset_sans_traefik_503_avant_tout(er, monkeypatch):
    monkeypatch.delenv("LIVRAISON_TRAEFIK_URL")
    _poser_deux_emplacements()
    for chemin in ("/apps/calendrier/reset", "/apps/calendrier/retour-arriere"):
        r = ca.post(chemin)
        assert r.status_code == 503 and "LIVRAISON_TRAEFIK_URL non configuré" in r.json()["detail"]
    assert er["appels_reset"] == [] and (operations.lire("calendrier").get("op") is None)


@pytest.mark.parametrize("base", ["a" * 32, "temoin_v0a1b2c3d"])
def test_reset_nom_de_base_racine_invalide_409_avant_le_202(er, tmp_path, monkeypatch, base):
    f = tmp_path / "inv2.json"
    f.write_text(json.dumps({"calendrier": {"bases": [dict(BASE_INV, base=base)], "volumes": [],
                                            "reset": dict(RESET_INV)}}))
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(f))
    r = ca.post("/apps/calendrier/reset")
    assert r.status_code == 409 and r.json()["detail"].startswith(
        "configuration invalide : nom de base trop long")
    assert operations.lire("calendrier") is None and er["appels_reset"] == []


# ── Après un reset (actif = B), les outils visent le jumeau (S247 2b, I4) ──

@pytest.fixture
def eb(ea):
    ea["apps"]["B1"] = {"applicationId": "B1", "name": "calendrier-jumeau", "appName": "cal-b",
                        "applicationStatus": "done", "rollbackActive": True, "deployments": [
                            {"deploymentId": "DB1", "title": "b1", "status": "done",
                             "createdAt": "u1", "finishedAt": "u1b", "rollbackId": "RB1"},
                            {"deploymentId": "DB2", "title": "b2", "status": "done",
                             "createdAt": "u2", "finishedAt": "u2b", "rollbackId": "RB2"}]}
    return ea


def _ids_vises(etat):
    sortie = []
    for a in etat["appels"]:
        corps = a["corps"] or {}
        sortie.append(corps.get("applicationId") or a["params"].get("applicationId")
                      or corps.get("rollbackId") or a["params"].get("deploymentId"))
    return [x for x in sortie if x]


@pytest.mark.parametrize("actif,cible,rb,dep", [("B", "B1", "RB1", "DB2"),
                                                 ("A", "A1", "R1", "D2"), (None, "A1", "R1", "D2")])
def test_outils_visent_l_emplacement_actif(eb, actif, cible, rb, dep):
    if actif:
        operations.enregistrer_emplacements("calendrier", {"app_id": "A1"}, {"app_id": "B1"},
                                            "A", "temoin")
        if actif == "B":
            operations.basculer_etat("calendrier", "B", "temoin_v0123abcd", "temoin")
    attendu = {"B": "B", "A": "A", None: None}[actif]
    e_ = ca.get("/apps/calendrier/etat").json()
    assert e_["emplacement"] == attendu
    assert e_["nom"] == ("calendrier-jumeau" if actif == "B" else "calendrier")
    assert ca.get("/apps/calendrier/logs").status_code == 200
    for chemin in ("redemarrer", "deployer", "rollback"):
        r = ca.post(f"/apps/calendrier/{chemin}")
        assert r.status_code == 200 and r.json().get("emplacement") == attendu, r.json()
    vises = _ids_vises(eb)
    autres = {"B1", "RB1", "RB2", "DB1", "DB2"} if cible == "A1" else {
        "A1", "R1", "R2", "D1", "D2"}
    assert cible in vises and rb in vises and dep in vises
    assert not set(vises) & autres, vises


def test_le_jumeau_par_son_nom_se_resout_sur_lui_meme(eb):
    _poser_deux_emplacements()
    operations.basculer_etat("calendrier", "A", "temoin", "temoin_v0123abcd")
    e_ = ca.get("/apps/calendrier-jumeau/etat").json()
    assert e_["nom"] == "calendrier-jumeau" and e_["emplacement"] is None
    ca.post("/apps/calendrier-jumeau/redemarrer")
    assert [a["corps"]["applicationId"] for a in eb["appels"]
            if a["chemin"] == "/api/application.reload"] == ["B1"]


def test_preuve_reste_indexee_sur_l_app_d_origine(eb):
    _poser_deux_emplacements()
    assert ca.get("/apps/calendrier/preuve").json()["app_id"] == "A1"


def test_manifeste_rollback_renvoie_au_retour_arriere_apres_reset():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    assert ("PAS après un reset pour revenir à l'instance précédente → livraison_retour_arriere"
            in caps["livraison_rollback"]["description"])


def test_manifeste_declare_les_outils_donnees():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    e, v = caps["livraison_donnees_exporter"], caps["livraison_donnees_verifier"]
    assert (e["chemin"], e["methode"], e["sensibilite"]) == ("/contrats/{app}/exporter", "POST", "reversible")
    assert e["action"] is True
    assert (v["chemin"], v["methode"]) == ("/contrats/{app}/verifier", "POST")
    assert v["sensibilite"] == "reversible" and v["action"] is True   # le vérificateur crée une copie
    for x in (e, v):
        assert set(x["params"]) == {"app", "utilisateur"} and x["relayer_erreurs"] is True
    routes = {(r.path, tuple(sorted(r.methods))) for r in main.app.routes if hasattr(r, "methods")}
    assert ("/contrats/{app_}/exporter", ("POST",)) in routes
    assert ("/contrats/{app_}/verifier", ("POST",)) in routes


def test_manifeste_outils_donnees_3b():
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    assert caps["livraison_donnees_verifier"]["fournit_preuve"] == "paquet_verifie"
    rz, rs = caps["livraison_donnees_reinitialiser"], caps["livraison_donnees_restituer"]
    assert (rz["sensibilite"], rz["prerequis"], rz["chemin"]) == ("donnees", ["paquet_verifie"],
                                                                   "/contrats/{app}/reinitialiser")
    assert (rs["sensibilite"], rs["chemin"]) == ("donnees", "/contrats/{app}/restituer")
    assert "prerequis" not in rs and rz["action"] is True and rs["action"] is True
    assert {"app", "utilisateur"} <= set(rz["params"]) and "paquet_id" in rs["params"]
    assert rz["relayer_erreurs"] is True and rs["relayer_erreurs"] is True
    assert "paquet_id" in rs["description"] and "vide" in rs["description"]   # sémantique implicite
    assert "504" in rz["description"] and "verifier" in rz["description"]
