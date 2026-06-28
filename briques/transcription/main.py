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
import json
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

import destinations
import fournisseurs
import moteur
import rendu
import resume

app = FastAPI(title="Transcription — audio→texte souverain", version="0.1.0")
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


_FRONT = Path(__file__).parent / "front.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    """Front en une page (vanilla) : capter un appel/mémo → notes → ranger. Parle à CETTE
    brique. Sert la démo autonome ET le contenu de l'iframe embarquée par le noyau."""
    return _FRONT.read_text(encoding="utf-8")


# Design system partagé (S123) : tokens visuels du monorepo.
# Source unique = shared/static/workplace.css, copié ici par outils/sync_socle.sh.
@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


# ── PWA : installable sur mobile (écran d'accueil), capture micro en haut-parleur ──
_MANIFEST = {
    "name": "Transcription — notes d'appel",
    "short_name": "Notes d'appel",
    "description": "Capter un appel ou un mémo, transcrire en local, ranger les notes.",
    "start_url": "/atelier",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#120f18",
    "theme_color": "#120f18",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml",
               "purpose": "any maskable"}],
}

_SW = """// Service worker minimal : coque hors-ligne, API toujours réseau.
const C = 'transcription-v1';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(C).then(c => c.addAll(['/atelier', '/icon.svg'])));
  self.skipWaiting();
});
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;                 // POST /notes, /archiver → réseau direct
  if (r.mode === 'navigate') {                     // lancement de l'app → coque en repli
    e.respondWith(fetch(r).catch(() => caches.match('/atelier')));
  }
});
"""

_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
         '<rect width="512" height="512" rx="96" fill="#120f18"/>'
         '<rect x="216" y="120" width="80" height="170" rx="40" fill="#e7c66b"/>'
         '<path d="M168 250a88 88 0 0 0 176 0" fill="none" stroke="#e7c66b" stroke-width="18" '
         'stroke-linecap="round"/>'
         '<line x1="256" y1="338" x2="256" y2="392" stroke="#e7c66b" stroke-width="18" '
         'stroke-linecap="round"/></svg>')


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return Response(json.dumps(_MANIFEST), media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return Response(_SW, media_type="application/javascript")


@app.get("/icon.svg", include_in_schema=False)
def icone():
    return Response(_ICON, media_type="image/svg+xml")


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
