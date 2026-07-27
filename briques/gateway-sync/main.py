"""Brique « gateway-sync » — entretien des modèles gratuits de la Gateway (S202).

Pourquoi un service dédié plutôt qu'un script. `core/horloge.py` est DÉCLARATIF : une brique
annonce ses tâches dans son `manifest.json`, et l'horloge appelle un chemin HTTP sur SA base
(résolue par son `port`). Le fichier pose explicitement que « le Cœur ne code en dur AUCUNE
tâche métier ». Il faut donc une brique qui expose un endpoint — or l'image LiteLLM est
officielle et n'expose que ses propres routes. D'où ce service, minuscule et sans état.

Le bénéfice n'est pas que technique : l'horloge journalise chaque exécution et l'expose via
`GET /horloge/taches`. C'est précisément ce qui manquait — l'ancien `sync_free_models.py`
était orphelin depuis le premier jour (il annonçait une cible `make start-gateway`
inexistante) et sa liste a figé 51 jours sans que personne ne le voie.

Décision et alternatives écartées : `docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md`.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException

import sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dernier passage, en mémoire : l'état de référence est journalisé par l'horloge du Cœur
# (GET /horloge/taches). Ce champ sert à ce que /sante dise la vérité même consulté
# directement, sans passer par le Cœur.
_DERNIER: dict = {"quand": None, "resultat": None}


def _identite_service(x_api_key: str | None = Header(None),
                      authorization: str | None = Header(None)) -> None:
    """Gage `/sync` par GATEWAY_SYNC_KEY si elle est configurée (motif des autres briques).

    Sans clé, le service reste ouvert — cohérent avec le reste du parc en réseau privé.
    """
    cle = os.environ.get("GATEWAY_SYNC_KEY")
    if not cle:
        return
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if presentee != cle:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


def _synchroniser_et_tracer() -> dict:
    resultat = sync.synchroniser()
    _DERNIER["quand"] = datetime.now(timezone.utc).isoformat()
    _DERNIER["resultat"] = resultat
    return resultat


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Sync au démarrage : une base LiteLLM neuve n'a AUCUN modèle gratuit tant que rien n'a
    tourné (les `free/*` ne sont plus dans le YAML). Sans ce passage initial, un déploiement
    neuf attendrait le premier tick de l'horloge — jusqu'à 24 h sans cascade gratuite.
    Best-effort strict : une Gateway pas encore prête ne doit pas empêcher ce service de
    démarrer, l'horloge repassera."""
    try:
        r = _synchroniser_et_tracer()
        logger.info("gateway-sync : sync au démarrage → %s", r.get("statut"))
    except Exception as e:  # noqa: BLE001
        logger.warning("gateway-sync : sync au démarrage impossible (%s) — l'horloge repassera",
                       str(e)[:150])
    yield


app = FastAPI(title="Gateway Sync", version="0.1.0", lifespan=lifespan)


@app.get("/sante", tags=["système"])
def sante():
    """Expose la date du dernier sync : une liste qui fige doit se VOIR, c'est tout l'objet
    de cette brique."""
    return {"statut": "ok", "dernier_sync": _DERNIER["quand"],
            "dernier_resultat": _DERNIER["resultat"]}


@app.post("/sync", tags=["modeles"], dependencies=[Depends(_identite_service)])
def sync_route():
    """Aligne les modèles `free/*` de LiteLLM sur le catalogue OpenRouter du moment.

    Idempotent : le sync est différentiel (il compare puis n'applique que l'écart), donc
    deux appels rapprochés ne produisent aucun effet supplémentaire.
    """
    try:
        return _synchroniser_et_tracer()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Sync impossible : {str(e)[:200]}")
