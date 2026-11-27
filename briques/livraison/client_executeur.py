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


# Au-dessus des 900 s de pg_restore côté exécuteur.
DELAI_CLONER = 960.0
DELAI_OBJET = 300.0


class Executeur:
    def __init__(self, base_url: str, cle: str,
                 transport: Optional[httpx.AsyncBaseTransport] = None, delai: float = 280.0):
        self._base, self._cle, self._transport, self._delai = base_url.rstrip("/"), cle, transport, delai

    async def _post(self, chemin: str, corps: dict, delai: float) -> dict:
        try:
            async with httpx.AsyncClient(base_url=self._base, transport=self._transport,
                                         timeout=delai) as c:
                r = await c.post(chemin, headers={"X-API-Key": self._cle}, json=corps)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ExecuteurErreur("Exécuteur de restauration injoignable.") from None
        except httpx.HTTPError:
            raise ExecuteurErreur("Échec de la communication avec l'exécuteur "
                                  "(délai dépassé ?).") from None
        if r.status_code == 401:
            raise ExecuteurErreur("L'exécuteur a refusé la clé.", 401)
        if r.status_code == 409:
            raise ExecuteurErreur("Une opération est déjà en cours sur l'exécuteur.", 409)
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

    async def verifier(self, service: str, utilisateur: str, base: str, objet: str) -> dict:
        return await self._post("/verifier", {"service": service, "utilisateur": utilisateur,
                                              "base": base, "objet": objet}, self._delai)

    async def cloner(self, service: str, utilisateur: str, base: str, objet: str,
                     nouvelle_base: str) -> dict:
        """Restaure une sauvegarde dans une base neuve (pg_restore plafonné à 900 s côté exécuteur)."""
        return await self._post("/cloner", {"service": service, "utilisateur": utilisateur,
                                            "base": base, "objet": objet,
                                            "nouvelle_base": nouvelle_base}, DELAI_CLONER)

    async def comptages(self, service: str, utilisateur: str, base: str) -> dict:
        return await self._post("/comptages", {"service": service, "utilisateur": utilisateur,
                                               "base": base}, self._delai)

    async def supprimer_base(self, service: str, utilisateur: str, base: str) -> dict:
        return await self._post("/supprimer-base", {"service": service, "utilisateur": utilisateur,
                                                    "base": base}, self._delai)

    async def _objet(self, methode: str, cle: str, contenu: Optional[bytes] = None) -> bytes:
        try:
            async with httpx.AsyncClient(base_url=self._base, transport=self._transport,
                                         timeout=DELAI_OBJET) as c:
                r = await c.request(methode, "/objets/" + cle, headers={"X-API-Key": self._cle},
                                    content=contenu)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ExecuteurErreur("Exécuteur de restauration injoignable.") from None
        except httpx.HTTPError:
            raise ExecuteurErreur("Échec de la communication avec l'exécuteur "
                                  "(délai dépassé ?).") from None
        if r.status_code == 401:
            raise ExecuteurErreur("L'exécuteur a refusé la clé.", 401)
        if r.status_code == 413:
            raise ExecuteurErreur("Objet trop gros pour l'exécuteur.", 413)
        if r.status_code != 200:
            raise ExecuteurErreur(f"L'exécuteur a répondu {r.status_code}.", r.status_code)
        return r.content

    async def deposer(self, cle: str, octets: bytes) -> None:
        await self._objet("PUT", cle, octets)

    async def lire(self, cle: str) -> bytes:
        return await self._objet("GET", cle)

    async def supprimer(self, cle: str) -> None:
        await self._objet("DELETE", cle)
