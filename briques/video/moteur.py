"""Moteur de VIDÉO PROVIDER-AGNOSTIQUE — orchestrateur (miroir de la brique images).

On balaie les fournisseurs DISPONIBLES (cf. fournisseurs.py) dans l'ordre de préférence
et on retient la PREMIÈRE vidéo obtenue. La brique RAPATRIE toujours la vidéo et la sert
depuis son propre stockage (/fichiers/…) : l'appelant n'a jamais à joindre fal, Replicate,
Luma, Runway, etc. directement, ni à connaître les clés.

Repli HONNÊTE : si AUCUN fournisseur n'est configuré, ou si tous échouent (injoignable /
clé invalide / timeout), on rend un PLACEHOLDER SVG qui le DIT (`place_holder: true`). On
ne casse jamais l'appelant, et on ne fait jamais passer un placeholder pour une vraie vidéo.
"""
import html
import os
import uuid
from pathlib import Path
from typing import Optional

import fournisseurs

VIDEOS_DIR = Path(os.getenv("VIDEOS_DIR", "/tmp/videos_brique"))
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


def _enregistrer(nom: str, data: bytes) -> str:
    (VIDEOS_DIR / nom).write_bytes(data)
    return f"/fichiers/{nom}"


def _ext(data: bytes) -> str:
    """Extension d'après les octets magiques (les fournisseurs rendent MP4/WEBM/MOV)."""
    if data[4:8] == b"ftyp":            # conteneur ISO-BMFF : mp4/mov/m4v
        marque = data[8:12]
        return "mov" if marque[:3] == b"qt " else "mp4"
    if data[:4] == b"\x1aE\xdf\xa3":     # EBML : webm / mkv
        return "webm"
    return "mp4"


def _placeholder(prompt: str, note: str = "") -> str:
    """SVG honnête : aperçu textuel du prompt + glyphe ▶ + mention « moteur vidéo absent ».

    Format paysage 16:9 (1280×720) pour s'afficher comme une vignette de lecteur."""
    largeur, hauteur = 1280, 720
    apercu = html.escape((prompt or "")[:160])
    msg = html.escape(note or "Moteur vidéo non branché")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largeur}" height="{hauteur}" '
        f'viewBox="0 0 {largeur} {hauteur}">'
        f'<rect width="100%" height="100%" fill="#120f18"/>'
        f'<rect x="1.5%" y="2.5%" width="97%" height="95%" fill="none" stroke="#4a3d6b" '
        f'stroke-width="3" stroke-dasharray="14 9"/>'
        f'<circle cx="50%" cy="40%" r="70" fill="none" stroke="#cbbcff" stroke-width="5"/>'
        f'<path d="M 615 290 L 615 370 L 685 330 Z" fill="#cbbcff"/>'
        f'<text x="50%" y="62%" fill="#cbbcff" font-family="sans-serif" font-size="36" '
        f'text-anchor="middle">🎬 {msg}</text>'
        f'<text x="50%" y="70%" fill="#8a7fb0" font-family="sans-serif" font-size="22" '
        f'text-anchor="middle">{apercu}</text></svg>'
    )
    nom = f"ph-{uuid.uuid4().hex[:12]}.svg"
    return _enregistrer(nom, svg.encode("utf-8"))


async def fournisseur_actif() -> Optional[str]:
    """Premier fournisseur réellement utilisable (pour /sante).

    Tous nos fournisseurs vidéo sont hébergés : la présence de la clé suffit (on ne brûle
    pas un appel facturé juste pour un état de santé)."""
    dispo = fournisseurs.disponibles()
    return dispo[0] if dispo else None


async def generer(prompt: str, image_url: str = "", secondes: int = 5,
                  seed=None, fournisseur: Optional[str] = None) -> dict:
    """Rend {url, backend, place_holder}. `url` est servie par CETTE brique (/fichiers/…).

    `image_url` (optionnel) = image de départ pour une animation (image→vidéo).
    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    """
    secondes = int(secondes or 5)

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        note = (f"Fournisseur « {fournisseur} » indisponible" if fournisseur
                else "Aucun moteur vidéo configuré")
        return {"url": _placeholder(prompt, note), "prompt": prompt,
                "backend": "placeholder", "place_holder": True, "fournisseurs": candidats}

    erreurs = {}
    for nom in candidats:
        try:
            data = await fournisseurs.REGISTRE[nom].generer(prompt, image_url, secondes, seed)
            if data:
                fichier = f"vid-{uuid.uuid4().hex[:12]}.{_ext(data)}"
                return {"url": _enregistrer(fichier, data), "prompt": prompt,
                        "backend": nom, "place_holder": False}
            erreurs[nom] = "aucune vidéo renvoyée"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return {"url": _placeholder(prompt, "Moteurs essayés sans succès : " + ", ".join(candidats)),
            "prompt": prompt, "backend": "placeholder", "place_holder": True,
            "erreurs": erreurs}
