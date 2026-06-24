"""Client de la brique TRANSCRIPTION (Whisper souverain, 5980).

Synopsis délègue ici la transcription des vidéos NON-YouTube : on envoie le média
(audio extrait d'un fichier uploadé, ou URL directe) à la brique transcription et on
récupère le texte + d'éventuels segments horodatés.

Repli HONNÊTE : si la brique répond `place_holder` (aucun moteur configuré) ou est
injoignable, on lève une erreur explicite — on n'invente JAMAIS de transcript.
"""

import logging
import os

import httpx

logger = logging.getLogger("synopsis.transcribe")

TRANSCRIPTION_URL = os.getenv("TRANSCRIPTION_URL", "http://host.docker.internal:5980").rstrip("/")
_API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
API_KEY = os.getenv("TRANSCRIPTION_API_KEY", "") or (_API_KEYS[0] if _API_KEYS else "")
TIMEOUT = float(os.getenv("TRANSCRIPTION_TIMEOUT", "1800"))


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _normaliser(data: dict, titre: str) -> dict:
    """Transforme la réponse de la brique transcription en transcript au format chunker
    (`[{start, text, duration}]`) — ou lève une erreur honnête."""
    if data.get("place_holder"):
        note = data.get("note") or ""
        raise ValueError(
            "La brique transcription n'a aucun moteur configuré (active le Whisper local "
            f"ou pose une clé hébergée). {note}".strip()
        )
    texte = (data.get("texte") or "").strip()
    if not texte:
        raise ValueError("La brique transcription a renvoyé un texte vide.")

    transcript = []
    for s in data.get("segments") or []:
        if not isinstance(s, dict):
            continue
        txt = (s.get("text") or s.get("texte") or "").strip()
        if not txt:
            continue
        transcript.append({
            "start": float(s.get("start", s.get("debut", 0)) or 0),
            "text": txt,
            "duration": float(s.get("duration", s.get("duree", 0)) or 0),
        })
    if not transcript:  # pas de segments horodatés → un seul bloc
        transcript = [{"start": 0.0, "text": texte, "duration": 0.0}]

    return {"transcript": transcript, "langue": data.get("langue") or "unknown", "titre": titre}


def transcrire_fichier(contenu: bytes, nom_fichier: str, langue: str | None = None) -> dict:
    """Audio (octets) → transcript via POST /transcrire (multipart)."""
    files = {"fichier": (nom_fichier or "audio.wav", contenu, "application/octet-stream")}
    data = {"langue": langue} if langue else {}
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{TRANSCRIPTION_URL}/transcrire", files=files, data=data, headers=_headers())
        r.raise_for_status()
        return _normaliser(r.json(), nom_fichier or "Vidéo")


def transcrire_url(url: str, langue: str | None = None) -> dict:
    """URL d'un média direct → transcript via POST /transcrire-url."""
    body = {"url": url}
    if langue:
        body["langue"] = langue
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{TRANSCRIPTION_URL}/transcrire-url", json=body, headers=_headers())
        r.raise_for_status()
        titre = url.rsplit("/", 1)[-1].split("?")[0] or "Vidéo"
        return _normaliser(r.json(), titre)
