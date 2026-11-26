import asyncio
import httpx
import pytest
from dokploy import Dokploy, DokployErreur
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
