"""Brique « jeu-factions » — création de personnage + factions/territoire (PvE).

Réutilise le moteur holistique de `personnages` en HTTP (aucun calcul dupliqué). Voir
docs/superpowers/specs/2026-07-29-jeu-factions-design.md pour le design complet, et
docs/superpowers/specs/2026-07-30-jeu-factions-identite-design.md pour l'identité réelle
(S217) : `cle_api` est désormais un `sub` Keycloak vérifié par cookie, plus une clé partagée.
"""
import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import archetypes
import combat
import groupes
import jeton
import mobs
import moteur_personnages
import stockage
import zones

app = FastAPI(title="Jeu-factions — factions & territoire (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


def cle_api(request: Request) -> str:
    """Identité réelle (S217) : uniquement le cookie posé par `GET /` après vérification du
    jeton signé par le Cœur — plus de clé partagée, plus de mode ouvert (spec, Non-objectifs)."""
    identite = jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))
    if not identite:
        raise HTTPException(401, "Session Cœur requise — rouvre la tuile Jeu-factions depuis le Cœur.")
    stockage.migrer_public_si_premiere_connexion(identite)
    return identite


@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
    mobs.seed_mobs()


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


# Ne pilote plus aucune résolution passive (celle-ci a disparu avec
# `zones.resoudre_toutes_zones`, cf. spec combat) — purement cosmétique : « dernière zone
# visitée », affichée par défaut dans le front. Entrer en combat = ouvrir le WebSocket
# `/zones/{zone_id}/combat`, indépendamment de cette valeur.
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


@app.websocket("/zones/{zone_id}/combat")
async def combat_ws(websocket: WebSocket, zone_id: str, personnage_id: str = Query(...)):
    await websocket.accept()
    # S217 : le cookie posé par `GET /` est déjà là au moment du handshake — même origine,
    # envoyé automatiquement par le navigateur, pas de query param `api_key`.
    identite = jeton.verifier(websocket.cookies.get(jeton.COOKIE_NOM))
    if identite is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(identite, personnage_id)
    zone = zones.lire_zone(zone_id)
    if not perso or not zone:
        await websocket.close(code=4404)
        return
    signe = zones.signe_personnage(perso["snapshot_holistique"]) or "Bélier"
    element = dict(zones.ZONES_SEED).get(signe, "Feu")
    gabarits = mobs.lister_mobs_zone(zone_id)
    inst = await combat.rejoindre(zone_id, personnage_id, element, signe, gabarits)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    try:
        combat.enregistrer_connexion(inst, personnage_id, websocket)
        await websocket.send_json({"type": "etat", **combat.etat_public(inst), "evenements": []})
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())


_PAGE_REOUVRIR = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Jeu-factions</title>
<link rel="stylesheet" href="/workplace.css"></head>
<body><p>Session expirée ou absente — rouvre la tuile Jeu-factions depuis le tableau de
bord du Cœur.</p></body></html>"""


@app.get("/", include_in_schema=False)
def accueil(request: Request):
    """Point d'entrée : lit le jeton d'URL (posé par le Cœur, `?j=`) en priorité, sinon le
    cookie d'une navigation précédente (S217). Ni l'un ni l'autre -> page d'invite (401,
    HTML — cette route est la seule atteinte par une navigation humaine directe)."""
    jeton_url = request.query_params.get("j")
    identite = jeton.verifier(jeton_url) or jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))
    if not identite:
        return HTMLResponse(_PAGE_REOUVRIR, status_code=401)
    contenu = (Path(__file__).parent / "front.html").read_text(encoding="utf-8")
    reponse = HTMLResponse(contenu)
    if jeton_url:
        reponse.set_cookie(jeton.COOKIE_NOM, jeton.emettre(identite, ttl=8 * 3600),
                           max_age=8 * 3600, httponly=True, samesite="lax")
    return reponse


# Statique, pas de données — l'auth réelle est sur les fetch() qu'il déclenche (personnages/WS).
@app.get("/front_combat.html", response_class=FileResponse, include_in_schema=False)
def combat_front():
    return FileResponse(Path(__file__).parent / "front_combat.html")


@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")
