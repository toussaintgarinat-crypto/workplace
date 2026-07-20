"""Habillage vidéo DÉTERMINISTE (sans IA, sans coût) — cartons de titre + sous-titres incrustés.

Complète la brique video (génération IA hébergée, cf. fournisseurs.py/moteur.py) par un
post-traitement 100% local : ffmpeg pur, aucune clé, aucun fournisseur. Deux usages nés du
Studio (S46 découpage en épisodes) :
  • une carte de titre/chapitre (texte sur fond uni, quelques secondes) ;
  • des sous-titres BRÛLÉS dans une vidéo existante, à partir d'une liste de segments minutés.

Comme les autres briques, honnêteté stricte : si `ffmpeg` est absent, on lève une erreur
claire plutôt que de rendre un fichier vide ou corrompu — jamais de faux résultat.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def disponible() -> bool:
    """Vrai si le binaire ffmpeg est présent (aucun réseau, aucune clé requise)."""
    return shutil.which(_bin()) is not None


def _echapper_drawtext(texte: str) -> str:
    """Échappe un texte pour le filtre ffmpeg `drawtext` (":", "'", "%", "\\")."""
    t = (texte or "").replace("\\", "\\\\").replace(":", "\\:").replace("%", "\\%")
    return t.replace("'", "’")   # apostrophe typographique : évite de fermer le filtre


def _temps_srt(secondes: float) -> str:
    """Secondes → horodatage SRT `HH:MM:SS,mmm` (pure, testable sans ffmpeg)."""
    ms = round(max(0.0, float(secondes)) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def construire_srt(segments: list[dict]) -> str:
    """Segments [{debut, fin, texte}] (secondes) → contenu .srt (pure, testable).

    Ignore les segments sans texte ou dont la fin ne suit pas le début — jamais d'exception
    sur une entrée mal formée, on garde juste les segments exploitables."""
    blocs = []
    for i, seg in enumerate(segments or [], start=1):
        if not isinstance(seg, dict):
            continue
        texte = (seg.get("texte") or "").strip()
        try:
            debut, fin = float(seg.get("debut") or 0), float(seg.get("fin") or 0)
        except (TypeError, ValueError):
            continue
        if not texte or fin <= debut:
            continue
        blocs.append(f"{len(blocs) + 1}\n{_temps_srt(debut)} --> {_temps_srt(fin)}\n{texte}\n")
    return "\n".join(blocs)


def _executer(cmd: list[str], timeout: int) -> bytes:
    if not disponible():
        raise RuntimeError("ffmpeg introuvable (FFMPEG_BIN) : habillage vidéo indisponible.")
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("ffmpeg a échoué : " + p.stderr.decode("utf-8", "ignore")[:200])
    return p.stdout


def carte_titre(texte: str, sous_titre: str = "", duree: float = 3.0,
                largeur: int = 1920, hauteur: int = 1080,
                fond: str = "0x120f18", couleur: str = "white") -> bytes:
    """Carte de titre/chapitre : fond uni + texte centré, `duree` secondes, rendue en MP4."""
    if not (texte or "").strip():
        raise ValueError("Le texte de la carte est vide.")
    decalage = "-40" if sous_titre else ""
    filtres = [f"drawtext=text='{_echapper_drawtext(texte)}':fontcolor={couleur}:fontsize=64:"
               f"x=(w-text_w)/2:y=(h-text_h)/2{decalage}"]
    if sous_titre:
        filtres.append(f"drawtext=text='{_echapper_drawtext(sous_titre)}':fontcolor={couleur}:"
                       "fontsize=32:x=(w-text_w)/2:y=(h-text_h)/2+40")
    cmd = [_bin(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", f"color=c={fond}:s={largeur}x{hauteur}:d={duree}",
           "-vf", ",".join(filtres), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-t", str(duree), "-f", "mp4", "-movflags", "frag_keyframe+empty_moov", "pipe:1"]
    return _executer(cmd, timeout=int(os.getenv("FFMPEG_TIMEOUT_S", "60")))


def sous_titrer(video: bytes, segments: list[dict]) -> bytes:
    """Brûle des sous-titres (segments minutés) dans une vidéo existante. Rend le MP4 résultant."""
    srt = construire_srt(segments)
    if not srt.strip():
        raise ValueError("Aucun segment de sous-titre exploitable.")
    with tempfile.TemporaryDirectory() as d:
        v_in = Path(d) / "in.mp4"
        v_in.write_bytes(video)
        srt_path = Path(d) / "sub.srt"
        srt_path.write_text(srt, encoding="utf-8")
        cmd = [_bin(), "-hide_banner", "-loglevel", "error", "-i", str(v_in),
               "-vf", f"subtitles={srt_path}:force_style='FontSize=22'",
               "-c:v", "libx264", "-c:a", "copy", "-f", "mp4",
               "-movflags", "frag_keyframe+empty_moov", "pipe:1"]
        return _executer(cmd, timeout=int(os.getenv("FFMPEG_TIMEOUT_S", "120")))
