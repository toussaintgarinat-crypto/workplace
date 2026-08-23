"""Client HTTP vers la brique `personnages` — SEUL point de contact avec le moteur
astro. world-engine n'importe jamais de code de `personnages` : tout calcul de
thème passe par ces 2 appels."""
import os

import httpx

PERSONNAGES_URL = os.getenv("PERSONNAGES_URL", "http://host.docker.internal:5900")
_PERSONNAGES_CLE = os.getenv("PERSONNAGES_KEY")
_ENTETES = {"X-API-Key": _PERSONNAGES_CLE} if _PERSONNAGES_CLE else {}


class PersonnagesIndisponible(Exception):
    """La brique `personnages` n'a pas répondu (réseau/DNS/timeout) — jamais de
    donnée inventée pour compenser : l'appelant doit répondre 502."""


async def portrait(fiche: dict) -> httpx.Response:
    """POST /holistique/portrait — traditions + portrait + theme_complet réels."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            return await client.post(f"{PERSONNAGES_URL}/holistique/portrait",
                                      json=fiche, headers=_ENTETES)
        except httpx.HTTPError as e:
            raise PersonnagesIndisponible(str(e)) from e


async def recherche_inverse(description: str) -> httpx.Response:
    """POST /holistique/recherche-inverse — description → signes/nombres plausibles.

    `combien=1` : world-engine n'a besoin que du signe le mieux classé."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            return await client.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse",
                                      json={"description": description, "combien": 1},
                                      headers=_ENTETES)
        except httpx.HTTPError as e:
            raise PersonnagesIndisponible(str(e)) from e
