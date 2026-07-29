"""Brique « jeu-factions » — création de personnage + factions/territoire (PvE).

Réutilise le moteur holistique de `personnages` en HTTP (aucun calcul dupliqué). Voir
docs/superpowers/specs/2026-07-29-jeu-factions-design.md pour le design complet.
"""
import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import archetypes
import combat
import groupes
import mobs
import moteur_personnages
import stockage
import tick
import zones

app = FastAPI(title="Jeu-factions — factions & territoire (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API et sert de tenant. Vide = mode ouvert → tenant "public"."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
    mobs.seed_mobs()
    if os.getenv("JEU_FACTIONS_TICK_AUTOSTART", "1") != "0":
        asyncio.create_task(tick.boucle_tick())


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


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


class CreerGroupe(BaseModel):
    personnage_cible_id: str
    zone_archetype_id: str


class RejoindreGroupe(BaseModel):
    personnage_id: str


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


@app.get("/personnages", tags=["personnages"])
def lister_personnages_route(cle: str = Depends(cle_api)):
    return stockage.lister_personnages(cle)


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


@app.get("/personnages/{pid}/competences", tags=["personnages"])
def lister_competences_route(pid: str, cle: str = Depends(cle_api)):
    if not stockage.lire_personnage(cle, pid):
        raise HTTPException(404, "Personnage introuvable.")
    return archetypes.lister_competences_debloquees(pid)


def _cle_depuis_query(api_key: str) -> str | None:
    """Même validation que `cle_api` (Header) mais pour le WebSocket : le navigateur ne
    peut pas poser d'en-tête personnalisé à la connexion — la clé passe en query param."""
    if not API_KEYS:
        return api_key or "public"
    return api_key if api_key in API_KEYS else None


@app.websocket("/zones/{zone_id}/combat")
async def combat_ws(websocket: WebSocket, zone_id: str,
                    personnage_id: str = Query(...), api_key: str = Query("")):
    await websocket.accept()
    cle = _cle_depuis_query(api_key)
    if cle is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(cle, personnage_id)
    zone = zones.lire_zone(zone_id)
    if not perso or not zone:
        await websocket.close(code=4404)
        return
    signe = zones.signe_personnage(perso["snapshot_holistique"]) or "Bélier"
    element = dict(zones.ZONES_SEED).get(signe, "Feu")
    gabarits = mobs.lister_mobs_zone(zone_id)
    inst = await combat.rejoindre(zone_id, personnage_id, element, signe, gabarits)
    combat.enregistrer_connexion(inst, personnage_id, websocket)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    await websocket.send_json({"type": "etat", **combat.etat_public(inst)})
    try:
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())


@app.get("/", response_class=FileResponse, include_in_schema=False)
def accueil():
    return FileResponse(Path(__file__).parent / "front.html")


@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")
