"""Brique « jeu-factions-public » — exposition publique du jeu (S220). Comptes email + mot
de passe propres à la brique, AUCUNE dépendance à core/ ni à Keycloak — voir
docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md."""
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import moteur_personnages

import jeton
import limiteur
import moderation
import stockage
import mobs
import zones
import archetypes
import mobs_archetype
import groupes

app = FastAPI(title="Jeu-factions-public — exposition publique du jeu (PvE)", version="0.1.0")

@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
    mobs.seed_mobs()
    mobs_archetype.seed_mobs_archetype()

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


class CreerPersonnage(BaseModel):
    nom: str
    prenoms: str = ""
    date_naissance: Optional[str] = None
    heure_naissance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset: Optional[float] = None
    description: Optional[str] = None


class AssignerZone(BaseModel):
    zone_id: str


class Connexion(BaseModel):
    email: str
    mot_de_passe: str


class CreerGroupe(BaseModel):
    personnage_cible_id: str
    zone_archetype_id: str


class RejoindreGroupe(BaseModel):
    personnage_id: str


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


@app.get("/archetypes/{archetype}/etapes", tags=["archetypes"])
def lister_etapes_route(archetype: str, cle: str = Depends(cle_api)):
    if archetype not in archetypes.ARCHETYPES_SIGNATURE:
        raise HTTPException(404, "Archétype inconnu.")
    return archetypes.lister_etapes(archetype)


@app.post("/groupes", tags=["archetypes"])
def creer_groupe_route(body: CreerGroupe, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, body.personnage_cible_id):
        raise HTTPException(404, "Personnage introuvable.")
    try:
        return groupes.creer_groupe(body.personnage_cible_id, body.zone_archetype_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/groupes/{gid}/rejoindre", tags=["archetypes"])
def rejoindre_groupe_route(gid: str, body: RejoindreGroupe, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, body.personnage_id):
        raise HTTPException(404, "Personnage introuvable.")
    try:
        return groupes.rejoindre_groupe(gid, body.personnage_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/personnages", tags=["personnages"])
async def creer_personnage_route(body: CreerPersonnage, cle: str = Depends(cle_api)):
    a_une_date = bool((body.date_naissance or "").strip())
    a_une_description = bool((body.description or "").strip())
    if not a_une_date and not a_une_description:
        raise HTTPException(422, "Fournis une date de naissance ou une description.")

    if a_une_date:
        donnees_naissance = {"date_naissance": body.date_naissance,
                             "heure_naissance": body.heure_naissance,
                             "latitude": body.latitude, "longitude": body.longitude,
                             "utc_offset": body.utc_offset}
        fiche = {**donnees_naissance, "prenoms": body.prenoms, "nom": body.nom}
    else:
        donnees_naissance = {"description": body.description}
        ri = await moteur_personnages.recherche_inverse(body.description)
        exemple_date = ri.get("exemple_date")
        if not exemple_date:
            raise HTTPException(422, "Description trop vague : aucune date déduite. "
                                     "Précise le caractère ou fournis une date.")
        fiche = {"date_naissance": exemple_date, "prenoms": body.prenoms, "nom": body.nom}

    resultat = await moteur_personnages.portrait(fiche)
    stockage.assurer_joueur(cle)
    return stockage.creer_personnage(cle, body.nom, donnees_naissance, resultat)


@app.post("/presence", tags=["personnages"])
def enregistrer_presence_route(cle: str = Depends(cle_api)):
    stockage.enregistrer_presence(cle)
    return {"ok": True}


@app.get("/personnages", tags=["personnages"])
def lister_personnages_route(cle: str = Depends(cle_api)):
    personnages = stockage.lister_personnages(cle)
    derniere_presence = stockage.lire_derniere_presence(cle)
    maintenant = datetime.now(timezone.utc)
    for p in personnages:
        archetype = (p["snapshot_holistique"].get("portrait") or {}).get("archetype")
        prochaine = archetypes.prochaine_etape(p["id"], archetype) if archetype else None
        p["bonus_idle_actuel"] = (
            archetypes.bonus_idle(derniere_presence, maintenant,
                                  archetypes.TAUX_IDLE_PAR_HEURE, archetypes.PLAFOND_IDLE_HEURES)
            if prochaine else 0)
    return personnages


@app.get("/personnages/{pid}", tags=["personnages"])
def lire_personnage_route(pid: str, cle: str = Depends(cle_api)):
    p = stockage.lire_personnage(cle, pid)
    if not p:
        raise HTTPException(404, "Personnage introuvable.")
    p["progressions"] = archetypes.lister_progressions_personnage(pid)
    p["competences"] = archetypes.lister_competences_debloquees(pid)
    return p


@app.patch("/personnages/{pid}/zone", tags=["personnages"])
def assigner_zone_route(pid: str, body: AssignerZone, cle: str = Depends(cle_api)):
    if not zones.lire_zone(body.zone_id):
        raise HTTPException(404, "Zone introuvable.")
    p = stockage.assigner_zone(cle, pid, body.zone_id)
    if not p:
        raise HTTPException(404, "Personnage introuvable.")
    return p


@app.get("/personnages/{pid}/competences", tags=["personnages"])
def lister_competences_route(pid: str, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, pid):
        raise HTTPException(404, "Personnage introuvable.")
    return archetypes.lister_competences_debloquees(pid)
