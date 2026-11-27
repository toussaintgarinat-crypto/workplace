"""Registre des apps à contrat de données + client de leurs routes /support/* (S248 3a).

Fichier JSON tenu par l'exploitant (comme `inventaire.json`) : une app absente ou mal formée
n'est PAS jouée « au hasard », on refuse. Le bloc `contrat_donnees` du manifeste y est copié et
VALIDÉ ici (chemins sûrs, version numérique) : c'est le point où le bloc est exploité."""
import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

import contrat_donnees as C

_RE_CLE_ENV = re.compile(r"[A-Z][A-Z0-9_]{0,60}_SUPPORT_KEY")
_RE_RAISON = re.compile(r"[a-z_]{1,30}")
_CHAMPS = {"url", "cle_env", "bloc"}
CHEMIN_VERIFIER = "/support/verifier"   # fixe : hors bloc (le bloc n'a que 3 actions)
DELAI_S = 120.0


class ContratErreur(Exception):
    def __init__(self, message: str, statut: Optional[int] = None, raison: str = ""):
        super().__init__(message)
        self.message, self.statut, self.raison = message, statut, raison


def _chemin() -> Path:
    explicite = os.getenv("LIVRAISON_CONTRATS")
    return Path(explicite) if explicite else Path(os.getenv("LIVRAISON_DATA", "/data")) / "contrats.json"


def _url_sure(url) -> bool:
    if not isinstance(url, str):
        return False
    p = urlsplit(url)
    return (p.scheme in ("http", "https") and bool(p.hostname) and p.path in ("", "/")
            and not (p.username or p.password or p.query or p.fragment))


def _valide(e) -> bool:
    return (isinstance(e, dict) and set(e) == _CHAMPS and _url_sure(e["url"])
            and isinstance(e["cle_env"], str) and _RE_CLE_ENV.fullmatch(e["cle_env"]) is not None
            and not C.valider_bloc_contrat(e["bloc"]))


def lire(nom_app: str) -> Optional[dict]:
    try:
        d = json.loads(_chemin().read_text())
    except (OSError, ValueError):
        return None
    e = d.get((nom_app or "").strip().lower()) if isinstance(d, dict) else None
    return json.loads(json.dumps(e)) if _valide(e) else None


def ouvrir(nom_app: str, transport: Optional[httpx.AsyncBaseTransport] = None) -> "AppContrat":
    e = lire(nom_app)
    if e is None:
        raise ContratErreur("aucun contrat de données valide pour cette application", 404, "inconnu")
    return AppContrat(nom_app.strip().lower(), e, transport)


class AppContrat:
    def __init__(self, nom: str, entree: dict, transport: Optional[httpx.AsyncBaseTransport] = None,
                 delai: float = DELAI_S):
        self.nom, self._e, self._transport, self._delai = nom, entree, transport, delai
        self._cle = os.getenv(entree["cle_env"], "").strip()
        if not self._cle:
            raise ContratErreur("clé de support de l'application non configurée", 503, "non_configure")

    @property
    def version_schema(self) -> str:
        return self._e["bloc"]["version_schema"]

    async def _appel(self, methode: str, chemin: str, **kw) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self._e["url"], transport=self._transport,
                                         timeout=self._delai) as c:
                r = await c.request(methode, chemin, headers={"X-Support-Key": self._cle}, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ContratErreur("application injoignable", None, "injoignable") from None
        except httpx.HTTPError:
            raise ContratErreur("échec de la communication avec l'application", None,
                                "delai") from None
        if r.status_code == 200:
            return r
        raison = ""
        if r.status_code in (409, 422):
            try:
                d = r.json().get("detail")
            except (ValueError, AttributeError):
                d = None
            raison = d if isinstance(d, str) and _RE_RAISON.fullmatch(d) else "refus"
        raison = raison or {401: "cle_refusee", 503: "desactive", 413: "trop_gros"}.get(
            r.status_code, "erreur")
        raise ContratErreur(f"l'application a répondu {r.status_code} ({raison})",
                            r.status_code, raison)

    def _action(self, nom: str) -> str:
        return self._e["bloc"][nom]["chemin"]

    async def exporter(self, utilisateur: str) -> tuple:
        r = await self._appel("POST", self._action("exporter"), json={"utilisateur": utilisateur})
        try:
            emp, comptages = r.headers["X-Empreinte"], json.loads(r.headers["X-Comptages"])
        except (KeyError, ValueError):
            raise ContratErreur("export sans métadonnées exploitables", 200, "meta") from None
        if not (isinstance(emp, str) and emp and isinstance(comptages, dict)):
            raise ContratErreur("export sans métadonnées exploitables", 200, "meta")
        return r.content, {"empreinte": emp, "comptages": comptages}

    async def verifier(self, utilisateur: str, paquet: bytes) -> dict:
        r = await self._appel("POST", CHEMIN_VERIFIER, params={"utilisateur": utilisateur},
                              content=paquet)
        return r.json()

    async def reinitialiser(self, utilisateur: str, empreinte: str) -> dict:
        r = await self._appel("POST", self._action("reinitialiser"),
                              json={"utilisateur": utilisateur, "empreinte": empreinte})
        return r.json()

    async def importer(self, utilisateur: str, paquet: bytes) -> dict:
        r = await self._appel("POST", self._action("importer"),
                              params={"utilisateur": utilisateur}, content=paquet)
        return r.json()
