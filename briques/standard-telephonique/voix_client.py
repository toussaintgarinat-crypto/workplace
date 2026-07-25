"""Client HTTP vers briques/voix (port 5985) — synthèse du menu/répondeur.

Repli honnête : si la brique est absente, injoignable, ou répond en mode placeholder
(aucun moteur TTS configuré), on retourne None — jamais un faux audio."""
import os

import httpx


def _client() -> httpx.AsyncClient:
    base = os.getenv("VOIX_URL", "http://host.docker.internal:5985").rstrip("/")
    return httpx.AsyncClient(base_url=base, timeout=20)


async def synthetiser(texte: str) -> bytes | None:
    """Texte → octets WAV via briques/voix. None si indisponible ou placeholder."""
    entetes = {}
    cle = os.getenv("VOIX_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    try:
        async with _client() as client:
            r = await client.post("/synthetiser", json={"texte": texte, "format": "wav"},
                                  headers=entetes)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    if r.headers.get("content-type", "").startswith("application/json"):
        return None  # placeholder honnête renvoyé en JSON, pas d'audio
    return r.content
