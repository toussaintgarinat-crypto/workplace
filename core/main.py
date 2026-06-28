"""Cœur de Workplace — orchestrateur central.

Découvre les briques via leurs manifests et pilote l'usine à applications. Les routes
HTTP sont déclarées par domaine dans `routers/` (S114) ; ce fichier ne garde que le
cycle de vie (lifespan), la création de l'app et le montage des routers.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import horloge
import orchestrateur
import outils
import proactif
import routage_outils
from etat import registre
from routers import agenda, assistant, dashboard, profil, systeme, usine


@asynccontextmanager
async def lifespan(app: FastAPI):
    registre.charger()
    orchestrateur.init_db()
    proactif.init_db()
    horloge.init_db()
    # Routage d'outils par embeddings (opt-in ROUTAGE_OUTILS) : on indexe AU DÉMARRAGE les
    # descriptions d'outils pour pouvoir filtrer, à chaque requête, sur les plus pertinents.
    # Best-effort : une indexation ratée (Gateway KO, numpy absent) n'empêche jamais le démarrage
    # — `filtrer_outils` laissera simplement passer tous les outils (comportement actuel).
    try:
        await routage_outils.indexer(outils.outils_pour(registre))
    except Exception:  # noqa: BLE001 — le routage ne doit jamais bloquer le démarrage
        logging.getLogger(__name__).warning("Routage d'outils : indexation ignorée", exc_info=True)
    # Boucle proactive en tâche de fond (rappels : agenda imminent, docs à classer).
    tache_proactif = asyncio.create_task(proactif.boucle(registre))
    # Horloge : déclenche les tâches périodiques déclarées par les briques (S29).
    tache_horloge = asyncio.create_task(horloge.boucle(registre))
    yield
    tache_proactif.cancel()
    tache_horloge.cancel()


app = FastAPI(
    title="Workplace — Cœur",
    description="Orchestrateur central du projet Workplace. Découvre les briques via leurs manifests et pilote l'usine à applications (ETL→Audit→Génération→Déploiement).",
    version="0.2.0",
    lifespan=lifespan,
)

# Origines autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*" =
# comportement historique (front servi en local). Pour durcir en déploiement,
# définir CORS_ORIGINS=https://app.${DOMAIN} dans le .env.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(systeme.router)
app.include_router(usine.router)
app.include_router(dashboard.router)
app.include_router(assistant.router)
app.include_router(agenda.router)
app.include_router(profil.router)
