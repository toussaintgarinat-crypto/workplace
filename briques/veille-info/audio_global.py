"""Audio global (S199) : concatène plusieurs digests DÉJÀ audio-générés (dans un ordre
choisi), avec un interlude TTS annonçant chaque thématique. Best-effort de bout en bout au
sens strict : toute étape manquante (digest sans audio, téléchargement en échec, ffmpeg en
échec) lève une erreur explicite avant de produire un résultat partiel — pas de "presque
bon" silencieux, contrairement à l'audio par digest qui, lui, reste best-effort (le digest
texte existe déjà sans lui)."""
from __future__ import annotations

import os
import secrets
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import stockage

VOIX_URL = os.getenv("VOIX_URL", "http://host.docker.internal:5985")
_AUDIO_GLOBAL_DIR = Path(os.getenv("VEILLE_INFO_AUDIO_GLOBAL_DIR", "/data/audio-global"))
_EXPIRATION_JOURS = 7


class AudioGlobalError(Exception):
    """Erreur explicite (digest sans audio, téléchargement/ffmpeg en échec)."""


def _telecharger(url: str) -> bytes:
    """Récupère les octets d'un fichier audio produit par une autre brique — pas de volume
    Docker partagé entre voix et veille-info (motif déjà utilisé par
    briques/transcription/main.py::_telecharger)."""
    try:
        r = httpx.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise AudioGlobalError(f"Téléchargement audio impossible ({url}) : {e}") from e


def _synthetiser_interlude(texte: str) -> bytes:
    """Synthétise un court interlude TTS via briques/voix (même endpoint /rendre que
    digest.py::_generer_audio), renvoie directement les octets audio."""
    try:
        r = httpx.post(f"{VOIX_URL}/rendre", timeout=60,
                       json={"segments": [{"voix": None, "texte": texte}]})
        r.raise_for_status()
        url = r.json().get("url")
    except httpx.HTTPError as e:
        raise AudioGlobalError(f"Synthèse de l'interlude impossible : {e}") from e
    if not url:
        raise AudioGlobalError("Synthèse de l'interlude : pas d'URL renvoyée par la voix.")
    return _telecharger(url)


def generer(user_id: str, ordre_digest_ids: list[int]) -> dict:
    if not ordre_digest_ids:
        raise AudioGlobalError("Aucun digest sélectionné.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fichiers = []
        for i, digest_id in enumerate(ordre_digest_ids):
            d = stockage.digest_get(user_id, digest_id)
            if d is None:
                raise AudioGlobalError(f"Digest {digest_id} introuvable.")
            if not d.get("audio_url"):
                raise AudioGlobalError(
                    f"Le digest « {d.get('thematique') or 'Général'} » du {d['date']} n'a pas "
                    "encore d'audio — génère-le d'abord avant de créer l'audio global.")

            nom_thematique = d.get("thematique") or "Général"
            interlude = _synthetiser_interlude(f"Voici les nouvelles pour la veille {nom_thematique}.")
            p_interlude = tmp_path / f"seg_{i:04d}a_interlude.mp3"
            p_interlude.write_bytes(interlude)
            fichiers.append(str(p_interlude))

            audio = _telecharger(d["audio_url"])
            p_digest = tmp_path / f"seg_{i:04d}b_digest.mp3"
            p_digest.write_bytes(audio)
            fichiers.append(str(p_digest))

        liste = tmp_path / "liste.txt"
        liste.write_text("\n".join(f"file '{f}'" for f in fichiers))
        _AUDIO_GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
        jeton = secrets.token_urlsafe(24)
        sortie = _AUDIO_GLOBAL_DIR / f"{jeton}.mp3"
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(liste), "-c:a", "libmp3lame", "-q:a", "4", str(sortie)],
                capture_output=True, timeout=300)
        except FileNotFoundError as e:
            raise AudioGlobalError("ffmpeg introuvable dans l'image.") from e
        if proc.returncode != 0:
            raise AudioGlobalError(f"ffmpeg : {proc.stderr.decode('utf-8', 'ignore')[:300]}")

    duree = None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(sortie)],
            capture_output=True, text=True, timeout=10)
        duree = float(r.stdout.strip())
    except Exception:  # noqa: BLE001 — durée optionnelle, jamais bloquant
        pass

    expire_le = (datetime.now(timezone.utc) + timedelta(days=_EXPIRATION_JOURS)).isoformat()
    return stockage.inserer_audio_global(user_id, jeton, ordre_digest_ids, str(sortie), duree, expire_le)
