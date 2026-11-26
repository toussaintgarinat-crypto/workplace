"""Faux serveur Dokploy (httpx.MockTransport) reproduisant les contrats v0.31.4.

Formes relevées sur le vrai Dokploy : `project.all` ne liste que
{applicationId, name, applicationStatus} par application ; `application.one` porte
`appName`, `rollbackActive`, `deployments[]` (du plus ancien au plus récent) ;
`start/stop/reload/redeploy` renvoient l'objet application entier (avec `refreshToken`).
"""
import json
from typing import Optional
from datetime import datetime, timezone

import httpx


def _gras(app: dict, etat: Optional[dict] = None) -> dict:
    sortie = {**app, "refreshToken": "SECRET", "password": "SECRET",
              "env": app.get("env", "TOKEN=SECRET")}
    if etat is not None:
        sortie["domains"] = [dict(d, refreshToken="SECRET") for d in etat["domaines"].values()
                             if d.get("applicationId") == app["applicationId"]]
    return sortie


def _type_ok(v, t) -> bool:
    if t is int:
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, t)


def _valide(corps, schema: dict) -> bool:
    """Comme la validation du vrai Dokploy : champ requis absent ou de mauvais type -> refus."""
    return isinstance(corps, dict) and all(
        k in corps and _type_ok(corps[k], t) for k, t in schema.items())


SCHEMAS = {
    "/api/application.create": {"name": str, "environmentId": str},
    "/api/application.saveGitProvider": {
        "applicationId": str, "customGitUrl": str, "customGitBranch": str,
        "customGitBuildPath": str, "watchPaths": list, "enableSubmodules": bool},
    "/api/application.saveBuildType": {
        "applicationId": str, "buildType": str, "dockerfile": str, "dockerContextPath": str},
    "/api/application.saveEnvironment": {
        "applicationId": str, "env": str, "buildArgs": str, "buildSecrets": str,
        "createEnvFile": bool},
    "/api/domain.create": {"host": str, "path": str, "port": int, "https": bool,
                           "applicationId": str, "certificateType": str, "domainType": str},
    "/api/domain.update": {"domainId": str, "host": str, "path": str, "port": int,
                           "https": bool, "certificateType": str, "domainType": str},
    "/api/backup.update": {"backupId": str, "database": str, "schedule": str, "prefix": str,
                           "enabled": bool, "destinationId": str, "keepLatestCount": int,
                           "databaseType": str, "backupType": str},
    "/api/application.deploy": {"applicationId": str},
}
CHAMPS_STOCKES = {
    "/api/application.saveGitProvider": ("customGitUrl", "customGitBranch",
                                         "customGitBuildPath", "watchPaths", "enableSubmodules"),
    "/api/application.saveBuildType": ("buildType", "dockerfile", "dockerContextPath"),
    "/api/application.saveEnvironment": ("env", "buildArgs", "buildSecrets", "createEnvFile"),
}


def fabrique_transport(etat: dict) -> httpx.MockTransport:
    etat.setdefault("appels", [])
    etat.setdefault("domaines", {})
    etat.setdefault("backups", {})

    def rep(code, corps):
        return httpx.Response(code, json=corps)

    def handler(req: httpx.Request) -> httpx.Response:
        # Panne injectée : `pannes[chemin]` = liste consommée appel par appel (True -> 500,
        # un entier -> ce statut HTTP, "lecture" -> appel TRAITÉ puis réponse perdue
        # (httpx.ReadError), "connexion" -> jamais parti (httpx.ConnectError, non enregistré),
        # False -> appel normal).
        pannes = (etat.get("pannes") or {}).get(req.url.path)
        panne = pannes.pop(0) if pannes else False
        if panne == "connexion":
            raise httpx.ConnectError("connexion refusée", request=req)
        if panne == "lecture":
            traiter(req)
            raise httpx.ReadError("réponse perdue", request=req)
        return traiter(req, panne)

    def traiter(req: httpx.Request, panne=False) -> httpx.Response:
        chemin = req.url.path
        corps = json.loads(req.content) if req.content else None
        etat["appels"].append({"methode": req.method, "chemin": chemin, "corps": corps,
                               "params": dict(req.url.params)})
        if req.headers.get("x-api-key") != etat.get("cle"):
            return rep(401, {"message": "Unauthorized"})
        if etat.get("limite"):
            return rep(429, {"message": "Rate limit exceeded"})
        if panne:
            return rep(500 if panne is True else panne, {"message": "panne injectée"})
        apps = etat["apps"]
        if chemin == "/api/project.all":
            liste = [{"applicationId": a["applicationId"], "name": a["name"],
                      "applicationStatus": a["applicationStatus"]} for a in apps.values()]
            return rep(200, [{"projectId": "P1", "name": "temoin", "environments": [
                {"environmentId": "E1", "name": "production", "isDefault": True,
                 "applications": liste, "postgres": [], "compose": []}]}])
        if chemin == "/api/application.one":
            a = apps.get(req.url.params.get("applicationId"))
            if not a:
                return rep(404, {"message": "NOT_FOUND"})
            if a.get("_lectures_deploy") is not None:
                # `running` à la 1re lecture après `application.deploy`, final à la 2e.
                a["_lectures_deploy"] += 1
                if a["_lectures_deploy"] >= 2:
                    a["_lectures_deploy"] = None
                    a["applicationStatus"] = "error" if etat.get("deploy_echoue") else "done"
                    if a.get("deployments"):
                        a["deployments"][-1]["status"] = a["applicationStatus"]
            return rep(200, _gras(a, etat))
        if chemin in ("/api/project.duplicate", "/api/application.delete"):
            return rep(401, {"message": "unauthorized to access resource"})
        if chemin in SCHEMAS and not _valide(corps, SCHEMAS[chemin]):
            return rep(400, {"message": "Input validation failed"})
        if chemin == "/api/application.create":
            n = etat["compteur"] = etat.get("compteur", 0) + 1
            nouv = {"applicationId": f"NEW{n}", "name": corps["name"], "appName": f"{corps['name']}-n{n}",
                    "description": corps.get("description"), "environmentId": corps["environmentId"],
                    "applicationStatus": "idle", "env": "", "deployments": []}
            apps[nouv["applicationId"]] = nouv
            return rep(200, _gras(nouv))
        if chemin in ("/api/application.saveGitProvider", "/api/application.saveBuildType",
                      "/api/application.saveEnvironment"):
            a = apps.get((corps or {}).get("applicationId"))
            if not a:
                return rep(404, {"message": "NOT_FOUND"})
            a.update({k: corps[k] for k in CHAMPS_STOCKES[chemin]})
            a["sourceType"] = a.get("sourceType") or "git"
            return rep(200, True)
        if chemin == "/api/application.deploy":
            a = apps.get((corps or {}).get("applicationId"))
            if not a:
                return rep(404, {"message": "NOT_FOUND"})
            a["applicationStatus"] = "running"
            a["_lectures_deploy"] = 0
            # Comme le réel : chaque déploiement laisse une trace (du plus ancien au plus récent).
            n = etat["compteur_deploiements"] = etat.get("compteur_deploiements", 0) + 1
            quand = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%S}.{n:06d}Z"
            a.setdefault("deployments", []).append(
                {"deploymentId": f"DEP{n}", "title": "deploy", "status": "running",
                 "createdAt": quand, "finishedAt": None, "rollbackId": None})
            return httpx.Response(200, content=b"")
        if chemin == "/api/domain.create":
            if corps["applicationId"] not in apps:
                return rep(404, {"message": "NOT_FOUND"})
            n = etat["compteur_domaines"] = etat.get("compteur_domaines", 0) + 1
            d = {"domainId": f"DOM{n}", "host": corps["host"], "port": corps["port"],
                 "path": corps.get("path"), "https": corps.get("https"),
                 "applicationId": corps["applicationId"]}
            etat["domaines"][d["domainId"]] = d
            return rep(200, d)
        if chemin == "/api/domain.update":
            d = etat["domaines"].get(corps.get("domainId"))
            if not d:
                return rep(404, {"message": "NOT_FOUND"})
            d.update(host=corps["host"], port=corps["port"])
            return httpx.Response(200, content=b"")
        if chemin == "/api/backup.one":
            b = etat["backups"].get(req.url.params.get("backupId"))
            return rep(200, b) if b else rep(404, {"message": "NOT_FOUND"})
        if chemin == "/api/backup.update":
            b = etat["backups"].get(corps.get("backupId"))
            if not b:
                return rep(404, {"message": "NOT_FOUND"})
            b.update({k: v for k, v in corps.items() if k != "backupId"})
            return httpx.Response(200, content=b"")
        if chemin == "/api/application.redeploy":
            # Réel (v0.31.4) : 200 avec un corps VIDE (non JSON).
            a = apps.get((corps or {}).get("applicationId"))
            return httpx.Response(200, content=b"") if a else rep(404, {"message": "NOT_FOUND"})
        if chemin in ("/api/application.reload",
                      "/api/application.start", "/api/application.stop"):
            a = apps.get((corps or {}).get("applicationId"))
            return rep(200, _gras(a)) if a else rep(404, {"message": "NOT_FOUND"})
        if chemin == "/api/rollback.rollback":
            # Réel : corps vide aussi (comme redeploy) ; la brique doit l'accepter.
            return httpx.Response(200, content=b"")
        if chemin == "/api/deployment.readLogs":
            did = req.url.params.get("deploymentId")
            return rep(200, etat.get("logs", {}).get(did, "ligne de log\n"))
        if chemin == "/api/backup.manualBackupPostgres":
            fichiers = etat.get("fichiers", {}).get((corps or {}).get("backupId"))
            if fichiers is None:
                return rep(404, {"message": "NOT_FOUND"})
            if etat.get("echec_sauvegarde"):
                return rep(500, {"message": "boom"})
            if not etat.get("sauvegarde_sans_fichier"):
                maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
                fichiers.append({"Name": f"{maintenant}.sql.gz", "Size": 1113, "Path": "SECRET",
                                 "ModTime": maintenant, "IsDir": False})
            return rep(200, True)
        if chemin == "/api/backup.listBackupFilesByBackupId":
            fichiers = etat.get("fichiers", {}).get(req.url.params.get("backupId"))
            return rep(200, fichiers) if fichiers is not None else rep(404, {"message": "NOT_FOUND"})
        if chemin == "/api/volumeBackups.runManually":
            etat.setdefault("volumes_lances", []).append((corps or {}).get("volumeBackupId"))
            return httpx.Response(200, content=b"")   # réel : corps vide
        return rep(404, {"message": "NOT_FOUND"})

    return httpx.MockTransport(handler)
