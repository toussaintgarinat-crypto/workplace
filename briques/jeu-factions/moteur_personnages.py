"""Client HTTP vers la brique `personnages` — le SEUL point d'appel au moteur holistique.

`jeu-factions` ne recalcule jamais une tradition/stat : tout passe par ces deux fonctions,
qui relaient tel quel la réponse de `personnages` (ou lèvent une HTTPException lisible)."""
import os

import httpx
from fastapi import HTTPException

PERSONNAGES_URL = os.getenv("PERSONNAGES_URL", "http://host.docker.internal:5900")
PERSONNAGES_KEY = os.getenv("PERSONNAGES_KEY", "")


def _entetes() -> dict:
    return {"X-API-Key": PERSONNAGES_KEY} if PERSONNAGES_KEY else {}


async def _appeler(chemin: str, corps: dict, client: httpx.AsyncClient | None = None) -> dict:
    async def _via(c: httpx.AsyncClient) -> dict:
        try:
            r = await c.post(f"{PERSONNAGES_URL}{chemin}", headers=_entetes(), json=corps)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"personnages injoignable ({PERSONNAGES_URL}) : {str(e)[:150]}")
        try:
            corps_reponse = r.json()
        except Exception:  # noqa: BLE001
            corps_reponse = {}
        if r.status_code >= 400:
            detail = corps_reponse.get("detail") if isinstance(corps_reponse, dict) else None
            raise HTTPException(r.status_code, detail or f"personnages a refusé la requête ({r.status_code}).")
        return corps_reponse

    if client is not None:
        return await _via(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _via(c)


async def portrait(fiche: dict, client: httpx.AsyncClient | None = None) -> dict:
    """Mode descendant : POST /holistique/portrait. `fiche` suit FicheHolistique de personnages."""
    return await _appeler("/holistique/portrait", fiche, client)


async def recherche_inverse(description: str, combien: int = 3,
                            client: httpx.AsyncClient | None = None) -> dict:
    """Mode montant : POST /holistique/recherche-inverse."""
    return await _appeler("/holistique/recherche-inverse",
                          {"description": description, "combien": combien}, client)
