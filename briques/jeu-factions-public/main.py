"""Brique « jeu-factions-public » — exposition publique du jeu (S220). Comptes email + mot
de passe propres à la brique, AUCUNE dépendance à core/ ni à Keycloak — voir
docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md."""
import os
import re
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import jeton
import limiteur
import moderation
import stockage
import mobs
import zones

app = FastAPI(title="Jeu-factions-public — exposition publique du jeu (PvE)", version="0.1.0")

@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    mobs.seed_mobs()

_cors = [o.strip() for o in os.getenv("JEU_FACTIONS_PUBLIC_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ip_client(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def cle_api(request: Request) -> str:
    identite = jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))
    if not identite:
        raise HTTPException(401, "Session requise — connecte-toi.")
    return identite


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


class Inscription(BaseModel):
    email: str
    mot_de_passe: str
    pseudo: str


class Connexion(BaseModel):
    email: str
    mot_de_passe: str


def _poser_cookie_session(response: Response, compte_id: str) -> None:
    response.set_cookie(jeton.COOKIE_NOM, jeton.emettre(compte_id), max_age=jeton.TTL_SESSION,
                        httponly=True, samesite="lax", secure=True)


@app.post("/inscription", tags=["auth"])
def inscription_route(body: Inscription, request: Request, response: Response):
    if not limiteur.autorise(_ip_client(request)):
        raise HTTPException(429, "Trop de tentatives — réessaie plus tard.")
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(422, "Email invalide.")
    if len(body.mot_de_passe) < 8:
        raise HTTPException(422, "Mot de passe trop court (8 caractères minimum).")
    if not body.pseudo.strip() or moderation.contient_mot_banni(body.pseudo):
        raise HTTPException(422, "Pseudo refusé.")
    if stockage.lire_compte_par_email(body.email):
        raise HTTPException(409, "Cet email a déjà un compte.")
    try:
        compte = stockage.creer_compte(body.email, jeton.hacher_mot_de_passe(body.mot_de_passe),
                                       body.pseudo)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Cet email a déjà un compte.")
    stockage.assurer_joueur(compte["id"], body.pseudo)
    _poser_cookie_session(response, compte["id"])
    return {"ok": True}


@app.post("/connexion", tags=["auth"])
def connexion_route(body: Connexion, request: Request, response: Response):
    if not limiteur.autorise(_ip_client(request)):
        raise HTTPException(429, "Trop de tentatives — réessaie plus tard.")
    compte = stockage.lire_compte_par_email(body.email)
    if not compte or not jeton.verifier_mot_de_passe(body.mot_de_passe, compte["mot_de_passe_hash"]):
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    _poser_cookie_session(response, compte["id"])
    return {"ok": True}


@app.post("/deconnexion", tags=["auth"])
def deconnexion_route(response: Response):
    response.delete_cookie(jeton.COOKIE_NOM)
    return {"ok": True}


@app.get("/zones", tags=["zones"])
def lister_zones_route(cle: str = Depends(cle_api)):
    return zones.lister_zones()


@app.get("/zones/{zid}", tags=["zones"])
def lire_zone_route(zid: str, cle: str = Depends(cle_api)):
    z = zones.lire_zone(zid)
    if not z:
        raise HTTPException(404, "Zone introuvable.")
    return z
