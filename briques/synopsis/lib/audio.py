"""Extraction audio via ffmpeg : N'IMPORTE QUEL conteneur vidéo/audio → WAV 16 kHz mono.

C'est ce qui permet à Synopsis d'accepter « n'importe quel type de vidéo » : on extrait
la piste audio AVANT de la confier à la brique transcription, ce qui garantit un format
propre quel que soit le fichier d'entrée (mp4, mov, mkv, webm, mp3, m4a…).
"""

import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger("synopsis.audio")


def _ffmpeg() -> str | None:
    for c in ("ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"):
        if shutil.which(c):
            return c
    return None


def extraire_audio(contenu: bytes, nom_fichier: str = "media") -> bytes:
    """Extrait la piste audio (WAV 16 kHz mono) d'une vidéo/audio quelconque.

    Lève ValueError si ffmpeg est absent, si le fichier est vide, ou si l'extraction échoue.
    """
    if not contenu:
        raise ValueError("Fichier vide.")
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        raise ValueError("ffmpeg introuvable dans le conteneur synopsis.")

    ext = os.path.splitext(nom_fichier or "")[1] or ".bin"
    with tempfile.TemporaryDirectory(prefix="synopsis_") as tmp:
        src = os.path.join(tmp, f"in{ext}")
        out = os.path.join(tmp, "out.wav")
        with open(src, "wb") as f:
            f.write(contenu)
        cmd = [ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", out]
        logger.info("Extraction audio de %s (%d octets)", nom_fichier, len(contenu))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(out):
            raise ValueError(f"Extraction audio échouée : {r.stderr[-300:]}")
        with open(out, "rb") as f:
            return f.read()
