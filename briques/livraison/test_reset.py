"""Orchestrateur du reset bleu/vert (S247 2b, Task 6) : faux Dokploy strict + faux exécuteur."""
import asyncio
import logging
import os
import re
from pathlib import Path

import httpx
import pytest

import operations
import reset
import sauvegarde
from client_executeur import Executeur, ExecuteurErreur
from dokploy import Dokploy
from faux_dokploy import fabrique_transport

RE_GENEREE = re.compile(r"[a-z_][a-z0-9_]{0,30}_v[0-9a-f]{8}")
APP = "calendrier-familial"
PUBLIC, TEST = "cal.exemple.fr", "cal-test.exemple.fr"
ENV = ("NODE_ENV=production\nDATABASE_URL=postgres://temoin:SECRETXYZ@pg:5432/temoin\n"
       "PASSWORD=SECRETXYZ\n")
ENTREE = {"bases": [{"base": "temoin", "service": "postgres-temoin-abc", "utilisateur": "temoin",
                     "sauvegarde_id": "BK1", "prefixe_s3": "temoin/pg"}],
          "volumes": [],
          "reset": {"variable_env": "DATABASE_URL", "domaine_public": PUBLIC,
                    "domaine_test": TEST, "port_app": 3000, "sante_chemin": "/sante"}}


def run(co):
    return asyncio.run(co)


async def _sans_attente(_s):
    return None


class FauxEx:
    """Exécuteur à scénarios : `verdicts` et `recomptes` sont consommés appel par appel."""

    def __init__(self, verdicts=None, recomptes=None, echec_supprimer=False, cloner_leve=False,
                 bloquer_supprimer=False):
        self.appels = []
        self.bloquer_supprimer = bloquer_supprimer
        self.origine = {"evenements": 42, "membres": 3}
        self.verdicts = list(verdicts or [])
        self.recomptes = list(recomptes or [])
        self.echec_supprimer = echec_supprimer
        self.cloner_leve = cloner_leve
        self.bases = set()

    async def cloner(self, service, utilisateur, base, objet, nouvelle_base):
        self.appels.append(("cloner", base, objet, nouvelle_base))
        assert RE_GENEREE.fullmatch(nouvelle_base) and nouvelle_base != base
        if self.cloner_leve:
            raise ExecuteurErreur("L'exécuteur a répondu 500 : SECRETXYZ", 500)
        verdict = self.verdicts.pop(0) if self.verdicts else "valide"
        if verdict == "valide":
            self.bases.add(nouvelle_base)
        return {"ok": True, "verdict": verdict, "raison": None, "nouvelle_base": nouvelle_base,
                "comptages_origine": dict(self.origine),
                "comptages_restaures": dict(self.origine), "nettoyage": "ok"}

    async def comptages(self, service, utilisateur, base):
        self.appels.append(("comptages", base))
        return {"ok": True, "comptages": self.recomptes.pop(0) if self.recomptes
                else dict(self.origine)}

    async def supprimer_base(self, service, utilisateur, base):
        self.appels.append(("supprimer_base", base))
        assert RE_GENEREE.fullmatch(base), base
        if self.bloquer_supprimer:
            await asyncio.sleep(3600)
        if self.echec_supprimer:
            raise ExecuteurErreur("boom")
        self.bases.discard(base)
        return {"ok": True}

    def noms(self, quoi):
        return [a[-1] for a in self.appels if a[0] == quoi]


def _monde(env=ENV, domaine_a=False):
    etat = {"cle": "k", "appels": [], "apps": {"A1": {
        "applicationId": "A1", "name": APP, "appName": "cal-x", "applicationStatus": "done",
        "sourceType": "git", "customGitUrl": "https://forgejo.test/temoin/cal.git",
        "customGitBranch": "main", "customGitBuildPath": "/", "buildType": "dockerfile",
        "dockerfile": "Dockerfile", "dockerContextPath": ".", "env": env, "deployments": []}},
        "backups": {"BK1": {"backupId": "BK1", "database": "temoin", "schedule": "0 3 * * *",
                            "prefix": "temoin/pg", "enabled": True, "destinationId": "S3",
                            "keepLatestCount": 7, "databaseType": "postgres",
                            "backupType": "database"}},
        "fichiers": {"BK1": []}}
    if domaine_a:
        etat["domaines"] = {"DOM0": {"domainId": "DOM0", "host": PUBLIC, "port": 3000, "path": "/",
                                     "https": False, "applicationId": "A1"}}
    return etat


def _dok(etat):
    return Dokploy("http://d.test", "k", transport=fabrique_transport(etat))


def _appels(etat, chemin):
    return [a for a in etat["appels"] if a["chemin"] == chemin]


def _hotes(etat):
    return {d["applicationId"]: d["host"] for d in etat["domaines"].values()}


def _jumeau(etat):
    return next(i for i, a in etat["apps"].items() if a["name"] == APP + "-jumeau")


async def _sain(_h, _c):
    return True


async def _malade(_h, _c):
    return False


def _lancer(etat, ex, sante=_sain, entree=ENTREE, type_="reset"):
    oid = operations.demarrer(APP, type_)
    run(reset.reset(_dok(etat), ex, entree, APP, "A1", oid, sante=sante, dormir=_sans_attente))
    return operations.lire(APP)


def _fichier_etat() -> str:
    return (Path(os.environ["LIVRAISON_DATA"]) / "operations.json").read_text()


# ── nominal ──

def test_premier_reset_cree_le_jumeau_et_bascule():
    etat, ex = _monde(), FauxEx()
    s = _lancer(etat, ex)
    b = _jumeau(etat)
    assert s["op"]["etat"] == "reussie", s["op"]
    assert s["actif"] == "B" and s["emplacements"]["B"]["app_id"] == b
    nouvelle = s["base_active"]
    assert RE_GENEREE.fullmatch(nouvelle) and nouvelle.startswith("temoin_v")
    assert s["base_precedente"] == "temoin"
    assert _hotes(etat) == {"A1": TEST, b: PUBLIC}
    assert etat["backups"]["BK1"]["database"] == nouvelle
    # l'inactif a reçu l'env de l'actif, une seule variable réécrite
    assert etat["apps"][b]["env"] == ENV.replace("@pg:5432/temoin", f"@pg:5432/{nouvelle}")
    assert etat["apps"][b]["customGitUrl"] == "https://forgejo.test/temoin/cal.git"
    # l'actif n'a jamais été touché (ni env, ni source, ni déploiement)
    for chemin in ("/api/application.saveEnvironment", "/api/application.saveGitProvider",
                   "/api/application.saveBuildType", "/api/application.deploy"):
        assert all(a["corps"]["applicationId"] != "A1" for a in _appels(etat, chemin)), chemin
    assert etat["apps"]["A1"]["env"] == ENV
    m = s["op"]["message"]
    assert m.startswith("Les données écrites dans l'ancienne instance après ")
    assert "(UTC" in m and "restent dans l'ancienne base temoin" in m
    assert "instance B" in m and nouvelle in m and "2 tables" in m and len(m) <= 300
    assert ex.noms("supprimer_base") == []      # rien à nettoyer au premier reset
    assert ex.appels[0][1] == "temoin" and ex.appels[0][2].startswith("temoin/pg/")


def test_premier_provisionnement_sans_domaine_cree_le_domaine_public():
    etat = _monde()
    _lancer(etat, FauxEx())
    crees = [a["corps"] for a in _appels(etat, "/api/domain.create")]
    assert {(c["applicationId"], c["host"], c["port"]) for c in crees} == {
        ("A1", PUBLIC, 3000), (_jumeau(etat), TEST, 3000)}


def test_domaine_existant_de_l_actif_est_reutilise():
    etat = _monde(domaine_a=True)
    s = _lancer(etat, FauxEx())
    assert s["op"]["etat"] == "reussie"
    assert s["emplacements"]["A"]["domaine_id"] == "DOM0"
    assert all(a["corps"]["applicationId"] != "A1" for a in _appels(etat, "/api/domain.create"))


def test_domaine_actif_inattendu_refuse():
    etat = _monde(domaine_a=True)
    etat["domaines"]["DOM0"]["host"] = "autre.exemple.fr"
    s = _lancer(etat, FauxEx())
    assert s["op"]["etat"] == "echec" and s["op"]["message"] == "configuration_manquante"
    assert _appels(etat, "/api/application.create") == []


def test_second_reset_reutilise_l_inactif_et_troisieme_supprime_n_moins_2():
    etat, ex = _monde(), FauxEx()
    s1 = _lancer(etat, ex)
    g1 = s1["base_active"]
    s2 = _lancer(etat, ex)
    assert s2["op"]["etat"] == "reussie", s2["op"]
    g2 = s2["base_active"]
    assert len(_appels(etat, "/api/application.create")) == 1
    assert s2["actif"] == "A" and s2["base_precedente"] == g1 and g2 != g1
    assert _hotes(etat) == {"A1": PUBLIC, _jumeau(etat): TEST}
    # l'actif (B) lisait g1 : l'inactif (A) reçoit son env repointé sur g2
    assert f"/{g2}\n" in etat["apps"]["A1"]["env"]
    # N-2 = la base d'origine : jamais supprimée
    assert ex.noms("supprimer_base") == []
    s3 = _lancer(etat, ex)
    assert s3["op"]["etat"] == "reussie" and s3["actif"] == "B"
    assert ex.noms("supprimer_base") == [g1]
    assert s3["base_precedente"] == g2
    # le second reset a cloné depuis la base ACTIVE (g1), pas l'originale
    assert [a[1] for a in ex.appels if a[0] == "cloner"] == ["temoin", g1, g2]


def test_nettoyage_n_moins_2_en_echec_n_invalide_pas_le_reset():
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    _lancer(etat, ex)
    ex.echec_supprimer = True
    s = _lancer(etat, ex)
    assert s["op"]["etat"] == "reussie" and "non supprimée" in s["op"]["message"]


# ── sabotages : rien ne bascule ──

def _aucune_bascule(etat, s, ex, motif):
    assert s["op"]["etat"] == "echec" and s["op"]["message"] == motif, s["op"]
    assert s["op"]["motif"] == motif
    assert _appels(etat, "/api/domain.update") == []
    assert etat["backups"]["BK1"]["database"] == "temoin"
    assert s["actif"] == "A" and s["base_active"] == "temoin"
    assert etat["apps"]["A1"]["env"] == ENV
    assert ex.bases == set()        # toute base neuve créée a été supprimée


def test_sabotage_clone_invalide():
    etat, ex = _monde(), FauxEx(verdicts=["invalide"])
    s = _lancer(etat, ex)
    _aucune_bascule(etat, s, ex, "clonage_invalide")
    assert len(ex.noms("supprimer_base")) == 1     # drop if exists, par sûreté


def test_sabotage_executeur_en_erreur():
    etat, ex = _monde(), FauxEx(cloner_leve=True)
    s = _lancer(etat, ex)
    _aucune_bascule(etat, s, ex, "erreur_executeur")


def test_sabotage_deploiement_error():
    etat, ex = _monde(), FauxEx()
    etat["deploy_echoue"] = True
    _aucune_bascule(etat, _lancer(etat, ex), ex, "deploiement_echoue")


def test_sabotage_deploiement_incertain_504_sans_reessai():
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/application.deploy": [504]}
    s = _lancer(etat, ex)
    _aucune_bascule(etat, s, ex, "deploiement_incertain")
    assert len(_appels(etat, "/api/application.deploy")) == 1
    # 504 : incertain d'emblée, sans relire le statut du jumeau après la mutation
    b = _jumeau(etat)
    i = etat["appels"].index(_appels(etat, "/api/application.deploy")[0])
    assert not [a for a in etat["appels"][i + 1:] if a["chemin"] == "/api/application.one"
                and a["params"].get("applicationId") == b]


def test_sabotage_deploiement_500_relit_le_statut():
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/application.deploy": [True]}
    s = _lancer(etat, ex)
    _aucune_bascule(etat, s, ex, "deploiement_incertain")


def test_sabotage_sante_ko():
    etat, ex = _monde(), FauxEx()
    _aucune_bascule(etat, _lancer(etat, ex, sante=_malade), ex, "sante_ko")


def test_sabotage_env_inattendu():
    etat, ex = _monde(env="NODE_ENV=production\nPASSWORD=SECRETXYZ\n"), FauxEx()
    s = _lancer(etat, ex)
    assert s["op"]["message"] == "env_inattendu"
    assert _appels(etat, "/api/application.saveEnvironment") == []
    assert _appels(etat, "/api/domain.update") == [] and ex.bases == set()


def test_sabotage_recomptage_different_trois_fois():
    autre = {"evenements": 43, "membres": 3}
    etat, ex = _monde(), FauxEx(recomptes=[autre, autre, autre])
    s = _lancer(etat, ex)
    _aucune_bascule(etat, s, ex, "ecritures_en_cours")
    assert len(ex.noms("cloner")) == 3 and len(set(ex.noms("supprimer_base"))) == 3
    assert s["op"]["essais"] == 3


def test_ecritures_pendant_l_operation_puis_stables():
    etat, ex = _monde(), FauxEx(recomptes=[{"evenements": 43, "membres": 3}])
    s = _lancer(etat, ex)
    assert s["op"]["etat"] == "reussie" and s["op"]["essais"] == 2
    premiere, seconde = ex.noms("cloner")
    assert ex.noms("supprimer_base") == [premiere] and s["base_active"] == seconde


def test_echec_du_premier_changer_hote_annule_tout():
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/domain.update": [True]}
    s = _lancer(etat, ex)
    assert s["op"]["etat"] == "echec" and s["op"]["message"].startswith("bascule_incomplete")
    assert _hotes(etat) == {"A1": PUBLIC, _jumeau(etat): TEST}
    assert etat["backups"]["BK1"]["database"] == "temoin" and ex.bases == set()
    ups = [a["corps"]["database"] for a in _appels(etat, "/api/backup.update")]
    assert ups == [ex.noms("cloner")[0], "temoin"]


def test_rebasculement_de_la_sauvegarde_impossible():
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/backup.update": [True, True]}
    s = _lancer(etat, ex)
    assert s["op"]["message"] == "sauvegarde_non_rebasee"
    assert _appels(etat, "/api/domain.update") == [] and ex.bases == set()


def test_sauvegarde_sans_fichier_recent():
    etat, ex = _monde(), FauxEx()
    etat["sauvegarde_sans_fichier"] = True
    s = _lancer(etat, ex)
    assert s["op"]["message"] == "sauvegarde_absente" and ex.appels == []


# ── bascule ──

def _message_bascule_incomplete(s, nouvelle):
    assert s["op"]["etat"] == "echec" and s["op"]["motif"] == "bascule_incomplete"
    assert s["op"]["message"] == (
        f"bascule_incomplete : vérifier les domaines ; sauvegarde sur {nouvelle} ; "
        f"base neuve {nouvelle} conservée ; l'état indique encore la base temoin")


def test_echec_du_second_changer_hote_remet_les_hotes():
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/domain.update": [False, True]}
    s = _lancer(etat, ex)
    b = _jumeau(etat)
    nouvelle = ex.noms("cloner")[0]
    _message_bascule_incomplete(s, nouvelle)
    assert _hotes(etat) == {"A1": PUBLIC, b: TEST}
    assert s["actif"] == "A" and s["base_active"] == "temoin"
    # le public a peut-être écrit dans la base neuve : ni suppression ni sauvegarde défaite
    assert nouvelle in ex.bases and nouvelle not in ex.noms("supprimer_base")
    assert etat["backups"]["BK1"]["database"] == nouvelle
    assert [a["corps"]["database"] for a in _appels(etat, "/api/backup.update")] == [nouvelle]
    # jamais sans hôte public : l'actif retrouve le public AVANT que l'inactif ne le rende
    ups = [(a["corps"]["domainId"], a["corps"]["host"]) for a in _appels(etat, "/api/domain.update")]
    dom_a, dom_b = s["emplacements"]["A"]["domaine_id"], s["emplacements"]["B"]["domaine_id"]
    assert ups == [(dom_b, PUBLIC), (dom_a, TEST), (dom_a, PUBLIC), (dom_b, TEST)]


def test_hotes_non_remis_garde_base_et_sauvegarde():
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/domain.update": [False, True, True, True]}
    s = _lancer(etat, ex)
    nouvelle = ex.noms("cloner")[0]
    _message_bascule_incomplete(s, nouvelle)
    # l'état réel est inconnu : on ne détruit pas la base qui sert peut-être le public
    assert nouvelle in ex.bases and etat["backups"]["BK1"]["database"] == nouvelle
    assert nouvelle not in ex.noms("supprimer_base")


def test_echec_disque_a_la_bascule_remet_les_hotes(monkeypatch):
    etat, ex = _monde(), FauxEx()

    def panne(*a, **k):
        raise OSError("disque")
    monkeypatch.setattr(operations, "basculer_etat", panne)
    s = _lancer(etat, ex)
    nouvelle = ex.noms("cloner")[0]
    _message_bascule_incomplete(s, nouvelle)
    assert _hotes(etat)["A1"] == PUBLIC and s["actif"] == "A"
    assert nouvelle in ex.bases and etat["backups"]["BK1"]["database"] == nouvelle


def test_premier_changer_hote_en_504_conserve_la_base():
    # 504 sur une mutation : Dokploy l'a peut-être appliquée, le public a peut-être basculé
    etat, ex = _monde(), FauxEx()
    etat["pannes"] = {"/api/domain.update": [504]}
    s = _lancer(etat, ex)
    nouvelle = ex.noms("cloner")[0]
    _message_bascule_incomplete(s, nouvelle)
    assert nouvelle in ex.bases and etat["backups"]["BK1"]["database"] == nouvelle


# ── secrets, verrou, interruption, configuration ──

def test_aucune_fuite_de_l_env(caplog):
    caplog.set_level(logging.DEBUG)
    for ex, extra in ((FauxEx(), {}), (FauxEx(cloner_leve=True), {}),
                      (FauxEx(), {"deploy_echoue": True})):
        etat = _monde()
        etat.update(extra)
        s = _lancer(etat, ex)
        assert "SECRETXYZ" not in str(s) and "SECRETXYZ" not in _fichier_etat()
    assert "SECRETXYZ" not in caplog.text
    assert all("SECRETXYZ" not in str(r.args) for r in caplog.records)


def test_verrou_second_reset_refuse():
    operations.demarrer(APP, "reset")
    with pytest.raises(operations.OperationEnCours):
        operations.demarrer(APP, "reset")


def test_reset_ne_leve_jamais_meme_si_terminer_echoue(monkeypatch):
    etat = _monde()
    oid = operations.demarrer(APP, "reset")

    def panne(*a, **k):
        raise OSError("disque")
    monkeypatch.setattr(operations, "etape", panne)
    monkeypatch.setattr(operations, "terminer", panne)
    run(reset.reset(_dok(etat), FauxEx(), ENTREE, APP, "A1", oid, sante=_sain,
                    dormir=_sans_attente))
    assert _appels(etat, "/api/domain.update") == []


def test_bloc_reset_absent():
    etat, ex = _monde(), FauxEx()
    s = _lancer(etat, ex, entree={**ENTREE, "reset": None})
    assert s["op"]["message"] == "configuration_manquante" and etat["appels"] == []


def test_interruption_compense_et_relance():
    etat, ex = _monde(), FauxEx()

    async def sante_bloquee(_h, _c):
        await asyncio.sleep(3600)

    async def scenario():
        oid = operations.demarrer(APP, "reset")
        t = asyncio.create_task(reset.reset(_dok(etat), ex, ENTREE, APP, "A1", oid,
                                            sante=sante_bloquee, dormir=_sans_attente))
        while not ex.bases:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(scenario())
    s = operations.lire(APP)
    assert s["op"]["etat"] == "interrompue" and s["op"]["message"] == "interrompue_par_arret"
    assert ex.bases == set() and _appels(etat, "/api/domain.update") == []


def test_interruption_apres_bascule_enregistree_ne_defait_rien():
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    _lancer(etat, ex)
    ex.bloquer_supprimer = True
    n = len(_appels(etat, "/api/domain.update"))

    async def scenario():
        oid = operations.demarrer(APP, "reset")
        t = asyncio.create_task(reset.reset(_dok(etat), ex, ENTREE, APP, "A1", oid,
                                            sante=_sain, dormir=_sans_attente))
        while not ex.noms("supprimer_base"):
            await asyncio.sleep(0.01)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(scenario())
    s = operations.lire(APP)
    nouvelle = ex.noms("cloner")[-1]
    assert s["op"]["etat"] == "interrompue" and s["op"]["message"].startswith(
        "interrompue_par_arret")
    assert s["actif"] == "B" and s["base_active"] == nouvelle
    assert len(_appels(etat, "/api/domain.update")) == n + 2      # aucun hôte remis
    assert _hotes(etat) == {"A1": TEST, _jumeau(etat): PUBLIC}
    assert etat["backups"]["BK1"]["database"] == nouvelle and nouvelle in ex.bases


@pytest.mark.parametrize("base", ["Temoin", "tem-oin", "a" * 32, "temoin_v0a1b2c3d", "",
                                  "1temoin"])
def test_nom_de_base_d_origine_invalide_refuse(base):
    etat, ex = _monde(), FauxEx()
    entree = {**ENTREE, "bases": [{**ENTREE["bases"][0], "base": base}]}
    s = _lancer(etat, ex, entree=entree)
    assert s["op"]["message"] == "configuration_manquante" and etat["appels"] == []


def test_entree_effective_refusee():
    """Garde : reset() doit recevoir l'entrée BRUTE de l'inventaire, pas base_effective()."""
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    effective = reset.base_effective(ENTREE, operations.lire(APP))
    n = len(etat["appels"])
    s = _lancer(etat, ex, entree=effective)
    assert s["op"]["message"] == "configuration_manquante" and len(etat["appels"]) == n


def test_sabotage_au_second_reset_ne_touche_pas_l_actif_b():
    etat, ex = _monde(), FauxEx()
    s1 = _lancer(etat, ex)
    g1, b = s1["base_active"], _jumeau(etat)
    env_b = etat["apps"][b]["env"]
    n = len(_appels(etat, "/api/domain.update"))
    s = _lancer(etat, ex, sante=_malade)
    assert s["op"]["etat"] == "echec" and s["op"]["message"] == "sante_ko"
    assert len(_appels(etat, "/api/domain.update")) == n
    assert etat["apps"][b]["env"] == env_b
    assert all(a["corps"]["applicationId"] != b for a in
               _appels(etat, "/api/application.saveEnvironment")[1:])
    assert s["actif"] == "B" and s["base_active"] == g1
    assert etat["backups"]["BK1"]["database"] == g1 and ex.bases == {g1}
    assert _hotes(etat) == {"A1": TEST, b: PUBLIC}


def test_sante_par_defaut_ferme_sans_url(monkeypatch):
    monkeypatch.delenv("LIVRAISON_TRAEFIK_URL", raising=False)
    assert run(reset.sante_http(TEST, "/sante", dormir=_sans_attente)) is False


def test_sante_par_defaut_envoie_l_hote(monkeypatch):
    monkeypatch.setenv("LIVRAISON_TRAEFIK_URL", "http://traefik.test")
    vus = []

    def h(req):
        vus.append((req.headers["host"], req.url.path))
        return httpx.Response(503 if len(vus) < 3 else 302)
    t = httpx.MockTransport(h)
    assert run(reset.sante_http(TEST, "/sante", dormir=_sans_attente, transport=t)) is True
    assert vus == [(TEST, "/sante")] * 3
    vus.clear()
    t2 = httpx.MockTransport(lambda r: (vus.append(1), httpx.Response(500))[1])
    assert run(reset.sante_http(TEST, "/", dormir=_sans_attente, transport=t2)) is False
    assert len(vus) == 3


# ── retour arrière ──

def _retour(etat, sante=_sain):
    oid = operations.demarrer(APP, "retour")
    run(reset.retour_arriere(_dok(etat), ENTREE, APP, oid, sante=sante))
    return operations.lire(APP)


def test_retour_arriere_reechange_les_hotes():
    etat, ex = _monde(), FauxEx()
    s1 = _lancer(etat, ex)
    s = _retour(etat)
    assert s["op"]["etat"] == "reussie", s["op"]
    assert s["actif"] == "A" and s["base_active"] == "temoin"
    assert s["base_precedente"] == s1["base_active"]
    assert _hotes(etat) == {"A1": PUBLIC, _jumeau(etat): TEST}
    assert etat["backups"]["BK1"]["database"] == "temoin"
    assert "emplacement B" in s["op"]["message"] and s1["base_active"] in s["op"]["message"]
    assert reset.peut_retour_arriere(s)


def test_retour_arriere_sans_base_precedente_refuse():
    etat = _monde()
    assert not reset.peut_retour_arriere(operations.lire(APP))
    s = _retour(etat)
    assert s["op"]["etat"] == "echec" and s["op"]["message"] == "aucun_retour_possible"
    assert _appels(etat, "/api/domain.update") == []


def test_retour_arriere_apres_deux_resets():
    etat, ex = _monde(), FauxEx()
    s1 = _lancer(etat, ex)
    s2 = _lancer(etat, ex)
    s = _retour(etat)
    assert s["op"]["etat"] == "reussie", s["op"]
    assert s["actif"] == "B" and s["base_active"] == s1["base_active"]
    assert etat["backups"]["BK1"]["database"] == s1["base_active"]
    assert s["base_precedente"] == s2["base_active"]


def _refus_retour_invalide(etat, ex):
    hotes, sauv = _hotes(etat), etat["backups"]["BK1"]["database"]
    n_dom, n_bk = len(_appels(etat, "/api/domain.update")), len(_appels(etat, "/api/backup.update"))
    s = _retour(etat)
    assert s["op"]["etat"] == "echec" and s["op"]["message"] == "retour_invalide", s["op"]
    assert _hotes(etat) == hotes and etat["backups"]["BK1"]["database"] == sauv
    assert len(_appels(etat, "/api/domain.update")) == n_dom
    assert len(_appels(etat, "/api/backup.update")) == n_bk
    return s


def test_retour_arriere_refuse_apres_un_reset_echoue():
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    s2 = _lancer(etat, ex, sante=_malade)
    assert s2["op"]["message"] == "sante_ko" and s2["retour_invalide"] is True
    assert not reset.peut_retour_arriere(s2)
    s = _refus_retour_invalide(etat, ex)
    assert s["actif"] == "B"


def test_retour_arriere_refuse_si_l_env_de_l_inactif_a_change(monkeypatch):
    # même si le drapeau n'a pas pu être écrit, l'env de l'inactif est vérifié
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)

    def panne(*a, **k):
        raise OSError("disque")
    monkeypatch.setattr(operations, "invalider_retour", panne)
    s2 = _lancer(etat, ex, sante=_malade)
    assert s2["op"]["message"] == "sante_ko" and not s2.get("retour_invalide")
    assert reset.peut_retour_arriere(s2)
    _refus_retour_invalide(etat, ex)


def test_retour_arriere_refuse_si_env_illisible():
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    etat["apps"]["A1"]["env"] = "NODE_ENV=production\n"
    _refus_retour_invalide(etat, ex)


def test_reset_reussi_apres_echec_retablit_le_retour():
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    _lancer(etat, ex, sante=_malade)
    s = _lancer(etat, ex)
    assert s["op"]["etat"] == "reussie" and s["retour_invalide"] is False
    assert _retour(etat)["op"]["etat"] == "reussie"


def test_retour_arriere_sante_ko_ne_bascule_pas():
    etat, ex = _monde(), FauxEx()
    _lancer(etat, ex)
    n = len(_appels(etat, "/api/domain.update"))
    s = _retour(etat, sante=_malade)
    assert s["op"]["message"] == "sante_ko" and s["actif"] == "B"
    assert len(_appels(etat, "/api/domain.update")) == n


# ── base effective ──

def test_base_effective():
    assert reset.base_effective(ENTREE, None) is not ENTREE
    assert reset.base_effective(ENTREE, None)["bases"][0]["base"] == "temoin"
    e = reset.base_effective(ENTREE, {"base_active": "temoin_v0a1b2c3d"})
    assert e["bases"][0]["base"] == "temoin_v0a1b2c3d" and e["reset"] == ENTREE["reset"]
    assert ENTREE["bases"][0]["base"] == "temoin"      # l'entrée d'origine n'est pas modifiée
    assert reset.base_effective({"bases": [], "volumes": [{"v": 1}]},
                                {"base_active": "x_v0a1b2c3d"})["bases"] == []


def test_verifier_suit_la_base_active():
    etat = _monde()
    vus = []

    def h(req):
        import json
        vus.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "verdict": "valide",
                                         "comptages_restaures": {"e": 1}})
    ex = Executeur("http://exec.test", "k", transport=httpx.MockTransport(h))
    e = reset.base_effective(ENTREE, {"base_active": "temoin_v0a1b2c3d"})
    r = run(sauvegarde.verifier(_dok(etat), ex, e, "A1"))
    assert r["verdict"] == "valide" and vus[0]["base"] == "temoin_v0a1b2c3d"
    assert run(sauvegarde.sauvegarder(_dok(etat), e))["bases"] == ["temoin_v0a1b2c3d"]
