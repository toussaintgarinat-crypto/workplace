"""Brique « images » — moteur d'illustration en API (ComfyUI souverain + repli honnête).

Produit autonome, sans dépendance à Oria/Workplace :
  • /generer    : prompt libre → image (le primitif) ;
  • /portrait   : fiche de personnage → prompt visuel dérivé → image (synergie Personnages) ;
  • /couverture : titre + synopsis → image de couverture (synergie Studio) ;
  • /fichiers/* : sert les images produites (rapatriées de ComfyUI ou placeholder SVG).

Le moteur est PROVIDER-AGNOSTIQUE (cf. moteur.py) : on branche ComfyUI par `COMFY_URL` ;
sans backend, on rend un placeholder qui le DIT (jamais de fausse image).
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import fournisseurs
import moteur
import prompts

app = FastAPI(title="Images — moteur d'illustration", version="0.2.0")
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

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
    negatif:     Optional[str] = None
    largeur:     int = 1024
    hauteur:     int = 1024
    seed:        Optional[int] = None
    fournisseur: Optional[str] = None   # force un moteur (sinon : ordre de préférence)
    modele:      Optional[str] = None   # override ponctuel, honoré par le fournisseur gateway


class Portrait(BaseModel):
    fiche:       dict                  # {nom, role, description, archetype, empreinte/tags, ...}
    style:       Optional[str] = None
    largeur:     int = 768
    hauteur:     int = 1024            # portrait = format vertical par défaut
    fournisseur: Optional[str] = None


class Couverture(BaseModel):
    titre:       Optional[str] = ""
    synopsis:    Optional[str] = ""
    style:       Optional[str] = None
    personnages: Optional[list] = None
    largeur:     int = 1024
    hauteur:     int = 1024
    fournisseur: Optional[str] = None


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return ("<h1>🖼️ Brique images</h1><p>Moteur d'illustration (ComfyUI + repli honnête). "
            "Voir <a href='/docs'>/docs</a>.</p>")


@app.get("/sante", tags=["système"])
async def sante():
    """État du moteur : fournisseurs connus, ceux configurés (clé/URL), et le moteur actif."""
    actif = await moteur.fournisseur_actif()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),   # tous les moteurs livrés
        "ordre": fournisseurs.ordre(),                         # ordre de préférence effectif
        "configures": fournisseurs.disponibles(),             # ceux dont la clé/URL est là
        "actif": actif,                                        # celui qui servirait (ou null)
        "backend": actif or "placeholder",
    }


@app.get("/fournisseurs", tags=["système"])
async def liste_fournisseurs():
    """Catalogue des moteurs : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


@app.get("/modeles", tags=["système"])
async def liste_modeles():
    """Modèles d'image disponibles via la Gateway (OpenRouter), pour le comparatif de
    l'Atelier Images & Vidéo. Liste TOUJOURS interrogée en direct (avec cache côté
    fournisseurs.py) : jamais de catalogue figé en dur qui pourrait devenir obsolète."""
    try:
        modeles = await fournisseurs.modeles_image_openrouter()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"OpenRouter injoignable : {str(e)[:160]}")
    return {"modeles": modeles}


@app.post("/generer", tags=["images"])
async def generer(body: Generer, _cle: str = Depends(cle_api)):
    if not (body.prompt or "").strip():
        raise HTTPException(422, "Le prompt est vide.")
    return await moteur.generer(body.prompt, body.negatif or "", body.largeur,
                                body.hauteur, body.seed, fournisseur=body.fournisseur,
                                modele=body.modele)


@app.post("/portrait", tags=["images", "synergie"])
async def portrait(body: Portrait, _cle: str = Depends(cle_api)):
    """Fiche de personnage → prompt visuel dérivé → image (synergie Personnages)."""
    p = prompts.prompt_portrait(body.fiche, style=body.style or "")
    res = await moteur.generer(p["prompt"], p["negatif"], body.largeur, body.hauteur,
                               fournisseur=body.fournisseur)
    return {**res, "prompt_visuel": p["prompt"]}


@app.post("/couverture", tags=["images", "synergie"])
async def couverture(body: Couverture, _cle: str = Depends(cle_api)):
    """Titre + synopsis (+ personnages) → image de couverture (synergie Studio)."""
    p = prompts.prompt_couverture(body.titre or "", body.synopsis or "",
                                  style=body.style or "", personnages=body.personnages)
    res = await moteur.generer(p["prompt"], p["negatif"], body.largeur, body.hauteur,
                               fournisseur=body.fournisseur)
    return {**res, "prompt_visuel": p["prompt"]}


@app.get("/fichiers/{nom}", tags=["système"], include_in_schema=False)
def fichier(nom: str):
    """Sert une image produite (PNG rapatrié de ComfyUI, ou placeholder SVG)."""
    chemin = (moteur.IMAGES_DIR / nom).resolve()
    if not str(chemin).startswith(str(moteur.IMAGES_DIR.resolve())) or not chemin.is_file():
        raise HTTPException(404, "Image introuvable.")
    media = "image/svg+xml" if nom.endswith(".svg") else "image/png"
    return FileResponse(chemin, media_type=media)
