"""Client HTTP de l'exécuteur de restauration (VM 100). Messages d'erreur honnêtes, jamais la clé
ni le corps brut de la réponse."""
import re
from typing import Optional

import httpx


class ExecuteurErreur(Exception):
    def __init__(self, message: str, statut: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.statut = statut


_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _erreur_fixe(r: httpx.Response) -> str:
    """Seule la chaîne fixe `erreur` de l'exécuteur, nettoyée et bornée ; rien d'autre."""
    try:
        d = r.json()
    except ValueError:
        return ""
    e = d.get("erreur") if isinstance(d, dict) else None
    if not isinstance(e, str):
        return ""
    return _CTRL.sub("", e)[:120].strip()


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
            detail = _erreur_fixe(r) if r.status_code in (400, 404, 500, 502) else ""
            suite = f" : {detail}" if detail else "."
            raise ExecuteurErreur(f"L'exécuteur a répondu {r.status_code}{suite}", r.status_code)
        try:
            d = r.json()
        except ValueError:
            raise ExecuteurErreur("Réponse illisible de l'exécuteur.") from None
        if not isinstance(d, dict):
            raise ExecuteurErreur("Réponse inattendue de l'exécuteur.")
        return d
