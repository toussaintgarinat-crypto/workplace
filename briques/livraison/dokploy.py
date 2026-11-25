"""Client HTTP Dokploy v0.31.4 (auth `x-api-key`). Liste blanche de champs en sortie."""
from typing import Optional

import httpx

TAIL_MAX = 10000
DELAI_LECTURE = 20.0
DELAI_MUTATION = 60.0
MESSAGE_DELAI_MUTATION = ("Délai dépassé : l'action a peut-être été exécutée — vérifie avec "
                          "livraison_etat avant de réessayer.")


class DokployErreur(Exception):
    """Erreur honnête : `.message` ne contient jamais la clé ni un corps brut."""

    def __init__(self, message: str, statut: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.statut = statut


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
            raise DokployErreur("Dokploy injoignable (réseau ou service arrêté).") from None
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
