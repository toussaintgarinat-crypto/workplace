"""Client du Cœur vers la brique « calcul » (port 5990) — le « Muscle » déporté.

Décide si l'assistant met un modèle de calcul DISTANT en tête de sa cascade. On demande à
la brique calcul quel nœud est prêt (`GET /muscle`) :

  • un muscle déjà chaud → on renvoie son `modele_gateway` (le Cœur le met en tête) ;
  • aucun muscle chaud   → on déclenche un réveil EN FOND (fire-and-forget) pour que le
    PROCHAIN message tombe sur un muscle prêt, et la requête courante part en mode dégradé
    sur la cascade gratuite habituelle.

Tout est best-effort et NON bloquant : si calcul est absent/muet, on renvoie None et la
cascade existante prend le relais. Honnêteté : on ne met un modèle distant en tête que si
le muscle répond VRAIMENT (sonde live côté brique calcul).
"""
import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

CALCUL_URL = os.getenv("CALCUL_URL", "http://host.docker.internal:5990").rstrip("/")
CALCUL_KEY = os.getenv("CALCUL_KEY", "")          # si la brique calcul exige une clé API
_TIMEOUT = float(os.getenv("MUSCLE_TIMEOUT", "5"))


def _entetes() -> dict:
    return {"X-API-Key": CALCUL_KEY} if CALCUL_KEY else {}


async def tete_de_cascade(client: httpx.AsyncClient | None = None) -> str | None:
    """Modèle Gateway à mettre EN TÊTE si un muscle est DÉJÀ prêt, sinon None.

    Ne réveille rien (``reveiller=0``) : on ne bloque jamais la requête de l'utilisateur."""
    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.get(f"{CALCUL_URL}/muscle", params={"reveiller": "0"},
                             headers=_entetes())
        if r.status_code >= 400:
            return None
        data = r.json()
        if data.get("disponible") and data.get("modele_gateway"):
            return data["modele_gateway"]
        return None
    except (httpx.HTTPError, ValueError) as e:
        logger.debug("calcul injoignable (tete_de_cascade) : %s", e)
        return None
    finally:
        if propre:
            await client.aclose()


async def _reveiller() -> None:
    """Demande à calcul de réveiller un muscle (best-effort). Ne lève jamais."""
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            await c.get(f"{CALCUL_URL}/muscle", params={"reveiller": "1"}, headers=_entetes())
    except httpx.HTTPError as e:
        logger.debug("réveil muscle en fond échoué : %s", e)


def planifier_reveil() -> bool:
    """Lance le réveil d'un muscle en tâche de fond si une boucle asyncio tourne.

    Fire-and-forget (motif `shadow.planifier`) : n'attend rien, ne bloque pas la réponse
    servie. Renvoie True si planifié. La tâche ouvre son PROPRE client (elle survit à la
    requête courante)."""
    try:
        boucle = asyncio.get_running_loop()
    except RuntimeError:
        return False
    boucle.create_task(_reveiller())
    return True


async def etat(client: httpx.AsyncClient | None = None) -> dict:
    """État des nœuds pour le dashboard / ⚙ Cerveau. Best-effort, ne lève jamais.

    → {"brique_joignable": bool, "noeuds": [...]}."""
    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.get(f"{CALCUL_URL}/noeuds", headers=_entetes())
        if r.status_code >= 400:
            return {"brique_joignable": False, "noeuds": []}
        return {"brique_joignable": True, "noeuds": r.json().get("noeuds", [])}
    except (httpx.HTTPError, ValueError):
        return {"brique_joignable": False, "noeuds": []}
    finally:
        if propre:
            await client.aclose()
