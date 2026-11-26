"""Client HTTP de l'exécuteur de restauration (VM 100). Messages d'erreur honnêtes, jamais la clé
ni le corps brut de la réponse."""
from typing import Optional

import httpx


class ExecuteurErreur(Exception):
    def __init__(self, message: str, statut: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.statut = statut


class Executeur:
    def __init__(self, base_url: str, cle: str,
                 transport: Optional[httpx.AsyncBaseTransport] = None, delai: float = 280.0):
        self._base, self._cle, self._transport, self._delai = base_url.rstrip("/"), cle, transport, delai

    async def verifier(self, service: str, utilisateur: str, base: str, objet: str) -> dict:
        try:
            async with httpx.AsyncClient(base_url=self._base, transport=self._transport,
                                         timeout=self._delai) as c:
                r = await c.post("/verifier", headers={"X-API-Key": self._cle},
                                 json={"service": service, "utilisateur": utilisateur,
                                       "base": base, "objet": objet})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ExecuteurErreur("Exécuteur de restauration injoignable.") from None
        except httpx.HTTPError:
            raise ExecuteurErreur("Échec de la communication avec l'exécuteur "
                                  "(délai dépassé ?).") from None
        if r.status_code == 401:
            raise ExecuteurErreur("L'exécuteur a refusé la clé.", 401)
        if r.status_code == 409:
            raise ExecuteurErreur("Une vérification est déjà en cours sur l'exécuteur.", 409)
        if r.status_code != 200:
            raise ExecuteurErreur(f"L'exécuteur a répondu {r.status_code}.", r.status_code)
        try:
            d = r.json()
        except ValueError:
            raise ExecuteurErreur("Réponse illisible de l'exécuteur.") from None
        if not isinstance(d, dict):
            raise ExecuteurErreur("Réponse inattendue de l'exécuteur.")
        return d
