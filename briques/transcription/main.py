"""Brique « transcription » — audio→texte en API, SOUVERAINE par défaut.

Inspirée de Notta/Otter, SANS aucun appel à un tiers imposé : on héberge notre propre
moteur. Produit autonome, miroir des briques images/vidéo :
  • /transcrire     : upload d'un fichier audio → transcription (+ diarisation optionnelle) ;
  • /transcrire-url : URL d'un audio → transcription (souplesse / synergie) ;
  • /resumer        : transcription (texte) → notes de réunion (résumé/points d'action) ;
  • /notes          : LE flux complet — upload audio → transcription + notes en un appel.

Le moteur est PROVIDER-AGNOSTIQUE (cf. moteur.py) : Whisper LOCAL souverain en tête, puis
OpenAI / Deepgram / AssemblyAI / la Gateway en repli OPT-IN. Sans moteur, on rend un repli
HONNÊTE (texte vide, `place_holder: true`) — jamais de fausse transcription. La synthèse
passe par l'« économe gratuit » (≈0 $) comme le briefing S30, repli heuristique honnête.
"""
import os
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import destinations
import fournisseurs
import moteur
import rendu
import resume

app = FastAPI(title="Transcription — audio→texte souverain", version="0.1.0")
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


def _vrai(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "oui", "yes", "on")


class TranscrireURL(BaseModel):
    url:         str
    langue:      Optional[str] = None
    diarisation: bool = False
    fournisseur: Optional[str] = None


class Resumer(BaseModel):
    texte:  str
    langue: Optional[str] = None


class Archiver(BaseModel):
    notes:         dict                          # sortie de /resumer ou /notes["notes"]
    transcription: Optional[dict] = None         # sortie de /transcrire (facultatif)
    titre:         Optional[str] = None
    langue:        Optional[str] = None
    destination:   Optional[str] = None          # memoire | dossier (défaut : souverain)
    dossier:       Optional[str] = None          # pour destination=dossier (sinon NOTES_DOSSIER)
    espace:        Optional[str] = None           # pour destination=memoire


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return ("<h1>🎙️ Brique transcription</h1><p>Audio→texte souverain (Whisper local en "
            "tête, fournisseurs hébergés en repli) + notes de réunion (économe gratuit). "
            "Voir <a href='/docs'>/docs</a>.</p>")


@app.get("/sante", tags=["système"])
async def sante():
    """État : fournisseurs connus, configurés, moteur actif, et synthèse LLM dispo."""
    actif = await moteur.fournisseur_actif()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),
        "ordre": fournisseurs.ordre(),
        "configures": fournisseurs.disponibles(),
        "actif": actif,
        "backend": actif or "placeholder",
        "souverain": actif == "local",
        "synthese_llm": resume.disponible(),
    }


@app.get("/fournisseurs", tags=["système"])
async def liste_fournisseurs():
    """Catalogue des moteurs : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


async def _telecharger(url: str) -> tuple[bytes, str]:
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content, url.split("/")[-1].split("?")[0] or "audio.wav"
    except httpx.HTTPError as e:
        raise HTTPException(422, f"Audio injoignable : {e}")


@app.post("/transcrire", tags=["transcription"])
async def transcrire(fichier: UploadFile = File(...),
                     langue: Optional[str] = Form(None),
                     diarisation: str = Form("false"),
                     fournisseur: Optional[str] = Form(None),
                     _cle: str = Depends(cle_api)):
    """Upload d'un fichier audio → transcription (+ diarisation optionnelle)."""
    audio = await fichier.read()
    if not audio:
        raise HTTPException(422, "Fichier audio vide.")
    return await moteur.transcrire(audio, fichier.filename or "audio.wav", langue,
                                   _vrai(diarisation), fournisseur)


@app.post("/transcrire-url", tags=["transcription"])
async def transcrire_url(body: TranscrireURL, _cle: str = Depends(cle_api)):
    """URL d'un audio → transcription (souplesse / synergie)."""
    audio, nom = await _telecharger(body.url)
    return await moteur.transcrire(audio, nom, body.langue, body.diarisation, body.fournisseur)


@app.post("/resumer", tags=["notes", "synergie"])
async def resumer(body: Resumer, _cle: str = Depends(cle_api)):
    """Transcription (texte) → notes de réunion (résumé / points d'action / décisions)."""
    if not (body.texte or "").strip():
        raise HTTPException(422, "Le texte est vide.")
    return await resume.resumer(body.texte, body.langue)


@app.get("/destinations", tags=["archivage"])
async def liste_destinations():
    """Catalogue des destinations d'archivage + lesquelles sont configurées + le défaut."""
    return {"destinations": [{"nom": n, "configure": d.disponible()}
                             for n, d in destinations.REGISTRE.items()],
            "defaut": destinations.defaut(),
            "configurees": destinations.disponibles()}


@app.post("/archiver", tags=["archivage", "synergie"])
async def archiver(body: Archiver, _cle: str = Depends(cle_api)):
    """Dépose des notes dans la destination CHOISIE (mémoire souveraine ou dossier au choix).

    Pont consenti : la destination est explicite (jamais automatique). Si elle échoue, on
    rend `{ok: false, erreur}` sans rien perdre en silence."""
    p = rendu.paquet(body.notes, body.transcription, body.titre, body.langue)
    return await destinations.archiver(p, body.destination, dossier=body.dossier,
                                       espace=body.espace)


@app.post("/notes", tags=["notes"])
async def notes(fichier: UploadFile = File(...),
                langue: Optional[str] = Form(None),
                diarisation: str = Form("false"),
                fournisseur: Optional[str] = Form(None),
                destination: Optional[str] = Form(None),
                dossier: Optional[str] = Form(None),
                _cle: str = Depends(cle_api)):
    """LE flux complet (façon Notta) : upload audio → transcription + notes en un appel.

    Si `destination` est fournie (memoire | dossier), on archive aussi les notes dans la
    foulée (pont consenti, opt-in) et on renvoie le résultat sous `archivage`."""
    audio = await fichier.read()
    if not audio:
        raise HTTPException(422, "Fichier audio vide.")
    trans = await moteur.transcrire(audio, fichier.filename or "audio.wav", langue,
                                    _vrai(diarisation), fournisseur)
    notes_ = await resume.resumer(trans.get("texte", ""), langue)
    reponse = {"transcription": trans, "notes": notes_}
    if destination:
        p = rendu.paquet(notes_, trans, langue=langue)
        reponse["archivage"] = await destinations.archiver(p, destination, dossier=dossier)
    return reponse
