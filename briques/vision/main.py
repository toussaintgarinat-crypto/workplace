"""Brique « vision » — OCR / lecture de documents en API (« les yeux » du Cœur).

Produit autonome, sans dépendance à Oria/Workplace, miroir des briques images/transcription :
  • /extraire : un fichier (PDF/image/Office…) en multipart → texte (le primitif) ;
  • /lire     : un fichier par URL ou base64 (JSON) → texte (programmable + synergie + outil
                du Cœur via le manifest `capacites`) ;
  • /sante    : moteurs connus, configurés et celui qui servirait ;
  • /fournisseurs : catalogue (pour proposer un choix côté UI).

Le moteur est PROVIDER-AGNOSTIQUE (cf. moteur.py) : cascade souveraine LOCALE d'abord
(MarkItDown → Tesseract), puis hébergés à clé (Mistral → Google). Sans aucun moteur, on
rend un message qui le DIT (jamais de faux texte).
"""
import base64
import os
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import fournisseurs
import moteur

app = FastAPI(title="Vision — OCR / lecture de documents", version="0.1.0")
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
MAX_OCTETS = int(os.getenv("VISION_MAX_OCTETS", str(25 * 1024 * 1024)))   # 25 Mo par défaut


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


class Lire(BaseModel):
    url:             Optional[str] = None   # télécharger le fichier à lire
    contenu_base64:  Optional[str] = None   # …ou le fournir en base64 (data-URI toléré)
    nom_fichier:     Optional[str] = None   # aide à deviner le format (extension)
    mime:            Optional[str] = None   # type MIME, sinon deviné de l'extension
    fournisseur:     Optional[str] = None   # force un moteur (sinon : ordre de préférence)


_MIME_PAR_EXT = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
    "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
    "tiff": "image/tiff", "tif": "image/tiff", "bmp": "image/bmp",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html", "htm": "text/html", "txt": "text/plain",
}


def _mime_devine(nom_fichier: str, fourni: str = "") -> str:
    if fourni:
        return fourni
    ext = (nom_fichier or "").rsplit(".", 1)[-1].lower() if "." in (nom_fichier or "") else ""
    return _MIME_PAR_EXT.get(ext, "application/octet-stream")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return ("<h1>👁️ Brique vision</h1><p>OCR / lecture de documents (souverain + repli "
            "honnête). Voir <a href='/docs'>/docs</a>.</p>")


@app.get("/sante", tags=["système"])
async def sante():
    """État du moteur : moteurs OCR connus, ceux configurés (lib/clé), et le moteur actif."""
    actif = await moteur.fournisseur_actif()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),   # tous les moteurs livrés
        "ordre": fournisseurs.ordre(),                         # ordre de préférence effectif
        "configures": fournisseurs.disponibles(),             # ceux dont la lib/clé est là
        "actif": actif,                                        # celui qui servirait (ou null)
        "backend": actif or "placeholder",
    }


@app.get("/fournisseurs", tags=["système"])
def liste_fournisseurs():
    """Catalogue des moteurs OCR : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


@app.post("/extraire", tags=["vision"])
async def extraire(fichier: UploadFile = File(...), fournisseur: Optional[str] = None,
                   _cle: str = Depends(cle_api)):
    """Un fichier en multipart (PDF/image/Office…) → texte extrait par la cascade OCR."""
    data = await fichier.read()
    if not data:
        raise HTTPException(422, "Le fichier est vide.")
    if len(data) > MAX_OCTETS:
        raise HTTPException(413, f"Fichier trop volumineux (> {MAX_OCTETS} octets).")
    mime = _mime_devine(fichier.filename or "", fichier.content_type or "")
    return await moteur.extraire(data, fichier.filename or "", mime, fournisseur=fournisseur)


@app.post("/lire", tags=["vision", "synergie"])
async def lire(body: Lire, _cle: str = Depends(cle_api)):
    """Un fichier par URL OU base64 → texte. Surface JSON (outil du Cœur, synergie briques)."""
    data: bytes
    nom = body.nom_fichier or ""
    if body.contenu_base64:
        brut = body.contenu_base64.split(",", 1)[-1]   # tolère un préfixe data:...;base64,
        try:
            data = base64.b64decode(brut)
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "contenu_base64 invalide.")
    elif body.url:
        if not nom:
            nom = body.url.rstrip("/").rsplit("/", 1)[-1]
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
                r = await c.get(body.url)
                r.raise_for_status()
                data = r.content
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"Téléchargement impossible : {str(e)[:120]}")
    else:
        raise HTTPException(422, "Fournir `url` ou `contenu_base64`.")

    if not data:
        raise HTTPException(422, "Contenu vide.")
    if len(data) > MAX_OCTETS:
        raise HTTPException(413, f"Fichier trop volumineux (> {MAX_OCTETS} octets).")
    mime = _mime_devine(nom, body.mime or "")
    return await moteur.extraire(data, nom, mime, fournisseur=body.fournisseur)
