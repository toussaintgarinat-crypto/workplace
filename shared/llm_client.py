"""Client Gateway LLM unifié (S118) — pilier de `shared/`.

Auparavant dupliqué à l'identique dans `briques/audit/gateway.py` et
`briques/generateur/gateway.py` (~90 % communs) : appel résilient au Gateway LiteLLM
(backoff exponentiel sur 429/503 respectant Retry-After + retries réseau) puis
extraction du JSON renvoyé par le modèle. Les briques ne gardent que leur prompt
système et leur température ; toute la plomberie vit ici, en source unique.

Lecture des réglages (URL/modèle/clé) au moment de l'appel (et non à l'import) : les
tests tournent sans `GATEWAY_KEY`, et chaque brique garde son `GATEWAY_MODEL` d'env.
"""
import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Modèles gratuits (OpenRouter) throttlés en amont → on encaisse 429/503 avec un
# backoff exponentiel qui respecte l'en-tête Retry-After.
MAX_TENTATIVES = 6
DELAI_BASE = 5
DELAI_MAX = 60


def url_gateway() -> str:
    return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")


def modele_defaut() -> str:
    return os.getenv("GATEWAY_MODEL", "ollama/llama3")


def _attente(r: httpx.Response, delai_defaut: int) -> int:
    ra = r.headers.get("retry-after")
    if ra and ra.isdigit():
        return min(int(ra), DELAI_MAX)
    return delai_defaut


def extraire_json(texte: str) -> dict:
    """Extrait le premier objet JSON d'une réponse LLM (tolère le markdown autour)."""
    debut = texte.find("{")
    fin = texte.rfind("}") + 1
    if debut == -1 or fin == 0:
        raise ValueError("Aucun JSON trouvé dans la réponse LLM")
    return json.loads(texte[debut:fin])


async def appeler_json(user: str, *, system_prompt: str, temperature: float = 0.1,
                       model: str | None = None, timeout: float = 180.0) -> dict:
    """Appelle le Gateway (chat/completions) et renvoie le JSON parsé de la réponse.

    Résilient : backoff exponentiel sur 429/503 (respecte Retry-After) et sur erreur
    réseau, jusqu'à MAX_TENTATIVES. Lève RuntimeError si le Gateway reste injoignable,
    ValueError si la réponse ne contient aucun JSON."""
    payload = {
        "model": model or modele_defaut(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    entetes = {"Authorization": f"Bearer {os.environ['GATEWAY_KEY']}"}
    delai = DELAI_BASE
    derniere_erreur = "inconnue"
    async with httpx.AsyncClient(timeout=timeout) as client:
        for tentative in range(MAX_TENTATIVES):
            try:
                r = await client.post(f"{url_gateway()}/v1/chat/completions",
                                      headers=entetes, json=payload)
                if r.status_code in (429, 503):
                    attente = _attente(r, delai)
                    derniere_erreur = f"HTTP {r.status_code}"
                    logger.warning("Gateway %s, attente %ss (tentative %s/%s)",
                                   r.status_code, attente, tentative + 1, MAX_TENTATIVES)
                    await asyncio.sleep(attente)
                    delai = min(delai * 2, DELAI_MAX)
                    continue
                r.raise_for_status()
                contenu = r.json()["choices"][0]["message"]["content"]
                return extraire_json(contenu)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                derniere_erreur = str(e) or type(e).__name__
                logger.warning("Gateway erreur réseau : %s (tentative %s/%s)",
                               derniere_erreur, tentative + 1, MAX_TENTATIVES)
                await asyncio.sleep(delai)
                delai = min(delai * 2, DELAI_MAX)
    raise RuntimeError(
        f"Gateway indisponible après {MAX_TENTATIVES} tentatives : {derniere_erreur}")
