"""Brique « audit-fichiers » — scan antivirus (ClamAV/clamd) avant acceptation d'un fichier.

Service autonome, appelé SERVEUR-À-SERVEUR par une autre brique juste avant qu'elle
n'accepte un fichier envoyé par un utilisateur (vision /extraire, peertube
/videos/upload...). Adapté (licence MIT) du projet suitenumerique/file-scanner
(ANCT/DINUM), simplifié pour Workplace : un seul moteur (ClamAV, pas de sélection
catégories/nsfw/exav/jcop), scan SYNCHRONE uniquement (pas de file d'attente
dramatiq/Redis), auth API_KEYS standard Workplace (pas de JWT Ed25519 multi-émetteur).
FAIL-CLOSED : si ClamAV est injoignable, le fichier est REFUSÉ (jamais annoncé "propre"
sans avoir été scanné en entier) — voir
docs/superpowers/plans/2026-07-25-s195-brique-audit-fichiers-antivirus.md.
"""
from __future__ import annotations

import io
import os
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import moteur_clamav as moteur

app = FastAPI(title="Audit fichiers — scan antivirus (ClamAV)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
MAX_OCTETS = int(os.getenv("AUDIT_FICHIERS_MAX_OCTETS", str(100 * 1024 * 1024)))


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True, "brique": "audit-fichiers", "clamav_joignable": moteur.ping()}


@app.post("/scanner", tags=["scan"])
async def scanner(fichier: UploadFile = File(...), _cle: str = Depends(cle_api)):
    """Scanne un fichier (multipart). Fail-closed : ClamAV injoignable ⇒ 503, le
    fichier est REFUSÉ par précaution (jamais annoncé propre sans scan complet)."""
    data = await fichier.read()
    if not data:
        raise HTTPException(422, "Le fichier est vide.")
    if len(data) > MAX_OCTETS:
        raise HTTPException(413, f"Fichier trop volumineux (> {MAX_OCTETS} octets).")
    try:
        verdict = moteur.scanner(io.BytesIO(data))
    except moteur.MoteurIndisponible as e:
        raise HTTPException(503, f"Moteur antivirus indisponible : fichier refusé "
                                 f"par précaution ({e}).") from e
    return {"ok": True, "propre": verdict.propre, "raison": verdict.raison, "scanner": "clamav"}
