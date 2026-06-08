import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.environ["GATEWAY_KEY"]  # requis — défini dans le .env racine (plus de défaut public)
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "ollama/llama3")

# Les modèles gratuits (OpenRouter) sont throttlés en amont : on encaisse les
# 429/503 avec un backoff exponentiel qui respecte l'en-tête Retry-After.
MAX_TENTATIVES = 6
DELAI_BASE = 5
DELAI_MAX = 60


def _attente(r: httpx.Response, delai_defaut: int) -> int:
    ra = r.headers.get("retry-after")
    if ra and ra.isdigit():
        return min(int(ra), DELAI_MAX)
    return delai_defaut

SYSTEM_PROMPT = (
    "Tu es un expert en design d'applications d'entreprise. Tu analyses un audit structuré "
    "et tu produis une réponse UNIQUEMENT en JSON valide, sans markdown, "
    "sans explication autour du JSON. Tu remplis tous les champs demandés — "
    "si une info est absente, tu proposes une valeur raisonnable basée sur le contexte."
)


async def appeler_llm(user: str) -> dict:
    """Appelle le Gateway et retourne le JSON parsé. Retente 1 fois si JSON invalide."""
    payload = {
        "model": GATEWAY_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    delai = DELAI_BASE
    derniere_erreur = "inconnue"
    async with httpx.AsyncClient(timeout=180) as client:
        for tentative in range(MAX_TENTATIVES):
            try:
                r = await client.post(
                    f"{GATEWAY_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
                    json=payload,
                )
                if r.status_code in (429, 503):
                    attente = _attente(r, delai)
                    derniere_erreur = f"HTTP {r.status_code}"
                    logger.warning(f"Gateway {r.status_code}, attente {attente}s (tentative {tentative + 1}/{MAX_TENTATIVES})")
                    await asyncio.sleep(attente)
                    delai = min(delai * 2, DELAI_MAX)
                    continue
                r.raise_for_status()
                contenu = r.json()["choices"][0]["message"]["content"]
                return _extraire_json(contenu)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                derniere_erreur = str(e) or type(e).__name__
                logger.warning(f"Gateway erreur réseau : {derniere_erreur} (tentative {tentative + 1}/{MAX_TENTATIVES})")
                await asyncio.sleep(delai)
                delai = min(delai * 2, DELAI_MAX)
    raise RuntimeError(f"Gateway indisponible après {MAX_TENTATIVES} tentatives : {derniere_erreur}")


def _extraire_json(texte: str) -> dict:
    debut = texte.find("{")
    fin = texte.rfind("}") + 1
    if debut == -1 or fin == 0:
        raise ValueError("Aucun JSON trouvé dans la réponse LLM")
    return json.loads(texte[debut:fin])
