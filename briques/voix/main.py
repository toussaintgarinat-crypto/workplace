"""Brique « voix » — synthèse vocale (TTS) texte→audio en API, SOUVERAINE par défaut.

Miroir EXACT de la brique transcription (audio→texte), dans l'autre sens. Produit autonome,
composable par l'assistant et le pont messageries (réponse vocale → boucle speech-to-speech) :
  • /synthetiser : texte → audio (octets bruts) ;
  • /voix        : catalogue des voix/fournisseurs configurés.

Le moteur est PROVIDER-AGNOSTIQUE (cf. moteur.py) : Piper LOCAL souverain en tête, puis
OpenAI / ElevenLabs / la Gateway en repli OPT-IN. Sans moteur, on rend un repli HONNÊTE
(`place_holder: true`, pas d'audio) — jamais de fausse voix.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import fournisseurs
import moteur

app = FastAPI(title="Voix — synthèse vocale souveraine (TTS)", version="0.1.0")
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

# Format audio → type MIME du corps de réponse (opus = conteneur Ogg, idéal message vocal).
_MEDIA = {"opus": "audio/ogg", "ogg": "audio/ogg", "oga": "audio/ogg", "mp3": "audio/mpeg",
          "wav": "audio/wav", "aac": "audio/aac", "flac": "audio/flac", "pcm": "audio/L16"}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


class Synthese(BaseModel):
    texte:       str
    voix:        Optional[str] = None
    langue:      Optional[str] = None
    format:      Optional[str] = None
    fournisseur: Optional[str] = None


@app.get("/sante", tags=["système"])
async def sante():
    """État : fournisseurs connus, configurés, moteur actif, souveraineté."""
    actif = await moteur.fournisseur_actif()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),
        "ordre": fournisseurs.ordre(),
        "configures": fournisseurs.disponibles(),
        "actif": actif,
        "backend": actif or "placeholder",
        "souverain": actif == "piper",
    }


@app.get("/voix", tags=["système"])
async def liste_voix():
    """Catalogue des moteurs TTS : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


@app.post("/synthetiser", tags=["synthese"])
async def synthetiser(body: Synthese, _cle: str = Depends(cle_api)):
    """Texte → audio. Renvoie les OCTETS audio (Content-Type adapté) si un moteur a répondu,
    sinon un JSON `place_holder: true` honnête (200, pas d'audio inventé)."""
    if not (body.texte or "").strip():
        raise HTTPException(422, "Le texte est vide.")
    res = await moteur.synthetiser(body.texte, body.voix, body.langue, body.format,
                                   body.fournisseur)
    if res.get("place_holder") or not res.get("audio"):
        return JSONResponse({k: v for k, v in res.items() if k != "audio"}, status_code=200)
    media = _MEDIA.get(res["format"], "application/octet-stream")
    return Response(res["audio"], media_type=media,
                    headers={"X-Backend": res["backend"], "X-Format": res["format"]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5985")))
