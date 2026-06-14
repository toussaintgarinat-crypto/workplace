"""Brique « video » — moteur de vidéo en API (fournisseurs hébergés + repli honnête).

Produit autonome, sans dépendance à Oria/Workplace (miroir de la brique images) :
  • /generer   : prompt libre → clip (le primitif text→vidéo) ;
  • /teaser    : titre + synopsis → bande-annonce d'épisode (synergie Studio) ;
  • /animer    : fiche de personnage (+ portrait) → clip animé du perso (synergie Personnages) ;
  • /fichiers/*: sert les vidéos produites (MP4 rapatriés des fournisseurs ou placeholder SVG).

Le moteur est PROVIDER-AGNOSTIQUE (cf. moteur.py) : on branche fal / Replicate / Luma /
Runway / la Gateway par variables d'env ; sans fournisseur, on rend un placeholder qui
le DIT (jamais de fausse vidéo). Le Mac n'a pas de GPU → pas de moteur souverain local.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import fournisseurs
import moteur
import prompts

app = FastAPI(title="Video — moteur de génération vidéo", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


class Generer(BaseModel):
    prompt:      str
    image_url:   Optional[str] = None   # image de départ (image→vidéo) ; sinon text→vidéo
    secondes:    int = 5
    seed:        Optional[int] = None
    fournisseur: Optional[str] = None   # force un moteur (sinon : ordre de préférence)


class Teaser(BaseModel):
    titre:       Optional[str] = ""
    synopsis:    Optional[str] = ""
    style:       Optional[str] = None
    personnages: Optional[list] = None
    secondes:    int = 5
    fournisseur: Optional[str] = None


class Animer(BaseModel):
    fiche:       dict                   # {nom, role, description, archetype, empreinte, ...}
    image_url:   Optional[str] = None   # portrait à animer (recommandé) ; sinon text→vidéo
    style:       Optional[str] = None
    secondes:    int = 5
    fournisseur: Optional[str] = None


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return ("<h1>🎬 Brique video</h1><p>Moteur de génération vidéo (fal/Replicate/Luma/"
            "Runway/Gateway + repli honnête). Voir <a href='/docs'>/docs</a>.</p>")


@app.get("/sante", tags=["système"])
async def sante():
    """État du moteur : fournisseurs connus, ceux configurés (clé), et le moteur actif."""
    actif = await moteur.fournisseur_actif()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),   # tous les moteurs livrés
        "ordre": fournisseurs.ordre(),                         # ordre de préférence effectif
        "configures": fournisseurs.disponibles(),             # ceux dont la clé est là
        "actif": actif,                                        # celui qui servirait (ou null)
        "backend": actif or "placeholder",
    }


@app.get("/fournisseurs", tags=["système"])
async def liste_fournisseurs():
    """Catalogue des moteurs : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


@app.post("/generer", tags=["video"])
async def generer(body: Generer, _cle: str = Depends(cle_api)):
    if not (body.prompt or "").strip():
        raise HTTPException(422, "Le prompt est vide.")
    return await moteur.generer(body.prompt, body.image_url or "", body.secondes,
                                body.seed, fournisseur=body.fournisseur)


@app.post("/teaser", tags=["video", "synergie"])
async def teaser(body: Teaser, _cle: str = Depends(cle_api)):
    """Titre + synopsis (+ personnages) → bande-annonce d'épisode (synergie Studio)."""
    p = prompts.prompt_teaser(body.titre or "", body.synopsis or "",
                              style=body.style or "", personnages=body.personnages)
    res = await moteur.generer(p["prompt"], "", body.secondes, fournisseur=body.fournisseur)
    return {**res, "prompt_visuel": p["prompt"]}


@app.post("/animer", tags=["video", "synergie"])
async def animer(body: Animer, _cle: str = Depends(cle_api)):
    """Fiche de personnage (+ portrait) → clip animé du perso (synergie Personnages)."""
    p = prompts.prompt_animation(body.fiche, style=body.style or "")
    res = await moteur.generer(p["prompt"], body.image_url or "", body.secondes,
                               fournisseur=body.fournisseur)
    return {**res, "prompt_visuel": p["prompt"]}


@app.get("/fichiers/{nom}", tags=["système"], include_in_schema=False)
def fichier(nom: str):
    """Sert une vidéo produite (MP4/WEBM rapatrié, ou placeholder SVG)."""
    chemin = (moteur.VIDEOS_DIR / nom).resolve()
    if not str(chemin).startswith(str(moteur.VIDEOS_DIR.resolve())) or not chemin.is_file():
        raise HTTPException(404, "Vidéo introuvable.")
    media = {"svg": "image/svg+xml", "mp4": "video/mp4",
             "webm": "video/webm", "mov": "video/quicktime"}.get(nom.rsplit(".", 1)[-1],
                                                                  "application/octet-stream")
    return FileResponse(chemin, media_type=media)
