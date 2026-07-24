"""Proxy de fichiers de brique : sert les images/vidéos/exports produits par un outil
assistant sous une URL atteignable par le NAVIGATEUR du Cœur.

Motif : les briques media (images, video, export) rapatrient toujours leur production et
la servent depuis leur propre stockage local (`/fichiers/{nom}`, cf. briques/images/moteur.py
`_enregistrer`). Cette URL n'est relative qu'au port INTERNE Docker de la brique — sans ce
proxy, le résultat d'un outil comme `image_generer` renvoie une URL jamais résolvable par le
navigateur (S196). `core/outils_communs.py::_appel_dynamique` réécrit `url` en
`/brique-fichiers/{brique}/{nom}` pour les briques listées ci-dessous ; ce router sert
cette URL en la rejouant vers la vraie brique.

Ces endpoints `/fichiers/{nom}` ne portent aucune authentification côté brique (fichiers
nommés par uuid, pas de notion multi-tenant côté media) — le seul garde-fou nécessaire est
la session Cœur, déjà exigée par `main.py` sur ce router."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

import orchestrateur
from etat import registre

router = APIRouter()

_TIMEOUT = 30.0
# Briques dont l'endpoint `/fichiers/{nom}` peut être rejoué vers le navigateur.
_BRIQUES_AUTORISEES = {"images", "video", "export"}


@router.get("/brique-fichiers/{brique}/{nom}")
async def brique_fichier(brique: str, nom: str):
    if brique not in _BRIQUES_AUTORISEES:
        raise HTTPException(404, "Brique média inconnue.")
    base = orchestrateur._brique_base(registre, brique)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{base}/fichiers/{nom}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, "Fichier introuvable.")
    return Response(content=r.content, media_type=r.headers.get("content-type"))
