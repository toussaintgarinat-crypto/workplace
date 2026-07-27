"""Brique « veille-info » — RSS multi-sources → résumé quotidien consolidé, v0.1.0.

Produit autonome (port 6120), isolé par personne (X-User-Id, motif mail S185/agenda S182).
Fetch programmé (tâche horloge quotidienne déclarée dans manifest.json) : voir digest.py.
Aucune génération audio dans cette version — spec séparé
(docs/superpowers/specs/2026-07-21-veille-info-brique-design.md).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import audio_global
import digest
import envoi_mail
import stockage

app = FastAPI(title="Veille-info — RSS multi-sources → résumé quotidien", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None),
                  x_user_id: Optional[str] = Header(None)) -> str:
    """Résout le tenant. Deux dialectes :

    (a) **Cœur / cercle privé (S185, motif agenda S182 / ecoute S184)** : la clé présentée
        == `VEILLE_INFO_KEY` (SEUL le Cœur la détient) ⇒ le Cœur emprunte l'identité de la
        personne connectée via `X-User-Id` (sinon repli `perso`) — chaque membre du foyer
        obtient SES sources, ses digests, isolés des autres, même s'ils partagent tous la
        même `VEILLE_INFO_KEY`.
    (b) **Tenant externe (bundle-client)** : toute AUTRE clé (ou son absence, en dev) ⇒
        motif historique, le tenant est l'**empreinte** (sha256 tronquée) de la clé —
        un client externe n'a jamais de `X-User-Id` à faire valoir.

    Fail-closed si `API_KEYS` défini (401 hors ces deux dialectes) ; sinon (dev) « public »."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    cle_coeur = os.environ.get("VEILLE_INFO_KEY")
    if cle_coeur and presentee == cle_coeur:
        return f"perso:{x_user_id or 'perso'}"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /digest/executer : jeton partagé VEILLE_INFO_KEY, PAS tenant_actuel — cette
    route traite TOUTES les personnes en un seul appel (motif horloge), elle n'est donc pas
    scopée à un seul tenant. Fail-closed si VEILLE_INFO_KEY est défini."""
    attendu = os.environ.get("VEILLE_INFO_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "version": "0.1.0"}


class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)
    thematique: str = ""


@app.get("/sources", tags=["sources"])
def lister_sources_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_sources(tenant)


@app.post("/sources", tags=["sources"], status_code=201)
def creer_source_route(body: CreerSource, tenant: str = Depends(tenant_actuel)):
    return stockage.creer_source(tenant, body.nom, body.url, body.thematique)


@app.delete("/sources/{source_id}", tags=["sources"])
def supprimer_source_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    ok = stockage.supprimer_source(tenant, source_id)
    if not ok:
        raise HTTPException(404, "Source introuvable.")
    return {"ok": True}


class RetaggerSource(BaseModel):
    thematique: str = ""


@app.patch("/sources/{source_id}/thematique", tags=["sources"])
def retagger_source_route(source_id: int, body: RetaggerSource,
                          tenant: str = Depends(tenant_actuel)):
    ok = stockage.retagger_source(tenant, source_id, body.thematique)
    if not ok:
        raise HTTPException(404, "Source introuvable.")
    return {"ok": True}


@app.get("/thematiques", tags=["sources"])
def lister_thematiques_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_thematiques(tenant)


class BasculerPauseThematique(BaseModel):
    thematique: str
    en_pause: bool


@app.patch("/thematiques/pause", tags=["sources"])
def basculer_pause_thematique_route(body: BasculerPauseThematique,
                                    tenant: str = Depends(tenant_actuel)):
    n = stockage.basculer_pause_thematique(tenant, body.thematique, body.en_pause)
    if n == 0:
        raise HTTPException(404, "Thématique introuvable.")
    return {"ok": True, "nb_sources": n}


@app.get("/digests", tags=["digests"])
def lister_digests_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_digests(tenant)


@app.get("/digests/{digest_id}", tags=["digests"])
def lire_digest_route(digest_id: int, tenant: str = Depends(tenant_actuel)):
    d = stockage.digest_get(tenant, digest_id)
    if d is None:
        raise HTTPException(404, "Digest introuvable.")
    return d


class GenererAudioGlobal(BaseModel):
    ordre_thematiques: list[int] = Field(min_length=1)


class EnvoyerAudioGlobal(BaseModel):
    destinataires: list[str] = Field(min_length=1)
    sujet: str | None = None
    message: str | None = None


class GenererEtEnvoyerAudioGlobal(BaseModel):
    ordre_thematiques: list[int] = Field(min_length=1)
    destinataires: list[str] = Field(min_length=1)
    sujet: str | None = None
    message: str | None = None


@app.post("/audio-global/generer", tags=["audio-global"])
def generer_audio_global_route(body: GenererAudioGlobal, tenant: str = Depends(tenant_actuel)):
    try:
        return audio_global.generer(tenant, body.ordre_thematiques)
    except audio_global.AudioGlobalError as e:
        raise HTTPException(422, str(e))


@app.get("/audio-global", tags=["audio-global"])
def lister_audio_global_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_audio_global(tenant)


@app.get("/audio-global/{jeton}.mp3", tags=["audio-global"], include_in_schema=False)
def telecharger_audio_global_route(jeton: str):
    a = stockage.audio_global_par_jeton(jeton)
    if a is None:
        raise HTTPException(404, "Audio introuvable.")
    if datetime.fromisoformat(a["expire_le"]) <= datetime.now(timezone.utc):
        raise HTTPException(404, "Ce lien a expiré.")
    return FileResponse(a["fichier_path"], media_type="audio/mpeg")


def _envoyer_audio_global(tenant: str, audio_id: int, destinataires: list[str],
                          sujet: str | None, message: str | None, base_url: str) -> dict:
    a = stockage.audio_global_get(tenant, audio_id)
    if a is None:
        raise HTTPException(404, "Audio introuvable.")
    base = os.getenv("VEILLE_INFO_PUBLIC_URL", "").rstrip("/") or base_url.rstrip("/")
    lien = f"{base}/audio-global/{a['jeton']}.mp3"
    resultats = []
    for dest in destinataires:
        try:
            envoi_mail.envoyer(tenant, dest, lien, sujet, message)
            stockage.inserer_envoi_audio_global(audio_id, dest, "envoye", None)
            resultats.append({"destinataire": dest, "ok": True})
        except envoi_mail.EnvoiAudioGlobalError as e:  # noqa: BLE001 — un échec par destinataire
            stockage.inserer_envoi_audio_global(audio_id, dest, "echec", str(e))
            resultats.append({"destinataire": dest, "ok": False, "erreur": str(e)})
    return {"resultats": resultats}


@app.post("/audio-global/{audio_id}/envoyer", tags=["audio-global"])
def envoyer_audio_global_route(audio_id: int, body: EnvoyerAudioGlobal, request: Request,
                               tenant: str = Depends(tenant_actuel)):
    return _envoyer_audio_global(tenant, audio_id, body.destinataires, body.sujet,
                                 body.message, str(request.base_url))


@app.post("/audio-global/generer-et-envoyer", tags=["audio-global"])
def generer_et_envoyer_audio_global_route(body: GenererEtEnvoyerAudioGlobal, request: Request,
                                          tenant: str = Depends(tenant_actuel)):
    try:
        audio = audio_global.generer(tenant, body.ordre_thematiques)
    except audio_global.AudioGlobalError as e:
        raise HTTPException(422, str(e))
    envoi = _envoyer_audio_global(tenant, audio["id"], body.destinataires, body.sujet,
                                  body.message, str(request.base_url))
    return {**audio, "envoi": envoi}


@app.post("/digest/executer", tags=["digest"])
def executer_digest_route(_: None = Depends(verifier_cle_horloge)):
    return digest.executer_digest_quotidien()
