import asyncio
import httpx
import pytest
from dokploy import Dokploy, DokployErreur, MESSAGE_DELAI_MUTATION, peut_etre_appliquee
from faux_dokploy import fabrique_transport


def etat():
    return {"cle": "k", "appels": [], "limite": False, "apps": {
        "A1": {"applicationId": "A1", "name": "calendrier", "appName": "calendrier-x",
               "applicationStatus": "done", "rollbackActive": True,
               "deployments": [
                   {"deploymentId": "D1", "title": "v1", "status": "done", "createdAt": "t1",
                    "finishedAt": "t1b", "rollbackId": None, "logPath": "/secret/chemin"},
                   {"deploymentId": "D2", "title": "v2", "status": "done", "createdAt": "t2",
                    "finishedAt": "t2b", "rollbackId": "R2"}]}}}


def cli(e, cle="k"):
    return Dokploy("http://d.test", cle, transport=fabrique_transport(e))


def run(c):
    return asyncio.run(c)


def test_apps_aplati_sans_champs_inutiles():
    # Forme réelle de project.all : pas d'appName dans la liste des applications.
    r = run(cli(etat()).apps())
    assert r == [{"id": "A1", "nom": "calendrier", "projet": "temoin",
                  "environnement": "production", "statut": "done"}]


def test_app_liste_blanche_et_deploiements_recents_d_abord():
    r = run(cli(etat()).app("A1"))
    assert r["app_name"] == "calendrier-x" and r["rollback_actif"] is True
    assert [d["id"] for d in r["deploiements"]] == ["D2", "D1"]
    assert r["deploiements"][0] == {"id": "D2", "titre": "v2", "statut": "done",
                                    "debut": "t2", "fin": "t2b", "rollback_id": "R2"}
    assert "logPath" not in str(r) and "refreshToken" not in str(r)


def test_cle_invalide_message_honnete_sans_secret():
    with pytest.raises(DokployErreur) as e:
        run(cli(etat(), cle="mauvaise").apps())
    assert e.value.statut == 401 and "mauvaise" not in e.value.message


def test_limite_429_dit_clairement_la_cause():
    e = etat()
    e["limite"] = True
    with pytest.raises(DokployErreur) as ex:
        run(cli(e).apps())
    assert ex.value.statut == 429 and "limite" in ex.value.message.lower()


def test_app_inconnue_404():
    with pytest.raises(DokployErreur) as ex:
        run(cli(etat()).app("ZZ"))
    assert ex.value.statut == 404


def test_redemarrer_envoie_app_name_et_id_et_ne_renvoie_pas_le_gras():
    e = etat()
    r = run(cli(e).redemarrer("A1", "calendrier-x"))
    # I2 : app_name déjà résolu par la route → un SEUL appel (pas de application.one redondant)
    assert [a["chemin"] for a in e["appels"]] == ["/api/application.reload"]
    corps = e["appels"][0]["corps"]
    assert corps == {"applicationId": "A1", "appName": "calendrier-x"}
    assert "refreshToken" not in str(r) and "SECRET" not in str(r)
    assert r["ok"] is True and r["id"] == "A1"


def test_deployer_envoie_titre_et_ne_renvoie_pas_le_gras():
    e = etat()
    r = run(cli(e).deployer("A1", "mise à jour"))
    a = [x for x in e["appels"] if x["chemin"] == "/api/application.redeploy"][0]
    assert a["methode"] == "POST"
    assert a["corps"] == {"applicationId": "A1", "title": "mise à jour"}
    assert "refreshToken" not in str(r) and "SECRET" not in str(r)
    assert r["ok"] is True


def test_rollback_envoie_rollback_id():
    e = etat()
    r = run(cli(e).rollback("R1"))
    assert e["appels"][-1]["corps"] == {"rollbackId": "R1"}
    assert r["ok"] is True and r["rollback_id"] == "R1"


def test_logs_deploiement_non_tronques_avant_masquage():
    # I4 : la troncature se fait APRÈS masquage (dans la route), jamais ici.
    e = etat()
    e["logs"] = {"D1": "x" * 50000 + "FIN"}
    r = run(cli(e).logs_deploiement("D1", tail=5))
    assert isinstance(r, str) and len(r) == 50003 and r.endswith("FIN")
    a = [x for x in e["appels"] if x["chemin"] == "/api/deployment.readLogs"][0]
    assert a["params"] == {"deploymentId": "D1", "tail": "5"}


def test_logs_tail_borne_a_10000():
    e = etat()
    run(cli(e).logs_deploiement("D1", tail=999999))
    a = [x for x in e["appels"] if x["chemin"] == "/api/deployment.readLogs"][0]
    assert a["params"]["tail"] == "10000"


def test_reponse_json_invalide_erreur_honnete():
    def pas_json(req):
        return httpx.Response(200, content=b"<html>proxy</html>")
    c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(pas_json))
    with pytest.raises(DokployErreur) as ex:
        run(c.apps())
    assert "illisible" in ex.value.message.lower() and "proxy" not in ex.value.message


def test_erreur_500_ne_relaie_pas_le_corps():
    def mal(req):
        return httpx.Response(500, json={"message": "TRACE secrete"})
    c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(mal))
    with pytest.raises(DokployErreur) as ex:
        run(c.apps())
    assert ex.value.statut == 500 and "secrete" not in ex.value.message


def test_reseau_coupe_message_honnete():
    def boom(req):
        raise httpx.ConnectError("x")
    c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(boom))
    with pytest.raises(DokployErreur) as ex:
        run(c.apps())
    assert "joignable" in ex.value.message.lower()


def test_timeout_message_honnete():
    def lent(req):
        raise httpx.ReadTimeout("x")
    c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(lent))
    with pytest.raises(DokployErreur) as ex:
        run(c.apps())
    assert "délai" in ex.value.message.lower()


def test_redemarrer_sans_app_name_refuse_sans_appel():
    e = etat()
    with pytest.raises(DokployErreur):
        run(cli(e).redemarrer("A1", ""))
    assert e["appels"] == []


def _transport_mutation(exc):
    def h(req):
        if req.method == "POST":
            raise exc
        return httpx.Response(200, json=[])
    return httpx.MockTransport(h)


@pytest.mark.parametrize("appel", [lambda c: c.redemarrer("A1", "x"),
                                   lambda c: c.deployer("A1", "t"),
                                   lambda c: c.rollback("R1")])
def test_mutation_timeout_apres_envoi_peut_avoir_ete_executee(appel):
    c = Dokploy("http://d.test", "k", transport=_transport_mutation(httpx.ReadTimeout("x")))
    with pytest.raises(DokployErreur) as ex:
        run(appel(c))
    assert ex.value.statut == 504
    assert ex.value.message == ("Délai dépassé : l'action a peut-être été exécutée — vérifie "
                                "avec livraison_etat avant de réessayer.")


@pytest.mark.parametrize("exc", [httpx.ConnectError("x"), httpx.ConnectTimeout("x")])
def test_mutation_erreur_de_connexion_reste_injoignable(exc):
    c = Dokploy("http://d.test", "k", transport=_transport_mutation(exc))
    with pytest.raises(DokployErreur) as ex:
        run(c.deployer("A1", "t"))
    assert "injoignable" in ex.value.message and ex.value.statut != 504
    assert ex.value.envoyee is False and not peut_etre_appliquee(ex.value)


@pytest.mark.parametrize("exc", [httpx.ReadError("x"), httpx.RemoteProtocolError("x"),
                                 httpx.ReadTimeout("x"), httpx.WriteError("x")])
def test_mutation_erreur_apres_envoi_peut_avoir_ete_appliquee(exc):
    c = Dokploy("http://d.test", "k", transport=_transport_mutation(exc))
    with pytest.raises(DokployErreur) as ex:
        run(c.deployer("A1", "t"))
    assert ex.value.envoyee is True and peut_etre_appliquee(ex.value)


@pytest.mark.parametrize("statut,appliquee", [(500, True), (502, True), (503, True),
                                              (504, True), (400, False), (401, False),
                                              (404, False), (429, False)])
def test_mutation_statut_http_peut_avoir_ete_appliquee(statut, appliquee):
    c = Dokploy("http://d.test", "k",
                transport=httpx.MockTransport(lambda r: httpx.Response(statut, json={})))
    with pytest.raises(DokployErreur) as ex:
        run(c.deployer("A1", "t"))
    assert ex.value.envoyee is True and peut_etre_appliquee(ex.value) is appliquee


def test_delais_lecture_20s_mutation_60s(monkeypatch):
    vus = []
    vrai = httpx.AsyncClient.__init__

    def espion(self, *a, **k):
        vus.append(k.get("timeout"))
        vrai(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", espion)
    c = cli(etat())
    run(c.apps())
    run(c.deployer("A1", "t"))
    assert vus == [20.0, 60.0]


def test_mutation_corps_vide_2xx_est_un_succes():
    """Constaté en réel : redeploy et rollback répondent 200 sans corps JSON."""
    e = etat()
    c = cli(e)
    assert run(c.deployer("A1", "t"))["ok"] is True
    assert run(c.rollback("R1"))["ok"] is True


def test_lecture_corps_invalide_reste_une_erreur():
    import httpx
    c = Dokploy("http://d.test", "k",
                transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"")))
    with pytest.raises(DokployErreur):
        run(c.apps())


def _etat_sauvegarde():
    e = etat()
    e["fichiers"] = {"B1": [{"Name": "vieux.sql.gz", "Size": 10, "ModTime":
                             "2026-11-25T10:00:00.000000000Z", "IsDir": False}]}
    return e


def test_sauvegarder_base_appelle_la_route_et_ne_renvoie_que_ok():
    e = _etat_sauvegarde()
    r = run(cli(e).sauvegarder_base("B1"))
    assert r == {"ok": True, "backup_id": "B1"}
    a = [x for x in e["appels"] if x["chemin"] == "/api/backup.manualBackupPostgres"][0]
    assert a["methode"] == "POST" and a["corps"] == {"backupId": "B1"}


def test_fichiers_sauvegarde_liste_blanche_plus_recent_d_abord_sans_dossiers():
    e = _etat_sauvegarde()
    e["fichiers"]["B1"] += [{"Name": "dossier", "IsDir": True, "ModTime": "2026-11-27T00:00:00Z"},
                            {"Name": "recent.sql.gz", "Size": 20, "Path": "SECRET",
                             "ModTime": "2026-11-26T10:00:00.000000000Z", "IsDir": False}]
    r = run(cli(e).fichiers_sauvegarde("B1"))
    assert [f["nom"] for f in r] == ["recent.sql.gz", "vieux.sql.gz"]
    assert set(r[0]) == {"nom", "taille", "date"} and "SECRET" not in str(r)


def test_fichiers_sauvegarde_inconnue_404():
    with pytest.raises(DokployErreur) as ex:
        run(cli(_etat_sauvegarde()).fichiers_sauvegarde("ZZ"))
    assert ex.value.statut == 404


def test_sauvegarder_volume_corps_vide_est_un_succes():
    e = _etat_sauvegarde()
    assert run(cli(e).sauvegarder_volume("V1")) == {"ok": True, "volume_backup_id": "V1"}
    assert e["volumes_lances"] == ["V1"]


# --- Task 3 (S247 2b) : créer, configurer, déployer, domaines, rebasculer la sauvegarde ---

def _appels(e, chemin):
    return [a for a in e["appels"] if a["chemin"] == chemin]


def test_environnement_id_premier_projet_premier_environnement():
    assert run(cli(etat()).environnement_id()) == "E1"


def test_environnement_id_aucun_leve():
    c = Dokploy("http://d.test", "k",
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    with pytest.raises(DokployErreur):
        run(c.environnement_id())


def test_app_complete_liste_blanche_garde_env_sans_secrets():
    e = etat()
    e["apps"]["A1"].update(sourceType="git", customGitUrl="u", customGitBranch="main",
                           customGitBuildPath="/", buildType="dockerfile", dockerfile="Dockerfile",
                           dockerContextPath=".", env="DATABASE_URL=postgres://x")
    e["domaines"] = {"D9": {"domainId": "D9", "host": "a.test", "port": 80, "path": "/",
                            "https": False, "applicationId": "A1", "certificateType": "none"}}
    r = run(cli(e).app_complete("A1"))
    assert r["env"] == "DATABASE_URL=postgres://x"
    assert r["domains"] == [{"domainId": "D9", "host": "a.test", "port": 80, "path": "/",
                             "https": False}]
    assert r["applicationStatus"] == "done" and r["appName"] == "calendrier-x"
    assert set(r) == {"applicationId", "name", "appName", "applicationStatus", "sourceType",
                      "customGitUrl", "customGitBranch", "customGitBuildPath", "buildType",
                      "dockerfile", "dockerContextPath", "env", "domains"}
    assert "refreshToken" not in str(r) and "password" not in str(r) and "SECRET" not in str(r)


def test_app_complete_inconnue_404_et_message_sans_env():
    e = etat()
    with pytest.raises(DokployErreur) as ex:
        run(cli(e).app_complete("ZZ"))
    assert ex.value.statut == 404
    assert ex.value.message == "Ressource Dokploy introuvable."
    assert "TOKEN" not in ex.value.message and "SECRET" not in ex.value.message


def test_aucune_erreur_ne_contient_le_contenu_de_env():
    secret = "DATABASE_URL=postgres://user:MOTDEPASSE@h/db"
    corps_piege = {"applicationId": "A1", "env": secret, "message": secret}
    for code in (401, 404, 429, 500):
        c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(
            lambda r, code=code: httpx.Response(code, json=corps_piege)))
        for appel in (lambda: c.app_complete("A1"), lambda: c.ecrire_env("A1", secret)):
            with pytest.raises(DokployErreur) as ex:
                run(appel())
            assert "MOTDEPASSE" not in str(ex.value) and "MOTDEPASSE" not in ex.value.message


def test_creer_app_corps_exact_et_retour():
    e = etat()
    r = run(cli(e).creer_app("E1", "temoin-b", "jumeau"))
    assert r == {"id": "NEW1", "app_name": "temoin-b-n1"}
    assert _appels(e, "/api/application.create")[0]["corps"] == {
        "name": "temoin-b", "environmentId": "E1", "description": "jumeau"}
    assert "NEW1" in e["apps"]


def test_configurer_source_deux_appels_corps_exacts():
    e = etat()
    src = {"customGitUrl": "https://git/x.git", "customGitBranch": "main",
           "customGitBuildPath": "/", "buildType": "dockerfile",
           "dockerfile": "Dockerfile", "dockerContextPath": "."}
    assert run(cli(e).configurer_source("A1", src)) is None
    assert [a["chemin"] for a in e["appels"]] == ["/api/application.saveGitProvider",
                                                   "/api/application.saveBuildType"]
    assert e["appels"][0]["corps"] == {
        "applicationId": "A1", "customGitUrl": "https://git/x.git", "customGitBranch": "main",
        "customGitBuildPath": "/", "watchPaths": [], "enableSubmodules": False}
    assert e["appels"][1]["corps"] == {
        "applicationId": "A1", "buildType": "dockerfile", "dockerfile": "Dockerfile",
        "dockerContextPath": ".", "dockerBuildStage": "", "herokuVersion": None,
        "railpackVersion": None, "publishDirectory": None, "isStaticSpa": None}


def test_ecrire_env_corps_exact():
    e = etat()
    assert run(cli(e).ecrire_env("A1", "A=1\nB=2")) is None
    assert _appels(e, "/api/application.saveEnvironment")[0]["corps"] == {
        "applicationId": "A1", "env": "A=1\nB=2", "buildArgs": "", "buildSecrets": "",
        "createEnvFile": True}
    assert e["apps"]["A1"]["env"] == "A=1\nB=2"


def test_creer_domaine_et_changer_hote():
    e = etat()
    c = cli(e)
    did = run(c.creer_domaine("A1", "b.test", 3000))
    assert did == "DOM1"
    assert _appels(e, "/api/domain.create")[0]["corps"] == {
        "host": "b.test", "path": "/", "port": 3000, "https": False, "applicationId": "A1",
        "certificateType": "none", "domainType": "application"}
    assert run(c.changer_hote(did, "c.test", 3001)) is None
    assert _appels(e, "/api/domain.update")[0]["corps"] == {
        "domainId": "DOM1", "host": "c.test", "path": "/", "port": 3001, "https": False,
        "certificateType": "none", "domainType": "application"}
    assert e["domaines"]["DOM1"]["host"] == "c.test"


class _Horloge:
    def __init__(self):
        self.t = 0.0
        self.dormis = []

    def __call__(self):
        return self.t

    async def dormir(self, s):
        self.dormis.append(s)
        self.t += s


def test_deployer_et_attendre_done():
    e = etat()
    h = _Horloge()
    r = run(cli(e).deployer_et_attendre("A1", "reset", horloge=h, dormir=h.dormir))
    assert r == "done"
    assert _appels(e, "/api/application.deploy")[0]["corps"] == {"applicationId": "A1"}
    assert h.dormis == [5]    # running à la 1re lecture, done à la 2e


def test_deployer_et_attendre_error():
    e = etat()
    e["deploy_echoue"] = True
    h = _Horloge()
    with pytest.raises(DokployErreur) as ex:
        run(cli(e).deployer_et_attendre("A1", "reset", horloge=h, dormir=h.dormir))
    assert ex.value.message == "Le déploiement de l'instance neuve a échoué."


def test_deployer_et_attendre_delai():
    e = etat()
    c = cli(e)

    async def toujours_running(id_):
        return {"applicationStatus": "running"}
    c.app_complete = toujours_running
    h = _Horloge()
    with pytest.raises(DokployErreur) as ex:
        run(c.deployer_et_attendre("A1", "reset", delai_s=20, pas_s=5, horloge=h,
                                   dormir=h.dormir))
    assert ex.value.message.startswith("Délai dépassé")
    assert len(h.dormis) == 4


def _etat_backup():
    e = etat()
    e["backups"] = {"B1": {"backupId": "B1", "schedule": "0 2 * * *", "prefix": "pg",
                           "enabled": True, "destinationId": "DEST", "keepLatestCount": 7,
                           "databaseType": "postgres", "backupType": "database",
                           "database": "ancienne", "secretInterne": "SECRET"}}
    return e


def test_rebaser_sauvegarde_relit_puis_ne_change_que_database():
    e = _etat_backup()
    assert run(cli(e).rebaser_sauvegarde("B1", "neuve")) is None
    assert [(a["methode"], a["chemin"]) for a in e["appels"]] == [
        ("GET", "/api/backup.one"), ("POST", "/api/backup.update")]
    assert e["appels"][0]["params"] == {"backupId": "B1"}
    assert e["appels"][1]["corps"] == {
        "backupId": "B1", "database": "neuve", "schedule": "0 2 * * *", "prefix": "pg",
        "enabled": True, "destinationId": "DEST", "keepLatestCount": 7,
        "databaseType": "postgres", "backupType": "database", "secretInterne": "SECRET"}
    assert e["backups"]["B1"]["database"] == "neuve"


def test_rebaser_sauvegarde_recopie_tous_les_scalaires_de_backup_one():
    """Forme riche de `backup.one` (Dokploy 0.31.4) : tout scalaire est recopié (les champs
    requis par apiUpdateBackup y sont), relations et horodatages en lecture seule écartés."""
    e = etat()
    e["backups"] = {"B1": {
        "backupId": "B1", "appName": "bk-x", "schedule": "0 2 * * *", "enabled": True,
        "database": "ancienne", "prefix": "pg", "serviceName": None, "destinationId": "DEST",
        "keepLatestCount": 7, "backupType": "database", "databaseType": "postgres",
        "customName": None,
        "composeId": None, "postgresId": "PG1", "mariadbId": None, "mysqlId": None,
        "mongoId": None, "userId": None, "metadata": None,
        "createdAt": "2026-11-01T00:00:00Z", "updatedAt": "2026-11-02T00:00:00Z",
        "destination": {"destinationId": "DEST", "secretAccessKey": "SECRET"},
        "postgres": {"postgresId": "PG1", "databasePassword": "SECRET"}, "mysql": None,
        "mariadb": None, "mongo": None, "compose": None, "user": None, "deployments": [],
        "liste": [1, 2]}}
    run(cli(e).rebaser_sauvegarde("B1", "neuve"))
    corps = e["appels"][1]["corps"]
    assert corps == {
        "backupId": "B1", "appName": "bk-x", "schedule": "0 2 * * *", "enabled": True,
        "database": "neuve", "prefix": "pg", "serviceName": None, "destinationId": "DEST",
        "keepLatestCount": 7, "backupType": "database", "databaseType": "postgres",
        "composeId": None, "postgresId": "PG1", "mariadbId": None, "mysqlId": None,
        "mongoId": None, "userId": None, "metadata": None}


def test_rebaser_sauvegarde_lecture_en_echec_n_est_pas_envoyee():
    e = _etat_backup()
    e["pannes"] = {"/api/backup.one": [True]}
    with pytest.raises(DokployErreur) as ex:
        run(cli(e).rebaser_sauvegarde("B1", "neuve"))
    assert ex.value.envoyee is False and not peut_etre_appliquee(ex.value)


def test_base_sauvegarde_lit_database():
    assert run(cli(_etat_backup()).base_sauvegarde("B1")) == "ancienne"


def test_rebaser_sauvegarde_backup_one_refuse_ne_poste_rien():
    e = _etat_backup()
    with pytest.raises(DokployErreur) as ex:
        run(cli(e).rebaser_sauvegarde("ZZ", "neuve"))
    assert ex.value.statut == 404
    assert [a["chemin"] for a in e["appels"]] == ["/api/backup.one"]


def test_le_faux_refuse_duplicate_et_delete_comme_le_vrai():
    e = etat()
    c = cli(e)
    for chemin in ("/api/project.duplicate", "/api/application.delete"):
        with pytest.raises(DokployErreur) as ex:
            run(c._requete("POST", chemin, json={"x": 1}))
        assert ex.value.statut == 401


def test_nouvelles_methodes_cle_inconnue_401():
    with pytest.raises(DokployErreur) as ex:
        run(cli(etat(), cle="mauvaise").creer_app("E1", "n", "d"))
    assert ex.value.statut == 401


# --- Revue Task 3 : faux strict, attente tolérante, entrées malformées ---

def _post_brut(e, chemin, corps):
    t = fabrique_transport(e)

    async def f():
        async with httpx.AsyncClient(base_url="http://d.test", transport=t) as c:
            return await c.post(chemin, json=corps, headers={"x-api-key": "k"})
    return run(f())


VALIDES = {
    "/api/application.create": {"name": "n", "environmentId": "E1"},
    "/api/application.saveGitProvider": {
        "applicationId": "A1", "customGitUrl": "u", "customGitBranch": "b",
        "customGitBuildPath": "/", "watchPaths": [], "enableSubmodules": False},
    "/api/application.saveBuildType": {
        "applicationId": "A1", "buildType": "dockerfile", "dockerfile": "D",
        "dockerContextPath": "."},
    "/api/application.saveEnvironment": {
        "applicationId": "A1", "env": "", "buildArgs": "", "buildSecrets": "",
        "createEnvFile": True},
    "/api/domain.create": {"host": "h", "path": "/", "port": 80, "https": False,
                           "applicationId": "A1", "certificateType": "none",
                           "domainType": "application"},
    "/api/application.deploy": {"applicationId": "A1"},
}


@pytest.mark.parametrize("chemin", list(VALIDES))
def test_faux_valide_accepte_puis_refuse_champ_manquant_ou_mauvais_type(chemin):
    assert _post_brut(etat(), chemin, VALIDES[chemin]).status_code == 200
    for k in VALIDES[chemin]:
        manquant = {x: v for x, v in VALIDES[chemin].items() if x != k}
        r = _post_brut(etat(), chemin, manquant)
        assert r.status_code == 400 and r.json() == {"message": "Input validation failed"}
        faux = dict(VALIDES[chemin], **{k: object_mauvais(VALIDES[chemin][k])})
        assert _post_brut(etat(), chemin, faux).status_code == 400


def object_mauvais(v):
    return 12345 if isinstance(v, (str, list)) or isinstance(v, bool) else "x"


def test_faux_domain_update_et_backup_update_valident():
    e = _etat_backup()
    e["domaines"] = {"D1": {"domainId": "D1", "host": "a", "port": 1, "applicationId": "A1"}}
    ok_d = {"domainId": "D1", "host": "h", "path": "/", "port": 80, "https": False,
            "certificateType": "none", "domainType": "application"}
    assert _post_brut(e, "/api/domain.update", ok_d).status_code == 200
    assert _post_brut(e, "/api/domain.update", dict(ok_d, port="80")).status_code == 400
    assert _post_brut(e, "/api/domain.update", {**ok_d, "domainId": "ZZ"}).status_code == 404
    ok_b = {"backupId": "B1", "database": "d", "schedule": "s", "prefix": "p", "enabled": True,
            "destinationId": "X", "keepLatestCount": 3, "databaseType": "postgres",
            "backupType": "database"}
    assert _post_brut(e, "/api/backup.update", ok_b).status_code == 200
    assert _post_brut(e, "/api/backup.update", dict(ok_b, enabled="oui")).status_code == 400
    assert _post_brut(e, "/api/backup.update",
                      {k: v for k, v in ok_b.items() if k != "prefix"}).status_code == 400


def test_faux_domain_create_application_inconnue_404():
    r = _post_brut(etat(), "/api/domain.create", dict(VALIDES["/api/domain.create"],
                                                      applicationId="ZZ"))
    assert r.status_code == 404


def test_faux_ne_stocke_pas_les_cles_inconnues():
    e = etat()
    corps = dict(VALIDES["/api/application.saveGitProvider"], intrus="X", refreshToken="Y")
    assert _post_brut(e, "/api/application.saveGitProvider", corps).status_code == 200
    corps = dict(VALIDES["/api/application.saveBuildType"], intrus2="X")
    assert _post_brut(e, "/api/application.saveBuildType", corps).status_code == 200
    a = e["apps"]["A1"]
    assert "intrus" not in a and "refreshToken" not in a and "intrus2" not in a
    assert a["customGitUrl"] == "u" and a["buildType"] == "dockerfile"


def test_client_vers_faux_strict_erreur_400_honnete():
    with pytest.raises(DokployErreur) as ex:
        run(cli(etat())._requete("POST", "/api/application.create", json={"name": "n"}))
    assert ex.value.statut == 400


def _client_lectures(sequence):
    """app_complete scripté : exceptions DokployErreur ou statuts."""
    c = cli(etat())
    it = iter(sequence)

    async def lire(id_):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return {"applicationStatus": v}
    c.app_complete = lire
    return c


def test_attendre_tolere_une_lecture_transitoire():
    c = _client_lectures([DokployErreur("x", 503), "done"])
    h = _Horloge()
    assert run(c.deployer_et_attendre("A1", "t", horloge=h, dormir=h.dormir)) == "done"
    assert h.dormis == [5]


def test_attendre_compteur_remis_a_zero_apres_lecture_reussie():
    seq = [DokployErreur("x"), DokployErreur("x", 429), "running", DokployErreur("x", 500),
           DokployErreur("x", 502), "done"]
    h = _Horloge()
    assert run(_client_lectures(seq).deployer_et_attendre(
        "A1", "t", horloge=h, dormir=h.dormir)) == "done"


def test_attendre_trois_lectures_transitoires_consecutives_leve():
    c = _client_lectures([DokployErreur("x"), DokployErreur("x", 502), DokployErreur("x", 429)])
    h = _Horloge()
    with pytest.raises(DokployErreur) as ex:
        run(c.deployer_et_attendre("A1", "t", horloge=h, dormir=h.dormir))
    assert "l'état du déploiement est inconnu" in ex.value.message
    assert len(h.dormis) == 2


def test_attendre_401_leve_immediatement():
    c = _client_lectures([DokployErreur("Clé API Dokploy refusée.", 401), "done"])
    h = _Horloge()
    with pytest.raises(DokployErreur) as ex:
        run(c.deployer_et_attendre("A1", "t", horloge=h, dormir=h.dormir))
    assert ex.value.statut == 401 and h.dormis == []


def test_configurer_source_cle_manquante_valeur_error_sans_valeur_ni_appel():
    e = etat()
    src = {"customGitUrl": "https://secret-url/x.git", "customGitBranch": "main",
           "customGitBuildPath": "/", "buildType": "dockerfile", "dockerfile": "Dockerfile"}
    with pytest.raises(ValueError) as ex:
        run(cli(e).configurer_source("A1", src))
    assert "dockerContextPath" in str(ex.value) and "secret-url" not in str(ex.value)
    assert e["appels"] == []


@pytest.mark.parametrize("projets", [{"a": 1}, ["x"], [{"environments": ["x"]}],
                                     [{"environments": 3}]])
def test_environnement_id_elements_malformes_erreur_honnete(projets):
    c = Dokploy("http://d.test", "k",
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json=projets)))
    with pytest.raises(DokployErreur) as ex:
        run(c.environnement_id())
    assert "inattendue" in ex.value.message


def test_timeout_sur_creer_app_est_un_504_avec_le_message_mutation():
    c = Dokploy("http://d.test", "k", transport=_transport_mutation(httpx.ReadTimeout("x")))
    with pytest.raises(DokployErreur) as ex:
        run(c.creer_app("E1", "n", "d"))
    assert ex.value.statut == 504 and ex.value.message == MESSAGE_DELAI_MUTATION
