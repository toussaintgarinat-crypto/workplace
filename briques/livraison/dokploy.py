"""Client HTTP Dokploy v0.31.4 (auth `x-api-key`). Liste blanche de champs en sortie."""
import asyncio
import time
from typing import Callable, Optional

import httpx

TAIL_MAX = 10000
CHAMPS_APP_COMPLETE = ("applicationId", "name", "appName", "applicationStatus", "sourceType",
                       "customGitUrl", "customGitBranch", "customGitBuildPath", "buildType",
                       "dockerfile", "dockerContextPath", "env")
CHAMPS_DOMAINE = ("domainId", "host", "port", "path", "https")
# Clés de `backup.one` en lecture seule (relations, horodatages) : jamais renvoyées à
# `backup.update`. Tout le reste (scalaire) est recopié tel quel (voir rebaser_sauvegarde).
CLES_SAUVEGARDE_LECTURE_SEULE = frozenset({"createdAt", "updatedAt", "destination", "postgres",
                                           "mysql", "mariadb", "mongo", "compose", "user",
                                           "deployments"})
CLES_SOURCE = ("customGitUrl", "customGitBranch", "customGitBuildPath", "buildType",
               "dockerfile", "dockerContextPath")
LECTURES_TRANSITOIRES_MAX = 3
DELAI_LECTURE = 20.0
DELAI_MUTATION = 60.0
MESSAGE_DELAI_MUTATION = ("Délai dépassé : l'action a peut-être été exécutée — vérifie avec "
                          "livraison_etat avant de réessayer.")


class DokployErreur(Exception):
    """Erreur honnête : `.message` ne contient jamais la clé ni un corps brut."""

    def __init__(self, message: str, statut: Optional[int] = None, envoyee: bool = True):
        super().__init__(message)
        self.message = message
        self.statut = statut
        # False seulement quand la requête n'est provablement JAMAIS partie (connexion refusée,
        # délai de connexion, pool saturé) ; True par défaut (prudence).
        self.envoyee = envoyee


def peut_etre_appliquee(e: DokployErreur) -> bool:
    """Une MUTATION en erreur a-t-elle pu être exécutée par Dokploy ? Oui si la requête est
    partie et que la réponse manque (coupure, délai : statut None/504) ou vaut 5xx ; non si
    elle n'est jamais partie ou si Dokploy l'a refusée (4xx)."""
    return bool(e.envoyee and (e.statut is None or e.statut >= 500))


class Dokploy:
    def __init__(self, base_url: str, cle: str,
                 transport: Optional[httpx.AsyncBaseTransport] = None,
                 delai: float = DELAI_LECTURE, delai_mutation: float = DELAI_MUTATION):
        self._base = base_url.rstrip("/")
        self._cle = cle
        self._transport = transport
        self._delai = delai
        self._delai_mutation = delai_mutation

    async def _requete(self, methode: str, chemin: str, params: Optional[dict] = None,
                       json: Optional[dict] = None):
        mutation = methode != "GET"
        try:
            async with httpx.AsyncClient(
                    base_url=self._base, transport=self._transport,
                    timeout=self._delai_mutation if mutation else self._delai) as c:
                r = await c.request(methode, chemin, params=params, json=json,
                                    headers={"x-api-key": self._cle})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # Avant envoi : la requête n'est jamais partie, rien n'a été exécuté.
            raise DokployErreur("Dokploy injoignable (réseau ou service arrêté).",
                                envoyee=False) from None
        except httpx.TimeoutException:
            # Après envoi (lecture/écriture) : sur une MUTATION, Dokploy a peut-être exécuté
            # l'action. Le dire (504) évite une double exécution à la réapprobation.
            if mutation:
                raise DokployErreur(MESSAGE_DELAI_MUTATION, 504) from None
            raise DokployErreur("Délai dépassé en attendant Dokploy.") from None
        except httpx.HTTPError:
            raise DokployErreur("Échec de la communication avec Dokploy.") from None
        if r.status_code == 401:
            raise DokployErreur("Clé API Dokploy refusée.", 401)
        if r.status_code == 404:
            raise DokployErreur("Ressource Dokploy introuvable.", 404)
        if r.status_code == 429:
            raise DokployErreur("Limite de débit de l'API Dokploy atteinte "
                                "(clé créée sans rateLimitEnabled:false ?).", 429)
        if r.status_code >= 400:
            raise DokployErreur(f"Dokploy a répondu {r.status_code}.", r.status_code)
        try:
            return r.json()
        except ValueError:
            # Constaté en réel (v0.31.4) : `application.redeploy` répond 200 avec un corps
            # NON JSON (vide). Pour une mutation acceptée (2xx), c'est un succès : l'action
            # est partie ; la déclarer en échec ferait réapprouver et ré-exécuter.
            if mutation:
                return None
            raise DokployErreur("Réponse de Dokploy illisible (JSON invalide).",
                                r.status_code) from None

    async def apps(self) -> list[dict]:
        projets = await self._requete("GET", "/api/project.all")
        sortie = []
        for p in projets if isinstance(projets, list) else []:
            for e in p.get("environments") or []:
                for a in e.get("applications") or []:
                    sortie.append({"id": a.get("applicationId"), "nom": a.get("name"),
                                   "projet": p.get("name"), "environnement": e.get("name"),
                                   "statut": a.get("applicationStatus")})
        return sortie

    async def app(self, id_: str) -> dict:
        a = await self._requete("GET", "/api/application.one", params={"applicationId": id_})
        if not isinstance(a, dict):
            raise DokployErreur("Réponse de Dokploy inattendue.")
        deps = sorted((a.get("deployments") or []),
                      key=lambda d: d.get("createdAt") or "", reverse=True)
        return {"id": a.get("applicationId"), "nom": a.get("name"),
                "app_name": a.get("appName"), "statut": a.get("applicationStatus"),
                "rollback_actif": bool(a.get("rollbackActive")),
                "deploiements": [{"id": d.get("deploymentId"), "titre": d.get("title"),
                                  "statut": d.get("status"), "debut": d.get("createdAt"),
                                  "fin": d.get("finishedAt"), "rollback_id": d.get("rollbackId")}
                                 for d in deps]}

    async def logs_deploiement(self, deploiement_id: str, tail: int = 200) -> str:
        tail = max(1, min(int(tail), TAIL_MAX))
        r = await self._requete("GET", "/api/deployment.readLogs",
                                params={"deploymentId": deploiement_id, "tail": str(tail)})
        if not isinstance(r, str):
            raise DokployErreur("Réponse de Dokploy inattendue (logs).")
        return r   # jamais tronqué ici : masquer d'abord, couper ensuite (main.logs_app)

    @staticmethod
    def _minimal(rep, id_: str, app_name: Optional[str] = None) -> dict:
        sortie = {"ok": True, "id": id_}
        if app_name:
            sortie["app_name"] = app_name
        if isinstance(rep, dict):
            if rep.get("applicationStatus"):
                sortie["statut"] = rep["applicationStatus"]
            if rep.get("name"):
                sortie["nom"] = rep["name"]
        return sortie

    async def redemarrer(self, id_: str, app_name: str) -> dict:
        """`app_name` vient de `app()` déjà appelé par la route (pas d'appel redondant)."""
        if not app_name:
            raise DokployErreur("Nom technique de l'application introuvable.")
        rep = await self._requete("POST", "/api/application.reload",
                                  json={"applicationId": id_, "appName": app_name})
        return self._minimal(rep, id_, app_name)

    async def deployer(self, id_: str, titre: str) -> dict:
        rep = await self._requete("POST", "/api/application.redeploy",
                                  json={"applicationId": id_, "title": titre})
        return self._minimal(rep, id_)

    async def rollback(self, rollback_id: str) -> dict:
        await self._requete("POST", "/api/rollback.rollback", json={"rollbackId": rollback_id})
        return {"ok": True, "rollback_id": rollback_id}

    async def sauvegarder_base(self, backup_id: str) -> dict:
        await self._requete("POST", "/api/backup.manualBackupPostgres",
                            json={"backupId": backup_id})
        return {"ok": True, "backup_id": backup_id}

    async def fichiers_sauvegarde(self, backup_id: str) -> list[dict]:
        r = await self._requete("GET", "/api/backup.listBackupFilesByBackupId",
                                params={"backupId": backup_id})
        if not isinstance(r, list):
            raise DokployErreur("Réponse de Dokploy inattendue (fichiers de sauvegarde).")
        fichiers = [{"nom": f.get("Name"), "taille": f.get("Size"), "date": f.get("ModTime")}
                    for f in r if isinstance(f, dict) and not f.get("IsDir") and f.get("Name")]
        return sorted(fichiers, key=lambda f: f["date"] or "", reverse=True)

    async def sauvegarder_volume(self, volume_backup_id: str) -> dict:
        await self._requete("POST", "/api/volumeBackups.runManually",
                            json={"volumeBackupId": volume_backup_id})
        return {"ok": True, "volume_backup_id": volume_backup_id}

    # ------------------------------------------------------------------
    # S247 2b : créer, configurer, déployer, domaines, rebasculer la sauvegarde
    # (formes de corps validées sur le vrai Dokploy 0.31.4, clé limitée au projet témoin)
    # ------------------------------------------------------------------

    async def environnement_id(self) -> str:
        """Premier environnement du premier projet (la clé est limitée à un projet)."""
        projets = await self._requete("GET", "/api/project.all")
        if projets is not None and not isinstance(projets, list):
            raise DokployErreur("Réponse de Dokploy inattendue.")
        for p in projets or []:
            if not isinstance(p, dict) or not isinstance(p.get("environments") or [], list):
                raise DokployErreur("Réponse de Dokploy inattendue.")
            for e in p.get("environments") or []:
                if not isinstance(e, dict):
                    raise DokployErreur("Réponse de Dokploy inattendue.")
                if e.get("environmentId"):
                    return e["environmentId"]
        raise DokployErreur("Aucun environnement Dokploy accessible avec cette clé.")

    async def app_complete(self, id_: str) -> dict:
        """`application.one` filtré sur liste blanche. `env` y figure (l'orchestrateur doit
        le relire pour réécrire UNE variable) : il ne sort jamais de la brique ni dans un log
        ou un message d'erreur (les erreurs de `_requete` ne relaient jamais de corps)."""
        a = await self._requete("GET", "/api/application.one", params={"applicationId": id_})
        if not isinstance(a, dict):
            raise DokployErreur("Réponse de Dokploy inattendue.")
        sortie = {k: a.get(k) for k in CHAMPS_APP_COMPLETE}
        sortie["domains"] = [{k: d.get(k) for k in CHAMPS_DOMAINE}
                             for d in (a.get("domains") or []) if isinstance(d, dict)]
        return sortie

    async def creer_app(self, environment_id: str, nom: str, description: str) -> dict:
        r = await self._requete("POST", "/api/application.create",
                                json={"name": nom, "environmentId": environment_id,
                                      "description": description})
        if not isinstance(r, dict) or not r.get("applicationId"):
            raise DokployErreur("Réponse de Dokploy inattendue (création d'application).")
        return {"id": r["applicationId"], "app_name": r.get("appName")}

    async def configurer_source(self, id_: str, source: dict) -> None:
        for k in CLES_SOURCE:
            if source.get(k) is None:
                raise ValueError(f"Clé de source manquante : {k}")
        await self._requete("POST", "/api/application.saveGitProvider", json={
            "applicationId": id_, "customGitUrl": source.get("customGitUrl"),
            "customGitBranch": source.get("customGitBranch"),
            "customGitBuildPath": source.get("customGitBuildPath"),
            "watchPaths": [], "enableSubmodules": False})
        await self._requete("POST", "/api/application.saveBuildType", json={
            "applicationId": id_, "buildType": source.get("buildType"),
            "dockerfile": source.get("dockerfile"),
            "dockerContextPath": source.get("dockerContextPath"),
            "dockerBuildStage": "", "herokuVersion": None, "railpackVersion": None,
            "publishDirectory": None, "isStaticSpa": None})

    async def ecrire_env(self, id_: str, env: str) -> None:
        await self._requete("POST", "/api/application.saveEnvironment", json={
            "applicationId": id_, "env": env, "buildArgs": "", "buildSecrets": "",
            "createEnvFile": True})

    async def creer_domaine(self, id_: str, host: str, port: int) -> str:
        r = await self._requete("POST", "/api/domain.create", json={
            "host": host, "path": "/", "port": port, "https": False, "applicationId": id_,
            "certificateType": "none", "domainType": "application"})
        if not isinstance(r, dict) or not r.get("domainId"):
            raise DokployErreur("Réponse de Dokploy inattendue (création de domaine).")
        return r["domainId"]

    async def changer_hote(self, domain_id: str, host: str, port: int) -> None:
        await self._requete("POST", "/api/domain.update", json={
            "domainId": domain_id, "host": host, "path": "/", "port": port, "https": False,
            "certificateType": "none", "domainType": "application"})

    async def deployer_et_attendre(self, id_: str, titre: str, delai_s: float = 600,
                                   pas_s: float = 5,
                                   horloge: Callable[[], float] = time.monotonic,
                                   dormir: Callable = asyncio.sleep) -> str:
        # `titre` : `application.deploy` n'en prend pas (corps validé : {applicationId}).
        await self._requete("POST", "/api/application.deploy", json={"applicationId": id_})
        debut = horloge()
        echecs = 0
        while horloge() - debut < delai_s:
            try:
                statut = (await self.app_complete(id_)).get("applicationStatus")
                echecs = 0
            except DokployErreur as e:
                # Lecture transitoire (réseau, délai, 429, 5xx) : le déploiement tourne
                # côté Dokploy ; on retente. 401/404 et autres 4xx : on arrête tout de suite.
                transitoire = e.statut is None or e.statut == 429 or e.statut >= 500
                echecs += 1
                if not transitoire:
                    raise
                if echecs >= LECTURES_TRANSITOIRES_MAX:
                    raise DokployErreur("Lectures de l'état impossibles : l'état du "
                                        "déploiement est inconnu (vérifie-le dans Dokploy).",
                                        e.statut) from None
                await dormir(pas_s)
                continue
            # Limite connue : sur un REdéploiement, un `done` ancien pourrait être lu avant le
            # passage à `running` ; les appelants l'utilisent sur une application fraîche.
            if statut == "done":
                return "done"
            if statut == "error":
                raise DokployErreur("Le déploiement de l'instance neuve a échoué.")
            await dormir(pas_s)
        raise DokployErreur("Délai dépassé : le déploiement de l'instance neuve n'est pas "
                            "terminé (vérifie son état dans Dokploy).")

    async def _config_sauvegarde(self, backup_id: str) -> dict:
        b = await self._requete("GET", "/api/backup.one", params={"backupId": backup_id})
        if not isinstance(b, dict):
            raise DokployErreur("Réponse de Dokploy inattendue (sauvegarde).")
        return b

    async def base_sauvegarde(self, backup_id: str) -> Optional[str]:
        """Nom de la base que la sauvegarde Dokploy vise réellement (`database`)."""
        base = (await self._config_sauvegarde(backup_id)).get("database")
        return base if isinstance(base, str) else None

    async def rebaser_sauvegarde(self, backup_id: str, base: str) -> None:
        """Repointe la sauvegarde sur `base` : relève la config, recopie TOUS ses champs
        scalaires (les champs requis par `apiUpdateBackup` y sont, quels qu'ils soient), sauf
        les clés en lecture seule, et ne change que `database`. Une erreur AVANT l'envoi de
        `backup.update` porte `envoyee=False` : rien n'a été modifié."""
        try:
            b = await self._config_sauvegarde(backup_id)
        except DokployErreur as e:
            raise DokployErreur(e.message, e.statut, envoyee=False) from None
        corps = {k: v for k, v in b.items()
                 if k not in CLES_SAUVEGARDE_LECTURE_SEULE
                 and (v is None or isinstance(v, (str, int, float, bool)))}
        corps.update(backupId=backup_id, database=base)
        await self._requete("POST", "/api/backup.update", json=corps)
