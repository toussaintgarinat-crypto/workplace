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
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException,
                     UploadFile, WebSocket)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import clones
import fournisseurs
import moteur
import realtime
import reglages

app = FastAPI(title="Voix — TTS souverain + chat vocal temps réel", version="0.7.0")
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

# Dossier de persistance des épisodes produits par /rendre.
_EPISODES_DIR = Path(os.getenv("VOIX_DIR", "/data/voix")) / "episodes"


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
    usage:       Optional[str] = None            # "conversation" / "lecture" ; sinon auto (longueur)


class SegmentRendre(BaseModel):
    voix:  Optional[str] = None
    texte: str


class RequeteRendre(BaseModel):
    episode_id: Optional[str] = None
    segments:   List[SegmentRendre]
    langue:     Optional[str] = None


class ChoixMoteur(BaseModel):
    fournisseur: Optional[str] = None            # None / "" / "auto" → ordre par défaut
    role:        Optional[str] = "conversation"  # "conversation" (rapide) / "lecture" (belle)


# Métadonnées d'affichage des moteurs (pour la page de réglage : nature + comment l'activer).
_INFO_MOTEUR = {
    "piper":      {"libelle": "Piper", "nature": "local souverain",
                   "note": "Rapide, 100 % local. Voix synthétique."},
    "kokoro":     {"libelle": "Kokoro", "nature": "local naturel",
                   "note": "Voix naturelle, locale. Plus lourd (CPU/GPU)."},
    "coqui":      {"libelle": "Coqui XTTS", "nature": "local · lecture",
                   "note": "Voix de lecture haut de gamme, 100 % locale + clonage. Lente en "
                           "CPU (OK pour les résumés). Modèle XTTS sous licence non commerciale."},
    "openai":     {"libelle": "OpenAI", "nature": "hébergé payant",
                   "note": "Très naturel. Le texte part chez OpenAI (clé requise)."},
    "elevenlabs": {"libelle": "ElevenLabs", "nature": "hébergé payant",
                   "note": "Le plus expressif. Le texte part chez ElevenLabs (clé requise)."},
    "gateway":    {"libelle": "Gateway", "nature": "hébergé",
                   "note": "Passe par la Gateway Workplace (clé Gateway)."},
}


@app.get("/sante", tags=["système"])
async def sante():
    """État : fournisseurs connus, configurés, moteur actif, souveraineté."""
    actif = await moteur.fournisseur_actif()
    rt = realtime.fournisseurs_configures()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),
        "ordre": fournisseurs.ordre(),
        "configures": fournisseurs.disponibles(),
        "actif": actif,
        "backend": actif or "placeholder",
        "souverain": actif == "piper",
        # Chat vocal temps réel (porté de Gungnir) : moteurs configurés (clé présente).
        "temps_reel": [n for n, info in rt.items() if info["configure"]],
    }


@app.get("/voix", tags=["système"])
async def liste_voix():
    """Catalogue des moteurs TTS : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


@app.get("/voix/moteur", tags=["système"])
async def lire_moteur():
    """État pour la page de réglage : moteurs des deux RÔLES (conversation rapide / lecture
    belle), moteur actif, seuil de bascule, et la liste des moteurs avec leur disponibilité
    (un moteur non installé/non configuré n'est pas sélectionnable)."""
    actif = await moteur.fournisseur_actif()
    fournis = []
    for nom, f in fournisseurs.REGISTRE.items():
        info = _INFO_MOTEUR.get(nom, {})
        fournis.append({"nom": nom, "configure": f.disponible(),
                        "libelle": info.get("libelle", nom), "nature": info.get("nature", ""),
                        "note": info.get("note", "")})
    return {"ok": True, "choisi": reglages.moteur_choisi(),
            "lecture": reglages.moteur_lecture(), "seuil": reglages.seuil_lecture(),
            "actif": actif, "ordre": fournisseurs.ordre(), "fournisseurs": fournis}


@app.post("/voix/moteur", tags=["système"])
async def choisir_moteur(body: ChoixMoteur, _cle: str = Depends(cle_api)):
    """Change le moteur d'un RÔLE EN UN CLIC (persiste, effet immédiat sans redémarrage).
    `role` = `conversation` (voix rapide, défaut) ou `lecture` (voix belle pour résumés/longs
    textes). Refuse HONNÊTEMENT un moteur inconnu (400) ou non disponible/non installé (409)."""
    role = (body.role or "conversation").strip().lower()
    if role not in ("conversation", "lecture"):
        raise HTTPException(400, f"Rôle inconnu : « {role} » (attendu conversation/lecture).")
    nom = (body.fournisseur or "").strip().lower()
    if nom in ("", "auto", "defaut", "défaut"):
        valeur = reglages.definir_moteur(None, role)  # retour au défaut pour ce rôle
    else:
        f = fournisseurs.REGISTRE.get(nom)
        if f is None:
            raise HTTPException(400, f"Moteur inconnu : « {nom} ».")
        if not f.disponible():
            info = _INFO_MOTEUR.get(nom, {})
            raise HTTPException(409, f"Le moteur « {info.get('libelle', nom)} » n'est pas "
                                     f"disponible (non installé ou non configuré).")
        try:
            valeur = reglages.definir_moteur(nom, role)
        except Exception as e:  # noqa: BLE001 — dossier non inscriptible → honnête
            raise HTTPException(500, f"Impossible d'enregistrer le choix : {e}")
    return {"ok": True, "role": role, "valeur": valeur,
            "choisi": reglages.moteur_choisi(), "lecture": reglages.moteur_lecture(),
            "actif": await moteur.fournisseur_actif()}


@app.get("/", include_in_schema=False)
async def page_reglage():
    """Page web autoportée : choisir la voix en un clic + bouton « Tester »."""
    chemin = os.path.join(os.path.dirname(__file__), "front.html")
    if os.path.exists(chemin):
        return FileResponse(chemin)
    raise HTTPException(404, "Page de réglage absente.")


# Design system partagé (S123) : tokens visuels du monorepo.
# Source unique = shared/static/workplace.css, copié ici par outils/sync_socle.sh.
@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(os.path.join(os.path.dirname(__file__), "workplace.css"),
                        media_type="text/css")


@app.post("/synthetiser", tags=["synthese"])
async def synthetiser(body: Synthese, _cle: str = Depends(cle_api)):
    """Texte → audio. Renvoie les OCTETS audio (Content-Type adapté) si un moteur a répondu,
    sinon un JSON `place_holder: true` honnête (200, pas d'audio inventé)."""
    if not (body.texte or "").strip():
        raise HTTPException(422, "Le texte est vide.")
    res = await moteur.synthetiser(body.texte, body.voix, body.langue, body.format,
                                   body.fournisseur, body.usage)
    if res.get("place_holder") or not res.get("audio"):
        return JSONResponse({k: v for k, v in res.items() if k != "audio"}, status_code=200)
    media = _MEDIA.get(res["format"], "application/octet-stream")
    return Response(res["audio"], media_type=media,
                    headers={"X-Backend": res["backend"], "X-Format": res["format"]})


@app.post("/rendre", tags=["synthese"])
async def rendre(body: RequeteRendre, _cle: str = Depends(cle_api)):
    """Batch TTS : liste de segments {voix, texte} → un MP3 concaténé.
    Persiste dans /data/voix/episodes/. Renvoie {url, duree, episode_id}."""
    if not body.segments:
        raise HTTPException(422, "Aucun segment fourni.")
    _EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    ep_id = (body.episode_id or "").strip() or str(uuid.uuid4())

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fichiers = []
        for i, seg in enumerate(body.segments):
            texte = (seg.texte or "").strip()
            if not texte:
                continue
            res = await moteur.synthetiser(texte, seg.voix, body.langue, "wav", None, None)
            if res.get("place_holder") or not res.get("audio"):
                continue
            p = tmp_path / f"seg_{i:04d}.wav"
            p.write_bytes(res["audio"])
            fichiers.append(str(p))

        if not fichiers:
            raise HTTPException(502, "Aucun segment synthétisé (moteur voix indisponible).")

        liste = tmp_path / "liste.txt"
        liste.write_text("\n".join(f"file '{f}'" for f in fichiers))
        sortie = _EPISODES_DIR / f"{ep_id}.mp3"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(liste), "-c:a", "libmp3lame", "-q:a", "4", str(sortie)],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0:
            raise HTTPException(502, f"ffmpeg : {proc.stderr.decode()[:300]}")

    dur = None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(sortie)],
            capture_output=True, text=True, timeout=10,
        )
        dur = float(r.stdout.strip())
    except Exception:  # noqa: BLE001
        pass

    url = f"http://localhost:5985/episodes/{ep_id}.mp3"
    return {"url": url, "duree": dur, "episode_id": ep_id}


@app.get("/episodes/{ep_id}.mp3", tags=["synthese"], include_in_schema=False)
async def telecharger_episode(ep_id: str):
    """Sert un épisode MP3 produit par /rendre."""
    p = _EPISODES_DIR / f"{ep_id}.mp3"
    if not p.exists():
        raise HTTPException(404, f"Épisode {ep_id!r} introuvable.")
    return FileResponse(str(p), media_type="audio/mpeg",
                        headers={"Content-Disposition": f'inline; filename="{ep_id}.mp3"'})


# ── Bibliothèque de VOIX CLONÉES (S107) — cloner une fois, rappeler partout ──
# Coqui XTTS reproduit un timbre depuis un court échantillon (speaker_wav). On range ces
# échantillons sous un nom (clones.py) pour les réutiliser : assistant, lecture de résumés,
# personnages des séries du Studio (via GET /voix/clones, capacité au manifest). La synthèse
# avec une voix clonée passe par la convention `voix: "clone:<nom>"` de /synthetiser.

@app.get("/voix/clones", tags=["clones"])
async def lister_clones():
    """Liste les voix clonées enregistrées (nom, date, durée, notes). Sert l'UI ET le Studio
    (réutilisation transverse). Indique si Coqui est disponible — sans lui, les clones ne
    peuvent pas être rendus (on le DIT honnêtement plutôt que d'échouer en silence)."""
    coqui = fournisseurs.REGISTRE["coqui"].disponible()
    return {"ok": True, "clones": clones.lister(), "coqui_disponible": coqui,
            "convention": "clone:<nom>"}


@app.post("/voix/clones", tags=["clones"])
async def creer_clone(nom: str = Form(...), fichier: UploadFile = File(...),
                      notes: str = Form(""), _cle: str = Depends(cle_api)):
    """Enregistre un échantillon de référence (WAV ~10-20 s) sous un nom réutilisable.
    Valide honnêtement le fichier (WAV, durée mini). ÉTHIQUE : ne cloner qu'une voix qu'on a
    le droit d'utiliser (consentement) — la responsabilité reste humaine."""
    octets = await fichier.read()
    try:
        entree = clones.enregistrer(nom, octets, notes)
    except ValueError as e:                          # entrée invalide → 422 honnête
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001 — dossier non inscriptible, etc.
        raise HTTPException(500, f"Impossible d'enregistrer la voix : {e}")
    return {"ok": True, "clone": entree}


@app.delete("/voix/clones/{nom}", tags=["clones"])
async def supprimer_clone(nom: str, _cle: str = Depends(cle_api)):
    """Retire une voix clonée (fichier + index). 404 honnête si elle n'existe pas."""
    if not clones.supprimer(nom):
        raise HTTPException(404, f"Voix clonée « {nom} » introuvable.")
    return {"ok": True, "supprime": nom}


class TestClone(BaseModel):
    texte:  Optional[str] = None
    format: Optional[str] = None


@app.post("/voix/clones/{nom}/tester", tags=["clones"])
async def tester_clone(nom: str, body: TestClone = TestClone(), _cle: str = Depends(cle_api)):
    """Écoute un échantillon synthétisé AVEC cette voix clonée. Renvoie les octets audio, ou un
    JSON placeholder honnête si Coqui n'est pas disponible / la voix est inconnue."""
    if clones.obtenir(nom) is None:
        raise HTTPException(404, f"Voix clonée « {nom} » introuvable.")
    texte = (body.texte or "").strip() or (
        "Bonjour, ceci est un essai de ma voix enregistrée dans la bibliothèque.")
    res = await moteur.synthetiser(texte, f"{clones.PREFIXE}{nom}", None, body.format, None, None)
    if res.get("place_holder") or not res.get("audio"):
        return JSONResponse({k: v for k, v in res.items() if k != "audio"}, status_code=200)
    media = _MEDIA.get(res["format"], "application/octet-stream")
    return Response(res["audio"], media_type=media,
                    headers={"X-Backend": res["backend"], "X-Format": res["format"]})


# ── Chat vocal TEMPS RÉEL (speech-to-speech) — porté du plugin voice de Gungnir ──
# Le TTS Piper ci-dessus est le geste « texte → audio » souverain. Ces endpoints
# ajoutent l'autre versant : une CONVERSATION vocale bidirectionnelle, en relayant un
# WebSocket navigateur ↔ l'API temps réel d'un fournisseur (OpenAI / Gemini / Grok).
# OPT-IN : chaque relais reste inerte tant que sa clé n'est pas renseignée (cf. realtime.py).

@app.get("/voix/realtime", tags=["temps-réel"])
async def realtime_fournisseurs():
    """Catalogue des fournisseurs de chat vocal temps réel + leur état de configuration."""
    return {"fournisseurs": realtime.fournisseurs_configures(), "agent": realtime.nom_agent()}


@app.websocket("/realtime/openai")
async def ws_openai(websocket: WebSocket):
    """Relais WebSocket navigateur ↔ OpenAI Realtime (PCM16 24 kHz)."""
    await realtime.relai_openai(websocket)


@app.websocket("/realtime/google")
async def ws_google(websocket: WebSocket):
    """Relais WebSocket navigateur ↔ Gemini Multimodal Live."""
    await realtime.relai_google(websocket)


@app.websocket("/realtime/grok")
async def ws_grok(websocket: WebSocket):
    """Relais WebSocket navigateur ↔ xAI Grok Realtime (OpenAI-compatible)."""
    await realtime.relai_grok(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5985")))
