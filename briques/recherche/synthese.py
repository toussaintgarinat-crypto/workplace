"""Synthèse LLM via le gateway Workplace (LiteLLM, port 4001).

Enchaîne : résultats de recherche → contexte → gateway /v1/chat/completions → texte.
Repli honnête si le gateway est indisponible : retourne (None, sources).
"""
import logging
import os

import aiohttp

from search_providers import SearchResult

logger = logging.getLogger(__name__)

_GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:4001")
_GATEWAY_KEY = os.getenv("LITELLM_MASTER_KEY", os.getenv("GATEWAY_API_KEY", ""))
_SYNTHESE_MODEL = os.getenv("SYNTHESE_MODEL", "deepseek/deepseek-v4-flash")
_TIMEOUT = 30


def _formater_contexte(resultats: list[SearchResult], max_items: int) -> tuple[str, list[dict]]:
    """Transforme les N premiers SearchResult en texte de contexte + liste de sources."""
    sources = []
    lignes = []
    for i, r in enumerate(resultats[:max_items]):
        extrait = (r.snippet or r.content or "").strip()
        provider = r.providers[0] if r.providers else r.source
        sources.append({"titre": r.title, "url": r.url, "provider": provider})
        lignes.append(f"[{i + 1}] {r.title}\n{r.url}\n{extrait}")
    return "\n\n".join(lignes), sources


async def synthetiser(
    requete: str,
    resultats: list[SearchResult],
    instructions: str = "",
    langue: str = "fr",
    max_items: int = 8,
) -> tuple[str | None, list[dict]]:
    """Appelle le gateway LLM et retourne (synthese_text, sources).

    En cas d'indisponibilité du gateway → (None, sources) pour repli honnête.
    """
    contexte, sources = _formater_contexte(resultats, max_items)
    if not contexte:
        return None, sources

    instruction_finale = (
        instructions.strip()
        or f"Synthétise les résultats en {langue} en 3 à 5 points clés. "
           "Cite les sources par leur numéro [1], [2], etc."
    )

    messages = [
        {
            "role": "system",
            "content": (
                f"Tu es un assistant de recherche. Langue de réponse : {langue}.\n"
                "Voici des résultats de recherche web numérotés. "
                "Utilise uniquement ces sources pour ta réponse."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Requête : {requete}\n\n"
                f"Sources :\n{contexte}\n\n"
                f"Instructions : {instruction_finale}"
            ),
        },
    ]

    headers = {"Content-Type": "application/json"}
    if _GATEWAY_KEY:
        headers["Authorization"] = f"Bearer {_GATEWAY_KEY}"

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_TIMEOUT)
        ) as session:
            async with session.post(
                f"{_GATEWAY_URL}/v1/chat/completions",
                json={
                    "model": _SYNTHESE_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 1024,
                },
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"[Synthèse] gateway {resp.status}: {body[:200]}")
                    return None, sources
                data = await resp.json()

        synthese = data["choices"][0]["message"]["content"]
        return synthese, sources

    except Exception as e:
        logger.warning(f"[Synthèse] gateway indisponible: {e}")
        return None, sources
