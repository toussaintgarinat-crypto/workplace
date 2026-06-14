"""Moteur d'images PROVIDER-AGNOSTIQUE — orchestrateur.

On balaie les fournisseurs DISPONIBLES (cf. fournisseurs.py) dans l'ordre de préférence
et on retient la PREMIÈRE image obtenue. La brique RAPATRIE toujours l'image et la sert
depuis son propre stockage (/fichiers/…) : l'appelant n'a jamais à joindre ComfyUI, fal,
Replicate, etc. directement, ni à connaître les clés.

Repli HONNÊTE : si AUCUN fournisseur n'est configuré, ou si tous échouent (injoignable /
clé invalide / timeout), on rend un PLACEHOLDER SVG qui le DIT (`place_holder: true`). On
ne casse jamais l'appelant, et on ne fait jamais passer un placeholder pour une vraie image.
"""
import html
import os
import uuid
from pathlib import Path
from typing import Optional

import fournisseurs

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "/tmp/images_brique"))
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _enregistrer(nom: str, data: bytes) -> str:
    (IMAGES_DIR / nom).write_bytes(data)
    return f"/fichiers/{nom}"


def _ext(data: bytes) -> str:
    """Extension d'après les octets magiques (les fournisseurs rendent PNG/JPEG/WEBP)."""
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "png"


def _placeholder(prompt: str, largeur: int, hauteur: int, note: str = "") -> str:
    """SVG honnête : aperçu textuel du prompt + mention claire « moteur d'images absent »."""
    apercu = html.escape((prompt or "")[:140])
    msg = html.escape(note or "Moteur d'images non branché")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largeur}" height="{hauteur}" '
        f'viewBox="0 0 {largeur} {hauteur}">'
        f'<rect width="100%" height="100%" fill="#1a1620"/>'
        f'<rect x="2%" y="2%" width="96%" height="96%" fill="none" stroke="#4a3d6b" '
        f'stroke-width="3" stroke-dasharray="12 8"/>'
        f'<text x="50%" y="44%" fill="#cbbcff" font-family="sans-serif" font-size="34" '
        f'text-anchor="middle">🖼️ {msg}</text>'
        f'<text x="50%" y="54%" fill="#8a7fb0" font-family="sans-serif" font-size="20" '
        f'text-anchor="middle">{apercu}</text></svg>'
    )
    nom = f"ph-{uuid.uuid4().hex[:12]}.svg"
    return _enregistrer(nom, svg.encode("utf-8"))


async def fournisseur_actif() -> Optional[str]:
    """Premier fournisseur réellement utilisable (pour /sante).

    Pour ComfyUI on vérifie la JOIGNABILITÉ réseau ; pour les hébergés, la présence de la
    clé suffit (on ne brûle pas un appel facturé juste pour un état de santé)."""
    for nom in fournisseurs.disponibles():
        f = fournisseurs.REGISTRE[nom]
        if nom == "comfyui":
            if await f.premier_joignable():
                return nom
        else:
            return nom
    return None


async def generer(prompt: str, negatif: str = "", largeur: int = 1024, hauteur: int = 1024,
                  seed=None, fournisseur: Optional[str] = None) -> dict:
    """Rend {url, backend, place_holder}. `url` est servie par CETTE brique (/fichiers/…).

    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    """
    largeur, hauteur = int(largeur or 1024), int(hauteur or 1024)

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        note = (f"Fournisseur « {fournisseur} » indisponible" if fournisseur
                else "Aucun moteur d'images configuré")
        return {"url": _placeholder(prompt, largeur, hauteur, note), "prompt": prompt,
                "backend": "placeholder", "place_holder": True, "fournisseurs": candidats}

    erreurs = {}
    for nom in candidats:
        try:
            data = await fournisseurs.REGISTRE[nom].generer(prompt, negatif, largeur, hauteur, seed)
            if data:
                fichier = f"img-{uuid.uuid4().hex[:12]}.{_ext(data)}"
                return {"url": _enregistrer(fichier, data), "prompt": prompt,
                        "backend": nom, "place_holder": False}
            erreurs[nom] = "aucune image renvoyée"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return {"url": _placeholder(prompt, largeur, hauteur,
                                "Moteurs essayés sans succès : " + ", ".join(candidats)),
            "prompt": prompt, "backend": "placeholder", "place_holder": True,
            "erreurs": erreurs}
