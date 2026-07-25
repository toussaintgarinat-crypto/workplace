"""Client HTTP vers briques/transcription (port 5980) — transcription du message
vocal enregistré par le répondeur.

Repli honnête : indisponible/placeholder → None, jamais un faux texte."""
import os

import httpx


def _client() -> httpx.AsyncClient:
    base = os.getenv("TRANSCRIPTION_URL", "http://host.docker.internal:5980").rstrip("/")
    return httpx.AsyncClient(base_url=base, timeout=60)


async def transcrire(wav_bytes: bytes) -> str | None:
    """Audio WAV → texte via briques/transcription. None si indisponible/placeholder."""
    entetes = {}
    cle = os.getenv("TRANSCRIPTION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    try:
        async with _client() as client:
            r = await client.post("/transcrire",
                                  files={"fichier": ("message.wav", wav_bytes, "audio/wav")},
                                  headers=entetes)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("place_holder") or not data.get("texte"):
        return None
    return data["texte"]
