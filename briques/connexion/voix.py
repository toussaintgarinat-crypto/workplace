"""Client des briques VOIX — audio↔texte pour la conversation vocale (speech-to-speech).

Symétrique de `client_assistant.py`. Deux sens :
  • `transcrire(...)` → brique transcription (Whisper local souverain, `POST :5980/transcrire`,
    multipart) : un message vocal entrant devient du texte AVANT d'être relayé au Cœur ;
  • `synthetiser(...)` → brique voix (Piper local souverain, `POST :5985/synthetiser`) : la
    réponse texte du Cœur redevient de l'audio pour répondre EN vocal.

Repli HONNÊTE des deux côtés : si un moteur est injoignable ou rend un `place_holder`
(aucun backend actif), on remonte l'absence — le pont NE relaie PAS une fausse transcription
et N'envoie PAS de fausse voix.
"""
import os
from typing import Optional

import httpx


def url_transcription() -> str:
    base = os.getenv("TRANSCRIPTION_URL", "http://host.docker.internal:5980").rstrip("/")
    return f"{base}/transcrire"


def url_synthese() -> str:
    base = os.getenv("VOIX_URL", "http://host.docker.internal:5985").rstrip("/")
    return f"{base}/synthetiser"


def _entetes(env_cle: str) -> dict:
    """Clé API optionnelle pour une brique voix (multi-tenant local). Repli sur API_KEYS."""
    cle = os.getenv(env_cle) or os.getenv("API_KEYS", "").split(",")[0].strip()
    return {"X-API-Key": cle} if cle else {}


def _format_depuis_ctype(ctype: str) -> str:
    return {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav",
            "audio/aac": "aac", "audio/flac": "flac"}.get(ctype.split(";")[0].strip(), "ogg")


async def transcrire(audio: bytes, nom: str = "voix.ogg",
                     langue: Optional[str] = None, *, timeout: float = 120.0) -> dict:
    """Envoie les octets audio au moteur souverain. Renvoie le dict de la brique
    (`{texte, place_holder, backend, ...}`). Lève en cas d'échec réseau — l'appelant gère
    le repli honnête."""
    fichiers = {"fichier": (nom, audio, "application/octet-stream")}
    donnees = {"langue": langue} if langue else {}
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url_transcription(), files=fichiers, data=donnees,
                         headers=_entetes("TRANSCRIPTION_KEY"))
        r.raise_for_status()
        return r.json()


async def synthetiser(texte: str, voix: Optional[str] = None, langue: Optional[str] = None,
                      *, timeout: float = 120.0) -> Optional[dict]:
    """Vocalise `texte` via la brique voix. Renvoie `{audio, format, backend}` si un moteur a
    répondu (corps binaire `audio/*`), ou `None` si la brique a rendu un placeholder JSON
    (aucun moteur TTS configuré). Lève en cas d'échec réseau — l'appelant gère le repli."""
    corps = {"texte": texte}
    if voix:
        corps["voix"] = voix
    if langue:
        corps["langue"] = langue
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url_synthese(), json=corps, headers=_entetes("VOIX_KEY"))
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if not ctype.startswith("audio/"):
            return None                          # placeholder honnête : pas de voix dispo
        return {"audio": r.content, "backend": r.headers.get("X-Backend"),
                "format": r.headers.get("X-Format") or _format_depuis_ctype(ctype)}
