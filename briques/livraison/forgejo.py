"""Client HTTP Forgejo en lecture seule (auth `Authorization: token …`). Liste blanche en sortie."""
from typing import Optional

import httpx


class ForgejoErreur(Exception):
    """Erreur honnête : `.message` ne contient jamais le jeton ni un corps brut."""

    def __init__(self, message: str, statut: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.statut = statut


class Forgejo:
    def __init__(self, base_url: str, jeton: str,
                 transport: Optional[httpx.AsyncBaseTransport] = None, delai: float = 20.0):
        self._base = base_url.rstrip("/")
        self._jeton = jeton
        self._transport = transport
        self._delai = delai

    async def _get(self, client: httpx.AsyncClient, chemin: str, params: Optional[dict] = None,
                   tolere_404: bool = False):
        try:
            r = await client.get(chemin, params=params,
                                 headers={"Authorization": f"token {self._jeton}"})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ForgejoErreur("Forgejo injoignable (réseau ou service arrêté).") from None
        except httpx.TimeoutException:
            raise ForgejoErreur("Délai dépassé en attendant Forgejo.") from None
        except httpx.HTTPError:
            raise ForgejoErreur("Échec de la communication avec Forgejo.") from None
        if r.status_code == 401:
            raise ForgejoErreur("Jeton Forgejo refusé.", 401)
        if r.status_code == 404:
            if tolere_404:
                return None
            raise ForgejoErreur("Ressource Forgejo introuvable.", 404)
        if r.status_code >= 400:
            raise ForgejoErreur(f"Forgejo a répondu {r.status_code}.", r.status_code)
        try:
            return r.json()
        except ValueError:
            raise ForgejoErreur("Réponse de Forgejo illisible (JSON invalide).",
                                r.status_code) from None

    async def depots(self) -> list[dict]:
        async with httpx.AsyncClient(base_url=self._base, transport=self._transport,
                                     timeout=self._delai) as c:
            liste = await self._get(c, "/api/v1/user/repos", params={"limit": "50"})
            if not isinstance(liste, list):
                raise ForgejoErreur("Réponse de Forgejo inattendue.")
            sortie = []
            for d in liste:
                nom = d.get("full_name") or d.get("name")
                branche = d.get("default_branch") or None
                commit = None
                if nom and branche and not d.get("empty"):
                    b = await self._get(c, f"/api/v1/repos/{nom}/branches/{branche}",
                                        tolere_404=True)
                    cid = ((b or {}).get("commit") or {}).get("id") if isinstance(b, dict) else None
                    commit = cid[:7] if isinstance(cid, str) and cid else None
                sortie.append({"nom": nom, "branche": branche, "miroir": bool(d.get("mirror")),
                               "dernier_commit": commit})
            return sortie
