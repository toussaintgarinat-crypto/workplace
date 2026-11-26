"""Faux serveur Dokploy (httpx.MockTransport) reproduisant les contrats v0.31.4.

Formes relevées sur le vrai Dokploy : `project.all` ne liste que
{applicationId, name, applicationStatus} par application ; `application.one` porte
`appName`, `rollbackActive`, `deployments[]` (du plus ancien au plus récent) ;
`start/stop/reload/redeploy` renvoient l'objet application entier (avec `refreshToken`).
"""
import json
from datetime import datetime, timezone

import httpx


def _gras(app: dict) -> dict:
    return {**app, "refreshToken": "SECRET", "env": "TOKEN=SECRET", "password": "SECRET"}


def fabrique_transport(etat: dict) -> httpx.MockTransport:
    etat.setdefault("appels", [])

    def rep(code, corps):
        return httpx.Response(code, json=corps)

    def handler(req: httpx.Request) -> httpx.Response:
        chemin = req.url.path
        corps = json.loads(req.content) if req.content else None
        etat["appels"].append({"methode": req.method, "chemin": chemin, "corps": corps,
                               "params": dict(req.url.params)})
        if req.headers.get("x-api-key") != etat.get("cle"):
            return rep(401, {"message": "Unauthorized"})
        if etat.get("limite"):
            return rep(429, {"message": "Rate limit exceeded"})
        apps = etat["apps"]
        if chemin == "/api/project.all":
            liste = [{"applicationId": a["applicationId"], "name": a["name"],
                      "applicationStatus": a["applicationStatus"]} for a in apps.values()]
            return rep(200, [{"projectId": "P1", "name": "temoin", "environments": [
                {"environmentId": "E1", "name": "production", "isDefault": True,
                 "applications": liste, "postgres": [], "compose": []}]}])
        if chemin == "/api/application.one":
            a = apps.get(req.url.params.get("applicationId"))
            return rep(200, _gras(a)) if a else rep(404, {"message": "NOT_FOUND"})
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
